package geotoolcn

// Idiomatic smoke tests. Correctness at scale is the conformance suite's job;
// these exist so `go test` says something useful on its own.

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"math"
	"strings"
	"testing"
)

func newTool(t *testing.T) *GeoTool {
	t.Helper()
	geo, err := New()
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return geo
}

func TestReverseResolvesCityCentre(t *testing.T) {
	r := newTool(t).Reverse(39.9042, 116.4074)
	if r.Province == nil || r.Province.Name != "北京市" {
		t.Fatalf("province = %+v", r.Province)
	}
	if r.District == nil || r.District.Code != "110101" {
		t.Fatalf("district = %+v", r.District)
	}
	// Municipalities report the province as their city.
	if r.City == nil || r.City.Code != "110000" || r.City.Level != "city" {
		t.Fatalf("city = %+v", r.City)
	}
}

func TestReverseOutsideChina(t *testing.T) {
	r := newTool(t).Reverse(35.6762, 139.6503)
	if r.Province != nil || r.District != nil {
		t.Fatalf("expected empty chain, got %+v", r)
	}
}

func TestHierarchyIsSelfConsistent(t *testing.T) {
	// 加格达奇区 is administered by 黑龙江 but sits inside 内蒙古's outline.
	r := newTool(t).Reverse(50.37295, 124.16537)
	if r.Province == nil || r.District == nil {
		t.Fatal("expected a full chain")
	}
	if r.Province.Code != "230000" || r.District.Code != "232718" {
		t.Fatalf("province=%s district=%s", r.Province.Code, r.District.Code)
	}
	if r.Province.Code[:2] != r.District.Code[:2] {
		t.Fatal("province and district disagree")
	}
}

func TestIslandsResolveAProvince(t *testing.T) {
	r := newTool(t).Reverse(30.66457, 122.56396)
	if r.Province == nil || r.Province.Name != "浙江省" {
		t.Fatalf("province = %+v", r.Province)
	}
	if r.District == nil || r.District.Name != "嵊泗县" {
		t.Fatalf("district = %+v", r.District)
	}
}

func TestSearchFiltersByAdcodeNotGeometry(t *testing.T) {
	geo := newTool(t)
	if got := geo.Search("朝阳区", SearchOptions{Level: "district"}); len(got) != 2 {
		t.Fatalf("expected two 朝阳区, got %d", len(got))
	}
	got := geo.Search("朝阳区", SearchOptions{Province: "北京市"})
	if len(got) != 1 || got[0].Code != "110105" {
		t.Fatalf("got %+v", got)
	}
	// An island's representative point lies outside its own province outline,
	// so a geometric filter would drop it.
	got = geo.Search("嵊泗县", SearchOptions{Province: "浙江省"})
	if len(got) != 1 || got[0].Code != "330922" {
		t.Fatalf("got %+v", got)
	}
}

func TestSearchTreatsQueryLiterally(t *testing.T) {
	geo := newTool(t)
	if got := geo.Search("东.区", SearchOptions{Level: "district"}); len(got) != 0 {
		t.Fatalf("regex metacharacters must not match, got %d", len(got))
	}
	if got := geo.Search("[", SearchOptions{}); len(got) != 0 {
		t.Fatalf("got %d", len(got))
	}
}

func TestLookupAdcodeIrregularDivisions(t *testing.T) {
	geo := newTool(t)
	// 济源市 is its own city; adcode[:4]+"00" would give the nonexistent 419000.
	if r := geo.LookupAdcode("419001"); r == nil || r.City == nil || r.City.Name != "济源市" {
		t.Fatalf("419001 -> %+v", r)
	}
	// 东莞市 has no subdivisions and appears at both levels under one code.
	if r := geo.LookupAdcode("441900"); r == nil || r.District == nil || r.District.Name != "东莞市" {
		t.Fatalf("441900 -> %+v", r)
	}
}

func TestIsInRegionHandlesTaiwan(t *testing.T) {
	geo := newTool(t)
	// Taiwan is published at province level only.
	if ok, err := geo.IsInRegion(25.03, 121.56, "710000"); err != nil || !ok {
		t.Fatalf("ok=%v err=%v", ok, err)
	}
	if ok, _ := geo.IsInRegion(39.9042, 116.4074, "710000"); ok {
		t.Fatal("Beijing is not in Taiwan")
	}
}

func TestIsInRegionRejectsUnknownAdcode(t *testing.T) {
	geo := newTool(t)
	for _, bad := range []string{"999999", "xyz", ""} {
		if _, err := geo.IsInRegion(39.9, 116.4, bad); err == nil {
			t.Fatalf("expected an error for %q", bad)
		}
	}
}

