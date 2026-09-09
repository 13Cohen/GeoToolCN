// Conformance adapter for the Go implementation.
//
//	go build -o /tmp/gtc-adapter ./cmd/conformance-adapter
//	python conformance/run.py --adapter cmd --cmd /tmp/gtc-adapter
//
// Reads one JSON request per line on stdin, writes one JSON response per line
// on stdout. Adding a language means writing a file like this one.
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"

	geotoolcn "github.com/13Cohen/geotoolcn-go"
)

type request struct {
	Op   string            `json:"op"`
	Args []json.RawMessage `json:"args"`
}

type response struct {
	// No omitempty on OK: it would drop `false`, `0` and empty slices, turning
	// is_in_china=false and a no-match search into a missing field.
	OK    any    `json:"ok"`
	Error string `json:"error,omitempty"`
}

var conversions = map[string]func(float64, float64) (float64, float64){
	"wgs84_to_gcj02": geotoolcn.WGS84ToGCJ02,
	"gcj02_to_wgs84": geotoolcn.GCJ02ToWGS84,
	"gcj02_to_bd09":  geotoolcn.GCJ02ToBD09,
	"bd09_to_gcj02":  geotoolcn.BD09ToGCJ02,
	"wgs84_to_bd09":  geotoolcn.WGS84ToBD09,
	"bd09_to_wgs84":  geotoolcn.BD09ToWGS84,
}

func chain(r *geotoolcn.ReverseResult) []any {
	code := func(x *geotoolcn.Region) any {
		if x == nil {
			return nil
		}
		return x.Code
	}
	return []any{code(r.Province), code(r.City), code(r.District)}
}

// canonical mirrors Python's json.dumps(sort_keys=True, separators=(",",":"),
// ensure_ascii=False) so the tree hash matches across languages.
func canonical(v any) string {
	switch value := v.(type) {
	case map[string]any:
		keys := make([]string, 0, len(value))
		for k := range value {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		parts := make([]string, 0, len(keys))
		for _, k := range keys {
			kb, _ := json.Marshal(k)
			parts = append(parts, fmt.Sprintf("%s:%s", kb, canonical(value[k])))
		}
		return "{" + strings.Join(parts, ",") + "}"
	case []any:
		parts := make([]string, 0, len(value))
		for _, item := range value {
			parts = append(parts, canonical(item))
		}
		return "[" + strings.Join(parts, ",") + "]"
	default:
		// SetEscapeHTML(false): Go escapes <, > and & by default, Python does not.
		var sb strings.Builder
		enc := json.NewEncoder(&sb)
		enc.SetEscapeHTML(false)
		_ = enc.Encode(v)
		return strings.TrimRight(sb.String(), "\n")
	}
}

func handle(geo *geotoolcn.GeoTool, req request) (any, error) {
	num := func(i int) float64 {
		var f float64
		_ = json.Unmarshal(req.Args[i], &f)
		return f
	}
	str := func(i int) string {
		var s string
		_ = json.Unmarshal(req.Args[i], &s)
		return s
	}

	switch req.Op {
	case "reverse":
		r := geo.Reverse(num(0), num(1))
		return chain(&r), nil
	case "lookup_adcode":
		r := geo.LookupAdcode(str(0))
		if r == nil {
			return nil, nil
		}
		return chain(r), nil
	case "search":
		var params map[string]any
		_ = json.Unmarshal(req.Args[1], &params)
		opts := geotoolcn.SearchOptions{}
		if v, ok := params["level"].(string); ok {
			opts.Level = v
		}
		if v, ok := params["province"].(string); ok {
			opts.Province = v
		}
		if v, ok := params["city"].(string); ok {
			opts.City = v
		}
		if v, ok := params["fuzzy"].(bool); ok && !v {
			opts.NoFuzzy = true
		}
		codes := []string{}
		for _, r := range geo.Search(str(0), opts) {
			codes = append(codes, r.Code)
		}
		return codes, nil
	case "is_in_china":
		return geo.IsInChina(num(0), num(1)), nil
	case "is_in_region":
		return geo.IsInRegion(num(0), num(1), str(2))
	case "distance":
		return geotoolcn.Distance(num(0), num(1), num(2), num(3)), nil
	case "tree_sha256":
		tree, err := geotoolcn.GetAdministrativeTree()
		if err != nil {
			return nil, err
		}
		// Round-trip through generic JSON so canonical() sees plain maps, and
		// so omitempty drops "children" on leaves exactly as Python does.
		encoded, err := json.Marshal(tree)
		if err != nil {
			return nil, err
		}
		var generic any
		if err := json.Unmarshal(encoded, &generic); err != nil {
			return nil, err
		}
		sum := sha256.Sum256([]byte(canonical(generic)))
		return hex.EncodeToString(sum[:]), nil
	default:
		fn, ok := conversions[req.Op]
		if !ok {
			return nil, fmt.Errorf("unknown op: %s", req.Op)
		}
		a, b := fn(num(0), num(1))
		return []float64{a, b}, nil
	}
}

func main() {
	geo, err := geotoolcn.New()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()

	for in.Scan() {
		line := strings.TrimSpace(in.Text())
		if line == "" {
			continue
		}
		var req request
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			_ = json.NewEncoder(out).Encode(response{Error: err.Error()})
			out.Flush()
			continue
		}
		result, err := handle(geo, req)
		var resp response
		if err != nil {
			resp = response{Error: err.Error()}
		} else {
			resp = response{OK: result}
		}
		encoder := json.NewEncoder(out)
		encoder.SetEscapeHTML(false)
		_ = encoder.Encode(resp)
		out.Flush()
	}
}
