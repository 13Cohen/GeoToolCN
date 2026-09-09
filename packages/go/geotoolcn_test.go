package geotoolcn

// Idiomatic smoke tests. Correctness at scale is the conformance suite's job;
// these exist so `go test` says something useful on its own.

import (
	"math"
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