func TestTreeHasOnePathPerDistrict(t *testing.T) {
	tree, err := GetAdministrativeTree()
	if err != nil {
		t.Fatal(err)
	}
	if len(tree) != 34 {
		t.Fatalf("expected 34 provinces, got %d", len(tree))
	}
	seen := map[string]bool{}
	total := 0
	for _, p := range tree {
		for _, c := range p.Children {
			for _, d := range c.Children {
				total++
				seen[d.Value] = true
			}
		}
	}
	if total != 2874 || len(seen) != 2874 {
		t.Fatalf("leaves=%d unique=%d — a district is reachable twice", total, len(seen))
	}
}

func TestTreeNodeMarshalsTheSameByValueAndByPointer(t *testing.T) {
	tree, err := GetAdministrativeTree()
	if err != nil {
		t.Fatal(err)
	}
	var taiwan *TreeNode
	for _, p := range tree {
		if p.Value == "710000" {
			taiwan = p
		}
	}
	if taiwan == nil || taiwan.Children == nil {
		t.Fatal("台湾省 should be a childless province, not a leaf")
	}
	byPtr, _ := json.Marshal(taiwan)
	byVal, _ := json.Marshal(*taiwan)
	embedded, _ := json.Marshal(struct{ Node TreeNode }{*taiwan})
	if string(byPtr) != string(byVal) || !strings.Contains(string(embedded), `"children":[]`) {
		t.Errorf("pointer %s\nvalue   %s\nembedded %s", byPtr, byVal, embedded)
	}
	leaf := taiwan
	for _, p := range tree {
		if p.Value == "110000" {
			leaf = p.Children[0].Children[0]
		}
	}
	if out, _ := json.Marshal(*leaf); strings.Contains(string(out), "children") {
		t.Errorf("leaf by value should omit children: %s", out)
	}
}

func TestListRegionsSortedAndValidated(t *testing.T) {
	geo := newTool(t)
	regions, err := geo.ListRegions("district")
	if err != nil {
		t.Fatal(err)
	}
	if len(regions) != 2874 {
		t.Fatalf("got %d districts", len(regions))
	}
	for i := 1; i < len(regions); i++ {
		if regions[i-1].Code >= regions[i].Code {
			t.Fatalf("not sorted at %d: %s >= %s", i, regions[i-1].Code, regions[i].Code)
		}
	}
	if _, err := geo.ListRegions("planet"); err == nil {
		t.Fatal("expected an error for an invalid level")
	}
}

func TestCoordConversionsTakeLongitudeFirst(t *testing.T) {
	gLng, gLat := WGS84ToGCJ02(116.4074, 39.9042)
	if math.Abs(gLng-116.4074) > 0.01 || math.Abs(gLat-39.9042) > 0.01 {
		t.Fatalf("offset too large: %v %v", gLng, gLat)
	}
	wLng, wLat := GCJ02ToWGS84(gLng, gLat)
	// A single-step inverse, so the round trip is lossy by a few metres.
	if d := Distance(39.9042, 116.4074, wLat, wLng) * 1000; d > 6 {
		t.Fatalf("round trip off by %.2f m", d)
	}
	if lng, lat := WGS84ToGCJ02(139.6503, 35.6762); lng != 139.6503 || lat != 35.6762 {
		t.Fatal("must pass through outside China")
	}
}

func BenchmarkReverse(b *testing.B) {
	geo, _ := New()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		geo.Reverse(39.9042, 116.4074)
	}
}

// TestConcurrentReverseMatchesSequential is the regression test for the
// geometry-cache race: before it was guarded, two goroutines decoding the same
// polygon could observe the "decoded" flag with an empty cache slot and answer
// "not inside". Run with -race to catch the data race itself; without it, this
// still catches the wrong answers.
func TestConcurrentReverseMatchesSequential(t *testing.T) {
	// Grid of points dense enough to touch mixed cells in every province.
	var pts [][2]float64
	for lat := 18.0; lat < 54; lat += 0.35 {
		for lng := 73.0; lng < 136; lng += 0.35 {
			pts = append(pts, [2]float64{lat, lng})
		}
	}
	want := newTool(t).ReverseBatch(pts)

	// A fresh instance so every polygon is decoded under contention.
	geo := newTool(t)
	const workers = 16
	got := make([][]ReverseResult, workers)
	done := make(chan int, workers)
	for w := 0; w < workers; w++ {
		go func(w int) {
			got[w] = geo.ReverseBatch(pts)
			done <- w
		}(w)
	}
	for w := 0; w < workers; w++ {
		<-done
	}
	for w := 0; w < workers; w++ {
		for i := range pts {
			if code(got[w][i].District) != code(want[i].District) {
				t.Fatalf("worker %d point %v: got %s, sequential %s",
					w, pts[i], code(got[w][i].District), code(want[i].District))
			}
		}
	}
}

func code(r *Region) string {
	if r == nil {
		return "<nil>"
	}
	return r.Code
}

