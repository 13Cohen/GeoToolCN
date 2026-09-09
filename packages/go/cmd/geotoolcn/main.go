// Command geotoolcn exposes the library to languages that have no binding.
//
//	geotoolcn reverse 39.9042 116.4074
//	geotoolcn serve --addr :8080
//
// Written in Go because it cross-compiles to a single static binary with the
// dataset embedded — there is nothing to install alongside it.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	geotoolcn "github.com/13Cohen/geotoolcn-go"
)

const usage = `geotoolcn — 中国行政区划离线地理编码

用法:
  geotoolcn reverse <lat> <lng>          坐标 → 省/市/区县
  geotoolcn lookup <adcode>              adcode → 完整层级链
  geotoolcn search <query> [--level L] [--province P] [--city C]
  geotoolcn tree                         行政区划树（JSON）
  geotoolcn convert <from> <to> <lng> <lat>
                                         坐标系转换，from/to ∈ wgs84|gcj02|bd09
                                         注意：经度在前
  geotoolcn serve [--addr :8080]         起 HTTP 服务
  geotoolcn version

所有子命令输出 JSON，便于管道处理:
  geotoolcn reverse 39.9042 116.4074 | jq -r .district.name
`

var version = "3.0.0"

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}

	geo, err := geotoolcn.New()
	if err != nil {
		fail(err)
	}

	switch os.Args[1] {
	case "reverse":
		cmdReverse(geo, os.Args[2:])
	case "lookup":
		cmdLookup(geo, os.Args[2:])
	case "search":
		cmdSearch(geo, os.Args[2:])
	case "tree":
		cmdTree()
	case "convert":
		cmdConvert(os.Args[2:])
	case "serve":
		cmdServe(geo, os.Args[2:])
	case "version", "--version", "-v":
		emit(map[string]string{"version": version})
	case "help", "--help", "-h":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "未知子命令: %s\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
}

func fail(err error) {
	_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"error": err.Error()})
	os.Exit(1)
}

func emit(v any) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		fail(err)
	}
}

func parseCoords(args []string) (float64, float64) {
	if len(args) < 2 {
		fail(fmt.Errorf("需要 <lat> <lng> 两个参数"))
	}
	lat, err := strconv.ParseFloat(args[0], 64)
	if err != nil {
		fail(fmt.Errorf("纬度无效: %s", args[0]))
	}
	lng, err := strconv.ParseFloat(args[1], 64)
	if err != nil {
		fail(fmt.Errorf("经度无效: %s", args[1]))
	}
	return lat, lng
}

func cmdReverse(geo *geotoolcn.GeoTool, args []string) {
	lat, lng := parseCoords(args)
	emit(geo.Reverse(lat, lng))
}

func cmdLookup(geo *geotoolcn.GeoTool, args []string) {
	if len(args) < 1 {
		fail(fmt.Errorf("需要 <adcode> 参数"))
	}
	result := geo.LookupAdcode(args[0])
	if result == nil {
		fail(fmt.Errorf("未找到 adcode %q", args[0]))
	}
	emit(result)
}

func cmdSearch(geo *geotoolcn.GeoTool, args []string) {
	fs := flag.NewFlagSet("search", flag.ExitOnError)
	level := fs.String("level", "", "province|city|district")
	province := fs.String("province", "", "限定省份（名称或 adcode）")
	city := fs.String("city", "", "限定城市（名称或 adcode）")
	exact := fs.Bool("exact", false, "关闭子串模糊匹配")
	if len(args) < 1 {
		fail(fmt.Errorf("需要 <query> 参数"))
	}
	query := args[0]
	_ = fs.Parse(args[1:])

	emit(geo.Search(query, geotoolcn.SearchOptions{
		Level: *level, Province: *province, City: *city, NoFuzzy: *exact,
	}))
}

func cmdTree() {
	tree, err := geotoolcn.GetAdministrativeTree()
	if err != nil {
		fail(err)
	}
	emit(tree)
}

var converters = map[string]func(float64, float64) (float64, float64){
	"wgs84>gcj02": geotoolcn.WGS84ToGCJ02,
	"gcj02>wgs84": geotoolcn.GCJ02ToWGS84,
	"gcj02>bd09":  geotoolcn.GCJ02ToBD09,
	"bd09>gcj02":  geotoolcn.BD09ToGCJ02,
	"wgs84>bd09":  geotoolcn.WGS84ToBD09,
	"bd09>wgs84":  geotoolcn.BD09ToWGS84,
}

