// Command geotoolcn exposes the library to languages that have no binding.
//
//	geotoolcn reverse 39.9042 116.4074
//	geotoolcn serve --addr :8080
//
// Written in Go because it cross-compiles to a single static binary with the
// dataset embedded — there is nothing to install alongside it.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math"
	"net"
	"net/http"
	"os"
	"os/signal"
	"runtime/debug"
	"strconv"
	"strings"
	"syscall"
	"time"

	geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"
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

// version is injected at release time with -ldflags "-X main.version=...".
// When it is not — `go install ...@v3.1.0`, a local `go build` — the module
// version Go recorded in the binary is the next best thing, so the literal
// here is only what a build from an untagged tree reports.
var version = "dev"

func init() {
	if version != "dev" {
		return
	}
	if info, ok := debug.ReadBuildInfo(); ok && info.Main.Version != "" && info.Main.Version != "(devel)" {
		version = strings.TrimPrefix(info.Main.Version, "v")
	}
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}

	// Subcommands that never touch the dataset skip parsing it. Cheap, but
	// `version` is what health checks and CI call in a loop.
	switch os.Args[1] {
	case "version", "--version", "-v":
		emit(map[string]string{"version": version})
		return
	case "help", "--help", "-h":
		fmt.Print(usage)
		return
	case "tree":
		cmdTree()
		return
	case "convert":
		cmdConvert(os.Args[2:])
		return
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
	case "serve":
		cmdServe(geo, os.Args[2:])
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

// parseCoordinate accepts what strconv does, minus the values that are
// syntactically numbers but never coordinates: NaN, ±Inf and anything past
// the poles or the antimeridian. Those would otherwise be answered with an
// empty chain and a 200, indistinguishable from "outside China".
func parseCoordinate(raw string, limit float64) (float64, error) {
	v, err := strconv.ParseFloat(raw, 64)
	if err != nil || math.IsNaN(v) || math.IsInf(v, 0) || math.Abs(v) > limit {
		return 0, fmt.Errorf("%q 不是 [-%g, %g] 内的数值", raw, limit, limit)
	}
	return v, nil
}

func parseCoords(args []string) (float64, float64) {
	if len(args) < 2 {
		fail(fmt.Errorf("需要 <lat> <lng> 两个参数"))
	}
	lat, err := parseCoordinate(args[0], 90)
	if err != nil {
		fail(fmt.Errorf("纬度无效: %w", err))
	}
	lng, err := parseCoordinate(args[1], 180)
	if err != nil {
		fail(fmt.Errorf("经度无效: %w", err))
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
	fs := newFlagSet("search")
	level := fs.String("level", "", "province|city|district")
	province := fs.String("province", "", "限定省份（名称或 adcode）")
	city := fs.String("city", "", "限定城市（名称或 adcode）")
	exact := fs.Bool("exact", false, "关闭子串模糊匹配")
	if len(args) < 1 {
		fail(fmt.Errorf("需要 <query> 参数"))
	}
	query := args[0]
	// The query is positional and comes first. A query that looks like a flag
	// is far more likely a misplaced flag than a region called "--level".
	if strings.HasPrefix(query, "-") {
		fail(fmt.Errorf("查询串 %q 以 - 开头；用法: search <query> [--level L] [--province P] [--city C]", query))
	}
	if err := fs.Parse(args[1:]); err != nil {
		fail(err)
	}
	if *level != "" && !validLevel(*level) {
		fail(fmt.Errorf("level 必须是 province、city 或 district，不是 %q", *level))
	}

	emit(geo.Search(query, geotoolcn.SearchOptions{
		Level: *level, Province: *province, City: *city, NoFuzzy: *exact,
	}))
}

// newFlagSet returns a FlagSet whose errors come back to the caller, so a bad
// flag is reported as {"error": ...} with exit 1 like every other failure
// rather than as Go's usage text with exit 2.
func newFlagSet(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(nopWriter{})
	return fs
}

type nopWriter struct{}

func (nopWriter) Write(p []byte) (int, error) { return len(p), nil }

func validLevel(level string) bool {
	for _, l := range geotoolcn.Levels {
		if l == level {
			return true
		}
	}
	return false
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
	fs := newFlagSet("serve")
	addr := fs.String("addr", ":8080", "监听地址")
	if err := fs.Parse(args); err != nil {
		fail(err)
	}

	// A server answers the same regions over and over; paying the full
	// decode once at start-up beats a stall on the first request to each.
	geo.PreloadGeometry()

	mux := http.NewServeMux()

	respond := func(w http.ResponseWriter, status int, v any) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(status)
		enc := json.NewEncoder(w)
		enc.SetEscapeHTML(false)
		_ = enc.Encode(v)
	}
	respondError := func(w http.ResponseWriter, status int, format string, a ...any) {
		respond(w, status, map[string]string{"error": fmt.Sprintf(format, a...)})
	}
	badRequest := func(w http.ResponseWriter, format string, a ...any) {
		respondError(w, http.StatusBadRequest, format, a...)
	}
	coordParam := func(r *http.Request, name string, limit float64) (float64, error) {
		raw := r.URL.Query().Get(name)
		if raw == "" {
			return 0, fmt.Errorf("缺少参数 %s", name)
		}
		return parseCoordinate(raw, limit)
	}
	// Every route is a read; anything else is 405 with the JSON body the
	// docs promise, and an unknown path is a JSON 404 rather than net/http's
	// text/plain default.
	get := func(pattern string, h func(w http.ResponseWriter, r *http.Request)) {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodGet && r.Method != http.MethodHead {
				w.Header().Set("Allow", "GET, HEAD")
				respondError(w, http.StatusMethodNotAllowed, "只支持 GET")
				return
			}
			h(w, r)
		})
	}

	get("/reverse", func(w http.ResponseWriter, r *http.Request) {
		lat, errLat := coordParam(r, "lat", 90)
		lng, errLng := coordParam(r, "lng", 180)
		if err := errors.Join(errLat, errLng); err != nil {
			badRequest(w, "%s", strings.ReplaceAll(err.Error(), "\n", "; "))
			return
		}
		respond(w, http.StatusOK, geo.Reverse(lat, lng))
	})

	get("/lookup", func(w http.ResponseWriter, r *http.Request) {
		adcode := r.URL.Query().Get("adcode")
		if adcode == "" {
			badRequest(w, "缺少参数 adcode")
			return
		}
		result := geo.LookupAdcode(adcode)
		if result == nil {
			respondError(w, http.StatusNotFound, "未找到 adcode %q", adcode)
			return
		}
		respond(w, http.StatusOK, result)
	})

	get("/search", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		query := q.Get("q")
		if query == "" {
			badRequest(w, "需要参数 q")
			return
		}
		level := q.Get("level")
		if level != "" && !validLevel(level) {
			badRequest(w, "level 必须是 province、city 或 district，不是 %q", level)
			return
		}
		exact := q.Get("exact")
		respond(w, http.StatusOK, geo.Search(query, geotoolcn.SearchOptions{
			Level:    level,
			Province: q.Get("province"),
			City:     q.Get("city"),
			NoFuzzy:  exact == "1" || exact == "true",
		}))
	})

	get("/regions", func(w http.ResponseWriter, r *http.Request) {
		regions, err := geo.ListRegions(r.URL.Query().Get("level"))
		if err != nil {
			badRequest(w, "%s", err)
			return
		}
		respond(w, http.StatusOK, regions)
	})

	get("/tree", func(w http.ResponseWriter, r *http.Request) {
		tree, err := geotoolcn.GetAdministrativeTree()
		if err != nil {
			respondError(w, http.StatusInternalServerError, "%s", err)
			return
		}
		respond(w, http.StatusOK, tree)
	})

	get("/healthz", func(w http.ResponseWriter, r *http.Request) {
		respond(w, http.StatusOK, map[string]string{"status": "ok", "version": version})
	})

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		respondError(w, http.StatusNotFound, "没有路由 %s", r.URL.Path)
	})

	server := &http.Server{
		Handler: mux,
		// Bounded so an idle or hostile client cannot hold a connection open
		// while sending headers one byte at a time, nor keep a response
		// socket busy indefinitely. The largest response (/tree, ~160 KB)
		// is well inside the write budget.
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	// Bind first, announce second: the log must not claim to be listening on
	// a port that turned out to be taken.
	listener, err := net.Listen("tcp", *addr)
	if err != nil {
		fail(err)
	}
	announce(listener.Addr().String())

	// In the container this process is PID 1 and gets SIGTERM straight from
	// the runtime; without a handler Go exits with status 2 mid-request.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	serveErr := make(chan error, 1)
	go func() { serveErr <- server.Serve(listener) }()

	select {
	case err := <-serveErr:
		fail(err)
	case <-ctx.Done():
		stop()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			fail(err)
		}
		fmt.Fprintln(os.Stderr, "geotoolcn: shut down")
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