func TestNonFiniteCoordinatesAreOutside(t *testing.T) {
	geo := newTool(t)
	for _, c := range [][2]float64{
		{math.NaN(), 116.4}, {39.9, math.NaN()}, {math.Inf(1), 116.4}, {39.9, math.Inf(-1)},
	} {
		if r := geo.Reverse(c[0], c[1]); r.Province != nil || r.City != nil || r.District != nil {
			t.Errorf("Reverse(%v) = %+v, want empty", c, r)
		}
		if geo.IsInChina(c[0], c[1]) {
			t.Errorf("IsInChina(%v) = true", c)
		}
	}
}

func TestTruncatedFileIsAFormatError(t *testing.T) {
	// Cut at several depths: inside the header, inside the section table,
	// and inside a section body. Each must be a FormatError, never a panic.
	for _, n := range []int{0, 8, 31, 32, 100, 4096, len(embeddedDataset) / 2} {
		func() {
			defer func() {
				if r := recover(); r != nil {
					t.Errorf("%d bytes: panic %v", n, r)
				}
			}()
			_, err := newGTCData(embeddedDataset[:n])
			var fe *FormatError
			if !errors.As(err, &fe) {
				t.Errorf("%d bytes: err = %v, want *FormatError", n, err)
			}
		}()
	}
}

func TestNoGeometryPanicsWithErrNoGeometry(t *testing.T) {
	// Build a "mini" view of the embedded file: same sections, GEOM emptied,
	// grid step zeroed — both as a real mini build writes them. The reader
	// takes len(geomBlob) == 0 as the no-geometry marker (SPEC §4.1).
	raw := append([]byte(nil), embeddedDataset...)
	binary.LittleEndian.PutUint32(raw[24:], 0)
	sectionCount := int(binary.LittleEndian.Uint16(raw[12:]))
	for i := 0; i < sectionCount; i++ {
		base := 32 + 24*i
		if int(binary.LittleEndian.Uint16(raw[base:])) == sectionGeom {
			binary.LittleEndian.PutUint64(raw[base+16:], 0)
		}
	}
	d, err := newGTCData(raw)
	if err != nil {
		t.Fatalf("newGTCData: %v", err)
	}
	geo := &GeoTool{data: d}

	if r := geo.GetRegion("110000"); r == nil || r.Name != "北京市" {
		t.Fatalf("name lookups must still work without geometry, got %+v", r)
	}
	defer func() {
		if r := recover(); r != ErrNoGeometry {
			t.Fatalf("recover() = %v, want ErrNoGeometry", r)
		}
	}()
	geo.Reverse(39.9, 116.4)
	t.Fatal("Reverse returned on a dataset with no geometry")
}

func TestSearchAcceptsMunicipalityAsCity(t *testing.T) {
	geo := newTool(t)
	for _, city := range []string{"北京市", "110000"} {
		got := geo.Search("朝阳区", SearchOptions{City: city})
		if len(got) != 1 || got[0].Code != "110105" {
			t.Errorf("City=%q: got %v", city, got)
		}
	}
	if got := geo.Search("朝阳区", SearchOptions{City: "广东省"}); len(got) != 0 {
		t.Errorf("a province that is not a municipality is not a city: %v", got)
	}
}

func TestSearchBlankAndBadLevel(t *testing.T) {
	geo := newTool(t)
	for _, q := range []string{"", "  ", "１１００００"} {
		if got := geo.Search(q, SearchOptions{}); len(got) != 0 {
			t.Errorf("Search(%q) = %d results, want 0", q, len(got))
		}
	}
	defer func() {
		if recover() == nil {
			t.Fatal("an invalid Level must panic: the signature has no error to return")
		}
	}()
	geo.Search("x", SearchOptions{Level: "county"})
}

func TestLookupAdcodeUnknownAtLevelIsNil(t *testing.T) {
	geo := newTool(t)
	for _, code := range []string{"440399", "110100", "419000"} {
		if r := geo.LookupAdcode(code); r != nil {
			t.Errorf("LookupAdcode(%q) = %+v, want nil", code, r)
		}
	}
}

func TestIsInRegionAgreesWithReverse(t *testing.T) {
	geo := newTool(t)
	for _, c := range []struct {
		lat, lng float64
		code     string
		want     bool
	}{
		{50.37295, 124.16537, "230000", true},
		{50.37295, 124.16537, "150000", false},
		{35.77829, 93.31087, "632724", true},
		{35.77829, 93.31087, "632801", false},
	} {
		got, err := geo.IsInRegion(c.lat, c.lng, c.code)
		if err != nil || got != c.want {
			t.Errorf("IsInRegion(%v, %v, %s) = %v, %v; want %v", c.lat, c.lng, c.code, got, err, c.want)
		}
	}
}

func TestTreeIsAFreshCopyPerCall(t *testing.T) {
	a, _ := GetAdministrativeTree()
	a[0].Label = "mutated"
	a[0].Children = nil
	b, _ := GetAdministrativeTree()
	if b[0].Label == "mutated" || len(b[0].Children) == 0 {
		t.Fatalf("a caller's edits leaked into the next call: %+v", b[0])
	}
}