func cmdConvert(args []string) {
	if len(args) < 4 {
		fail(fmt.Errorf("用法: convert <from> <to> <lng> <lat>"))
	}
	key := strings.ToLower(args[0]) + ">" + strings.ToLower(args[1])
	fn, ok := converters[key]
	if !ok {
		fail(fmt.Errorf("不支持的转换 %s → %s", args[0], args[1]))
	}
	// Longitude first, matching the library's conversion signatures.
	lng, err := strconv.ParseFloat(args[2], 64)
	if err != nil {
		fail(fmt.Errorf("经度无效: %s", args[2]))
	}
	lat, err := strconv.ParseFloat(args[3], 64)
	if err != nil {
		fail(fmt.Errorf("纬度无效: %s", args[3]))
	}
	outLng, outLat := fn(lng, lat)
	emit(map[string]float64{"lng": outLng, "lat": outLat})
}

func cmdServe(geo *geotoolcn.GeoTool, args []string) {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	addr := fs.String("addr", ":8080", "监听地址")
	_ = fs.Parse(args)

	mux := http.NewServeMux()

	respond := func(w http.ResponseWriter, status int, v any) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(status)
		enc := json.NewEncoder(w)
		enc.SetEscapeHTML(false)
		_ = enc.Encode(v)
	}
	badRequest := func(w http.ResponseWriter, format string, a ...any) {
		respond(w, http.StatusBadRequest, map[string]string{
			"error": fmt.Sprintf(format, a...),
		})
	}
	floatParam := func(r *http.Request, name string) (float64, bool) {
		raw := r.URL.Query().Get(name)
		if raw == "" {
			return 0, false
		}
		v, err := strconv.ParseFloat(raw, 64)
		return v, err == nil
	}

	mux.HandleFunc("/reverse", func(w http.ResponseWriter, r *http.Request) {
		lat, okLat := floatParam(r, "lat")
		lng, okLng := floatParam(r, "lng")
		if !okLat || !okLng {
			badRequest(w, "需要数值参数 lat 与 lng")
			return
		}
		respond(w, http.StatusOK, geo.Reverse(lat, lng))
	})

	mux.HandleFunc("/lookup", func(w http.ResponseWriter, r *http.Request) {
		adcode := r.URL.Query().Get("adcode")
		result := geo.LookupAdcode(adcode)
		if result == nil {
			respond(w, http.StatusNotFound, map[string]string{
				"error": fmt.Sprintf("未找到 adcode %q", adcode),
			})
			return
		}
		respond(w, http.StatusOK, result)
	})

	mux.HandleFunc("/search", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		query := q.Get("q")
		if query == "" {
			badRequest(w, "需要参数 q")
			return
		}
		respond(w, http.StatusOK, geo.Search(query, geotoolcn.SearchOptions{
			Level:    q.Get("level"),
			Province: q.Get("province"),
			City:     q.Get("city"),
			NoFuzzy:  q.Get("exact") == "1",
		}))
	})

	mux.HandleFunc("/regions", func(w http.ResponseWriter, r *http.Request) {
		regions, err := geo.ListRegions(r.URL.Query().Get("level"))
		if err != nil {
			badRequest(w, "%s", err)
			return
		}
		respond(w, http.StatusOK, regions)
	})

	mux.HandleFunc("/tree", func(w http.ResponseWriter, r *http.Request) {
		tree, err := geotoolcn.GetAdministrativeTree()
		if err != nil {
			respond(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		respond(w, http.StatusOK, tree)
	})

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		respond(w, http.StatusOK, map[string]string{"status": "ok", "version": version})
	})

	announce(*addr)
	server := &http.Server{
		Addr:    *addr,
		Handler: mux,
		// Bounded so an idle or hostile client cannot hold a connection open
		// while sending headers one byte at a time.
		ReadHeaderTimeout: 5 * time.Second,
	}
	if err := server.ListenAndServe(); err != nil {
		fail(err)
	}
}

// announce writes the route list to stderr, leaving stdout clean for piping.
func announce(addr string) {
	fmt.Fprintf(os.Stderr, "geotoolcn %s listening on %s\n", version, addr)
	for _, route := range []string{
		"GET /reverse?lat=39.9042&lng=116.4074",
		"GET /lookup?adcode=110108",
		"GET /search?q=深圳市&province=广东省",
		"GET /regions?level=province",
		"GET /tree",
		"GET /healthz",
	} {
		fmt.Fprintf(os.Stderr, "  %s\n", route)
	}
}
