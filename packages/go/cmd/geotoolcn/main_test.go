package main

// Black-box tests: the binary is built once and every subcommand is run the
// way a user runs it. The library underneath is held to the 38k-case
// conformance suite already, so what these establish is narrower and cannot
// be established any other way — that argument parsing and JSON output do not
// alter what the library returned. Each expected value is therefore computed
// by calling the library directly, never written down.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"
)

var (
	binary string
	geo    *geotoolcn.GeoTool
)

func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "geotoolcn-cli-")
	if err != nil {
		panic(err)
	}
	binary = filepath.Join(dir, "geotoolcn")
	build := exec.Command("go", "build", "-o", binary, ".")
	build.Env = append(os.Environ(), "CGO_ENABLED=0")
	if out, err := build.CombinedOutput(); err != nil {
		panic(fmt.Sprintf("build failed: %v\n%s", err, out))
	}
	geo, err = geotoolcn.New()
	if err != nil {
		panic(err)
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// run executes the binary and returns stdout, stderr and the exit code.
func run(t *testing.T, args ...string) (string, string, int) {
	t.Helper()
	cmd := exec.Command(binary, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	code := 0
	if exit, ok := err.(*exec.ExitError); ok {
		code = exit.ExitCode()
	} else if err != nil {
		t.Fatalf("%v: %v", args, err)
	}
	return stdout.String(), stderr.String(), code
}

// mustJSON runs a subcommand that must succeed and decodes its stdout.
func mustJSON(t *testing.T, into any, args ...string) {
	t.Helper()
	stdout, stderr, code := run(t, args...)
	if code != 0 {
		t.Fatalf("%v exited %d: %s", args, code, stderr)
	}
	if err := json.Unmarshal([]byte(stdout), into); err != nil {
		t.Fatalf("%v: stdout is not JSON: %v\n%s", args, err, stdout)
	}
}

// mustFail runs a subcommand that must exit non-zero with a JSON error on
// stderr and nothing on stdout — stdout is for piping, and a half-written
// result followed by an error would silently corrupt `| jq`.
func mustFail(t *testing.T, wantCode int, args ...string) string {
	t.Helper()
	stdout, stderr, code := run(t, args...)
	if code != wantCode {
		t.Fatalf("%v: exit %d, want %d\nstdout: %s\nstderr: %s", args, code, wantCode, stdout, stderr)
	}
	if stdout != "" {
		t.Errorf("%v: failed but wrote to stdout: %q", args, stdout)
	}
	return stderr
}

// roundTrip is what a library value looks like after the CLI has printed it
// and a user has parsed it: the only fair comparison with CLI output.
func roundTrip(t *testing.T, v any) any {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out any
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestReverseMatchesLibrary(t *testing.T) {
	for _, p := range [][2]float64{
		{39.9042, 116.4074}, // Beijing
		{30.7267, 122.4553}, // 嵊泗, an island whose province must resolve
		{0, 0},              // outside China: all three null
	} {
		var got any
		mustJSON(t, &got, "reverse", fmt.Sprint(p[0]), fmt.Sprint(p[1]))
		want := roundTrip(t, geo.Reverse(p[0], p[1]))
		if !reflect.DeepEqual(got, want) {
			t.Errorf("reverse %v:\n got %v\nwant %v", p, got, want)
		}
	}
}

func TestReverseRejectsBadInput(t *testing.T) {
	mustFail(t, 1, "reverse")
	mustFail(t, 1, "reverse", "39.9")
	stderr := mustFail(t, 1, "reverse", "north", "116.4")
	var msg map[string]string
	if err := json.Unmarshal([]byte(stderr), &msg); err != nil || msg["error"] == "" {
		t.Errorf("stderr should be a JSON error object, got %q", stderr)
	}
}

func TestLookupMatchesLibrary(t *testing.T) {
	// 419001 is province-governed: its city is itself, the case adcode[:4]+"00"
	// gets wrong. If the CLI ever derived the chain instead of asking the
	// library, this is where it would show.
	for _, code := range []string{"110101", "110000", "419001", "441900"} {
		var got any
		mustJSON(t, &got, "lookup", code)
		want := roundTrip(t, geo.LookupAdcode(code))
		if !reflect.DeepEqual(got, want) {
			t.Errorf("lookup %s:\n got %v\nwant %v", code, got, want)
		}
	}
}

func TestLookupUnknownIsAnError(t *testing.T) {
	mustFail(t, 1, "lookup")
	mustFail(t, 1, "lookup", "999999")
}

func TestSearchMatchesLibrary(t *testing.T) {
	cases := []struct {
		args []string
		opts geotoolcn.SearchOptions
	}{
		{[]string{"朝阳区"}, geotoolcn.SearchOptions{}},
		{[]string{"朝阳区", "--level", "district"}, geotoolcn.SearchOptions{Level: "district"}},
		{[]string{"朝阳区", "--province", "北京市"}, geotoolcn.SearchOptions{Province: "北京市"}},
		{[]string{"朝阳区", "--province", "110000"}, geotoolcn.SearchOptions{Province: "110000"}},
		{[]string{"朝阳区", "--city", "长春市"}, geotoolcn.SearchOptions{City: "长春市"}},
		{[]string{"深圳"}, geotoolcn.SearchOptions{}},
		{[]string{"深圳", "--exact"}, geotoolcn.SearchOptions{NoFuzzy: true}},
		{[]string{"嵊泗县", "--province", "浙江省"}, geotoolcn.SearchOptions{Province: "浙江省"}},
		{[]string{"不存在的地方"}, geotoolcn.SearchOptions{}},
		{[]string{"[", "--level", "district"}, geotoolcn.SearchOptions{Level: "district"}}, // literal, not regex
	}
	for _, c := range cases {
		var got any
		mustJSON(t, &got, append([]string{"search"}, c.args...)...)
		want := roundTrip(t, geo.Search(c.args[0], c.opts))
		if !reflect.DeepEqual(got, want) {
			t.Errorf("search %v:\n got %v\nwant %v", c.args, got, want)
		}
	}
}

func TestSearchEmptyResultIsAnArrayNotNull(t *testing.T) {
	// A Go nil slice marshals to `null`. To a caller doing `| jq length`
	// that is a type error, not zero.
	stdout, _, _ := run(t, "search", "不存在的地方")
	if strings.TrimSpace(stdout) != "[]" {
		t.Errorf("empty search should print [], got %q", stdout)
	}
}

func TestSearchRequiresQuery(t *testing.T) {
	mustFail(t, 1, "search")
}

func TestTreeMatchesLibrary(t *testing.T) {
	var got any
	mustJSON(t, &got, "tree")
	tree, err := geotoolcn.GetAdministrativeTree()
	if err != nil {
		t.Fatal(err)
	}
	want := roundTrip(t, tree)
	if !reflect.DeepEqual(got, want) {
		t.Error("tree output differs from the library's")
	}
	if n := len(got.([]any)); n != 34 {
		t.Errorf("tree has %d provinces, want 34", n)
	}
}

func TestConvertMatchesLibraryForEveryPair(t *testing.T) {
	lng, lat := 116.4074, 39.9042
	for key, fn := range converters {
		from, to, _ := strings.Cut(key, ">")
		var got map[string]float64
		mustJSON(t, &got, "convert", from, to, fmt.Sprint(lng), fmt.Sprint(lat))
		wantLng, wantLat := fn(lng, lat)
		if got["lng"] != wantLng || got["lat"] != wantLat {
			t.Errorf("convert %s: got %v, want lng=%v lat=%v", key, got, wantLng, wantLat)
		}
	}
}

func TestConvertIsCaseInsensitiveAboutSystems(t *testing.T) {
	var lower, upper map[string]float64
	mustJSON(t, &lower, "convert", "wgs84", "gcj02", "116.4074", "39.9042")
	mustJSON(t, &upper, "convert", "WGS84", "GCJ02", "116.4074", "39.9042")
	if !reflect.DeepEqual(lower, upper) {
		t.Errorf("case should not matter: %v vs %v", lower, upper)
	}
}

func TestConvertRejectsBadInput(t *testing.T) {
	mustFail(t, 1, "convert")
	mustFail(t, 1, "convert", "wgs84", "gcj02", "116.4")
	mustFail(t, 1, "convert", "wgs84", "mars", "116.4", "39.9")
	mustFail(t, 1, "convert", "wgs84", "gcj02", "east", "39.9")
}

func TestVersionAndHelp(t *testing.T) {
	var v map[string]string
	mustJSON(t, &v, "version")
	if v["version"] != version {
		t.Errorf("version: got %q, want %q", v["version"], version)
	}
	for _, alias := range []string{"--version", "-v"} {
		var alt map[string]string
		mustJSON(t, &alt, alias)
		if alt["version"] != version {
			t.Errorf("%s: got %q", alias, alt["version"])
		}
	}
	stdout, _, code := run(t, "help")
	if code != 0 || !strings.Contains(stdout, "geotoolcn reverse") {
		t.Errorf("help: exit %d, output %q", code, stdout)
	}
}

func TestUsageErrorsExitTwo(t *testing.T) {
	// 2 for "you called it wrong", 1 for "it ran and failed": the convention
	// scripts rely on to tell the two apart.
	_, stderr, code := run(t)
	if code != 2 || !strings.Contains(stderr, "用法") {
		t.Errorf("no args: exit %d, stderr %q", code, stderr)
	}
	_, stderr, code = run(t, "frobnicate")
	if code != 2 || !strings.Contains(stderr, "frobnicate") {
		t.Errorf("unknown subcommand: exit %d, stderr %q", code, stderr)
	}
}

// ---------------------------------------------------------------- serve

func freePort(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := l.Addr().String()
	l.Close()
	return addr
}

func startServer(t *testing.T) string {
	t.Helper()
	addr := freePort(t)
	cmd := exec.Command(binary, "serve", "--addr", addr)
	cmd.Stderr = io.Discard
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })

	base := "http://" + addr
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if resp, err := http.Get(base + "/healthz"); err == nil {
			resp.Body.Close()
			return base
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("server did not come up")
	return ""
}

func get(t *testing.T, url string) (int, string, any) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var decoded any
	if err := json.Unmarshal(body, &decoded); err != nil {
		t.Fatalf("GET %s: body is not JSON: %v\n%s", url, err, body)
	}
	return resp.StatusCode, resp.Header.Get("Content-Type"), decoded
}

func TestServeEveryRoute(t *testing.T) {
	base := startServer(t)

	status, ctype, body := get(t, base+"/healthz")
	if status != 200 || body.(map[string]any)["status"] != "ok" {
		t.Errorf("/healthz: %d %v", status, body)
	}
	if !strings.HasPrefix(ctype, "application/json") {
		t.Errorf("Content-Type: %q", ctype)
	}

	status, _, body = get(t, base+"/reverse?lat=39.9042&lng=116.4074")
	if want := roundTrip(t, geo.Reverse(39.9042, 116.4074)); status != 200 || !reflect.DeepEqual(body, want) {
		t.Errorf("/reverse: %d\n got %v\nwant %v", status, body, want)
	}

	status, _, body = get(t, base+"/lookup?adcode=110101")
	if want := roundTrip(t, geo.LookupAdcode("110101")); status != 200 || !reflect.DeepEqual(body, want) {
		t.Errorf("/lookup: %d\n got %v\nwant %v", status, body, want)
	}

	status, _, body = get(t, base+"/search?q=朝阳区&province=北京市")
	if want := roundTrip(t, geo.Search("朝阳区", geotoolcn.SearchOptions{Province: "北京市"})); status != 200 || !reflect.DeepEqual(body, want) {
		t.Errorf("/search: %d\n got %v\nwant %v", status, body, want)
	}
	status, _, body = get(t, base+"/search?q=深圳&exact=1")
	if want := roundTrip(t, geo.Search("深圳", geotoolcn.SearchOptions{NoFuzzy: true})); status != 200 || !reflect.DeepEqual(body, want) {
		t.Errorf("/search exact: %d\n got %v\nwant %v", status, body, want)
	}

	for _, level := range []string{"province", "city", "district"} {
		status, _, body = get(t, base+"/regions?level="+level)
		regions, _ := geo.ListRegions(level)
		if want := roundTrip(t, regions); status != 200 || !reflect.DeepEqual(body, want) {
			t.Errorf("/regions?level=%s: %d, %d entries", level, status, len(body.([]any)))
		}
	}

	status, _, body = get(t, base+"/tree")
	tree, _ := geotoolcn.GetAdministrativeTree()
	if want := roundTrip(t, tree); status != 200 || !reflect.DeepEqual(body, want) {
		t.Errorf("/tree: %d", status)
	}
}

func TestServeErrorStatuses(t *testing.T) {
	base := startServer(t)
	for _, c := range []struct {
		path string
		want int
	}{
		{"/reverse", 400},
		{"/reverse?lat=39.9", 400},
		{"/reverse?lat=north&lng=116.4", 400},
		{"/lookup?adcode=999999", 404},
		{"/lookup", 404},
		{"/search", 400},
		{"/regions?level=country", 400},
		{"/regions", 400},
	} {
		status, _, body := get(t, base+c.path)
		if status != c.want {
			t.Errorf("GET %s: %d, want %d", c.path, status, c.want)
		}
		if m, ok := body.(map[string]any); !ok || m["error"] == "" {
			t.Errorf("GET %s: error body should carry an error field, got %v", c.path, body)
		}
	}
}
