// Package geotoolcn provides offline geocoding for Chinese administrative
// regions: coordinates to province/city/district, and lookups by name or
// adcode. No network, no API key, no cgo.
//
// The dataset is embedded, so the zero-configuration path is:
//
//	geo, err := geotoolcn.New()
//	result := geo.Reverse(39.9042, 116.4074)
//	result.District.Name // 东城区
//
// The behaviour is specified in SPEC.md and checked against the same ~35k
// conformance cases as the Python and Node implementations.
package geotoolcn

import (
	_ "embed"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
)

//go:embed data/china.full.gtc
var embeddedDataset []byte

// Region is a single administrative region.
type Region struct {
	Name string `json:"name"`
	// Code is the 6-digit adcode. A string, because leading zeros matter.
	Code      string  `json:"code"`
	Level     string  `json:"level"`
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
}

// ReverseResult is the province/city/district chain for a point or adcode.
// Any field may be nil.
type ReverseResult struct {
	Province *Region `json:"province"`
	City     *Region `json:"city"`
	District *Region `json:"district"`
}

// SearchOptions narrows a search. The zero value searches every level with
// fuzzy matching on.
type SearchOptions struct {
	// Level restricts to "province", "city" or "district". Empty searches all.
	Level string
	// Province filters by province, given as a name or an adcode.
	Province string
	// City filters by city, given as a name or an adcode.
	City string
	// NoFuzzy disables substring matching when no exact match is found.
	// Negated so that the zero value keeps fuzzy matching on, matching the
	// other implementations' fuzzy=true default.
	NoFuzzy bool
}

var adcodePattern = regexp.MustCompile(`^\d{6}$`)
var digitsPattern = regexp.MustCompile(`^\d+$`)

// GeoTool answers geocoding queries. Safe for concurrent use from any number
// of goroutines once New or Open returns: geometry is decoded lazily, and each
// region's decode is guarded so that concurrent first requests for the same
// polygon block on one decode rather than racing on it.
//
// Reverse, ReverseBatch, IsInChina and IsInRegion need geometry and panic
// with ErrNoGeometry on a dataset that carries none (the "mini" tier).
type GeoTool struct {
	data *gtcData
}

// New opens the embedded dataset.
func New() (*GeoTool, error) {
	d, err := newGTCData(embeddedDataset)
	if err != nil {
		return nil, err
	}
	return &GeoTool{data: d}, nil
}

// Open reads a .gtc file from disk, for a custom or trimmed dataset.
func Open(path string) (*GeoTool, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	d, err := newGTCData(raw)
	if err != nil {
		return nil, err
	}
	return &GeoTool{data: d}, nil
}

// PreloadGeometry decodes every region's polygons up front.
//
// Not needed for correctness. A lookup decodes only the polygons it touches,
// which is what keeps cold start at tens of milliseconds; but a long-running
// server may prefer to pay the ~1M-vertex parse once at start-up rather than
// as a stall on the first request that reaches each region.
func (g *GeoTool) PreloadGeometry() {
	g.data.decodeAll()
}

func (g *GeoTool) region(index int) *Region {
	d := g.data
	return &Region{
		Name:      d.names[index],
		Code:      d.adcodes[index],
		Level:     Levels[d.levels[index]],
		Latitude:  d.lats[index],
		Longitude: d.lngs[index],
	}
}

func (g *GeoTool) regionByCode(code, level string) *Region {
	i := g.data.indexOf(code, level)
	if i < 0 {
		return nil
	}
	return g.region(i)
}

// provinceAsCity clones a province as its own city, which is how
// municipalities and SARs report.
func provinceAsCity(p *Region) *Region {
	if p == nil {
		return nil
	}
	clone := *p
	clone.Level = "city"
	return &clone
}

// chainFromDistrict derives the upper levels from the district's adcode
// (SPEC §2.1).
//
// Testing each layer independently produces contradictions, because the source
// layers overlap and disagree with each other.
func (g *GeoTool) chainFromDistrict(index int) ReverseResult {
	district := g.region(index)
	provinceCode := district.Code[:2] + "0000"
	province := g.regionByCode(provinceCode, "province")

	var city *Region
	parent := g.data.parents[index]
	switch {
	case parent == provinceCode:
		city = provinceAsCity(province)
	case parent != "":
		city = g.regionByCode(parent, "city")
	}
	return ReverseResult{Province: province, City: city, District: district}
}

// Reverse looks up the administrative region for a WGS-84 coordinate.
func (g *GeoTool) Reverse(lat, lng float64) ReverseResult {
	if i := g.data.locate(lat, lng); i >= 0 {
		return g.chainFromDistrict(i)
	}
	// No district covers the point — Taiwan is published at province level
	// only, and coastal gaps leave slivers between districts. The city stays
	// nil because the .gtc carries no city geometry.
	pi := g.data.locateProvince(lat, lng)
	if pi < 0 {
		return ReverseResult{}
	}
	province := g.region(pi)
	var city *Region
	if mergedPrefixes[province.Code[:2]] {
		city = provinceAsCity(province)
	}
	return ReverseResult{Province: province, City: city}
}

// ReverseBatch reverse-geocodes many coordinates, given as [lat, lng] pairs.
func (g *GeoTool) ReverseBatch(coords [][2]float64) []ReverseResult {
	out := make([]ReverseResult, len(coords))
	for i, c := range coords {
		out[i] = g.Reverse(c[0], c[1])
	}
	return out
}

// Search finds regions by name or adcode.
//
// An empty or blank query returns no results: an empty substring is contained
// in every name, and 3,271 results is never what a blank search box meant.
//
// Panics on an opts.Level that is not one of Levels. The signature carries no
// error return, and a level string the program did not get from Levels is a
// programming error rather than bad input — the CLI and HTTP server validate
// user input before calling this.
func (g *GeoTool) Search(query string, opts SearchOptions) []*Region {
	if opts.Level != "" {
		if _, ok := g.data.levelRanges[opts.Level]; !ok {
			panic(fmt.Sprintf("geotoolcn: invalid level %q, must be one of %v", opts.Level, Levels))
		}
	}
	if strings.TrimSpace(query) == "" {
		return []*Region{}
	}
	d := g.data
	levels := Levels[:]
	if opts.Level != "" {
		levels = []string{opts.Level}
	}

	var matches []int
	for _, levelName := range levels {
		r := d.levelRanges[levelName]
		if digitsPattern.MatchString(query) {
			for i := r[0]; i < r[1]; i++ {
				if d.adcodes[i] == query {
					matches = append(matches, i)
				}
			}
			continue
		}
		var exact []int
		for _, i := range d.byName[query] {
			if i >= r[0] && i < r[1] {
				exact = append(exact, i)
			}
		}
		if len(exact) > 0 {
			matches = append(matches, exact...)
		} else if !opts.NoFuzzy {
			// Literal substring, never a regex: dialects differ across
			// languages, so a regex could not mean the same thing everywhere.
			for i := r[0]; i < r[1]; i++ {
				if strings.Contains(d.names[i], query) {
					matches = append(matches, i)
				}
			}
		}
	}

	regions := make([]*Region, 0, len(matches))
	for _, i := range matches {
		regions = append(regions, g.region(i))
	}
	if opts.Province != "" {
		regions = g.filterByParent(regions, "province", opts.Province)
	}
	if opts.City != "" {
		regions = g.filterByParent(regions, "city", opts.City)
	}

	levelRank := func(name string) int {
		for i, l := range Levels {
			if l == name {
				return i
			}
		}
		return len(Levels)
	}
	sort.SliceStable(regions, func(a, b int) bool {
		ra, rb := levelRank(regions[a].Level), levelRank(regions[b].Level)
		if ra != rb {
			return ra < rb
		}
		return regions[a].Code < regions[b].Code
	})
	return regions
}

// filterByParent keeps regions administratively under parentQuery (SPEC §2.4).
//
// By adcode relationship, never by geometry: a region's representative point
// can lie outside its own parent's polygon — islands especially — so a
// geometric test silently drops valid matches.
func (g *GeoTool) filterByParent(regions []*Region, parentLevel, parentQuery string) []*Region {
	parentCode := g.resolveParent(parentQuery, parentLevel)
	if parentCode == "" && parentLevel == "city" {
		// A municipality or SAR has no city layer of its own: the city a
		// caller means by "北京市" or "110000" is the province, which is what
		// Reverse and the administrative tree hand back as the city
		// (SPEC §2.4).
		if asProvince := g.resolveParent(parentQuery, "province"); asProvince != "" && mergedPrefixes[asProvince[:2]] {
			parentCode, parentLevel = asProvince, "province"
		}
	}
	// "No parent by that name" is an empty result, not a nil one: nil
	// marshals to JSON null, and the CLI and HTTP server promise [].
	if parentCode == "" {
		return []*Region{}
	}
	out := regions[:0:0]
	for _, region := range regions {
		if g.isUnder(region, parentLevel, parentCode) {
			out = append(out, region)
		}
	}
	return out
}

// resolveParent is the adcode of the region parentQuery names at parentLevel,
// or "" when there is none.
func (g *GeoTool) resolveParent(parentQuery, parentLevel string) string {
	d := g.data
	if digitsPattern.MatchString(parentQuery) {
		if d.indexOf(parentQuery, parentLevel) < 0 {
			return ""
		}
		return parentQuery
	}
	r := d.levelRanges[parentLevel]
	for _, i := range d.byName[parentQuery] {
		if i >= r[0] && i < r[1] {
			return d.adcodes[i]
		}
	}
	return ""
}

func (g *GeoTool) isUnder(region *Region, parentLevel, parentCode string) bool {
	if parentLevel == "province" {
		return region.Code[:2] == parentCode[:2]
	}
	if region.Level == "district" {
		i := g.data.indexOf(region.Code, "district")
		return i >= 0 && g.data.parents[i] == parentCode
	}
	return region.Code == parentCode
}

// ListRegions returns every region at a level, sorted by adcode.
func (g *GeoTool) ListRegions(level string) ([]*Region, error) {
	r, ok := g.data.levelRanges[level]
	if !ok {
		return nil, fmt.Errorf("geotoolcn: invalid level %q, must be one of %v", level, Levels)
	}
	out := make([]*Region, 0, r[1]-r[0])
	for i := r[0]; i < r[1]; i++ {
		out = append(out, g.region(i))
	}
	return out, nil
}

// GetRegion looks up one region by adcode, searching province, then city, then
// district. Returns nil when nothing matches.
func (g *GeoTool) GetRegion(code string) *Region {
	for _, level := range Levels {
		if r := g.regionByCode(code, level); r != nil {
			return r
		}
	}
	return nil
}

func adcodeLevel(adcode string) string {
	if !adcodePattern.MatchString(adcode) {
		return ""
	}
	switch {
	case strings.HasSuffix(adcode, "0000"):
		return "province"
	case strings.HasSuffix(adcode, "00"):
		return "city"
	default:
		return "district"
	}
}

// LookupAdcode returns the full chain for a 6-digit adcode, or nil when the
// adcode is malformed or names no region at the level its shape implies
// (SPEC §2.7). A non-nil result therefore means "this adcode exists".
func (g *GeoTool) LookupAdcode(adcode string) *ReverseResult {
	level := adcodeLevel(adcode)
	if level == "" {
		return nil
	}

	prefix2 := adcode[:2]
	province := g.regionByCode(prefix2+"0000", "province")
	if level == "province" {
		if province == nil {
			return nil
		}
		return &ReverseResult{Province: province}
	}

	if level == "district" {
		i := g.data.indexOf(adcode, "district")
		if i < 0 {
			return nil
		}
		chain := g.chainFromDistrict(i)
		return &chain
	}

	// City-shaped code. Municipalities and SARs have no city layer, so a code
	// like 110100 names nothing and is nil here.
	city := g.regionByCode(adcode, "city")
	if city == nil {
		return nil
	}
	// Prefecture-level cities with no subdivisions (东莞, 中山, 儋州, 嘉峪关)
	// and the province-governed county-level divisions appear at both levels
	// under one code.
	district := g.regionByCode(adcode, "district")
	return &ReverseResult{Province: province, City: city, District: district}
}

// IsInChina reports whether a coordinate falls within China's territory.
func (g *GeoTool) IsInChina(lat, lng float64) bool {
	return g.data.locate(lat, lng) >= 0 || g.data.locateProvince(lat, lng) >= 0
}

// IsInRegion reports whether a coordinate falls within a specific region —
// defined as "the matching level of Reverse is this adcode" (SPEC §2.9), so
// the two can never disagree. It errors on a malformed or unknown adcode
// rather than reporting false.
func (g *GeoTool) IsInRegion(lat, lng float64, adcode string) (bool, error) {
	level := adcodeLevel(adcode)
	if level == "" {
		return false, fmt.Errorf("geotoolcn: invalid adcode %q", adcode)
	}
	if g.data.indexOf(adcode, "") < 0 {
		return false, fmt.Errorf("geotoolcn: region not found for adcode %q", adcode)
	}

	i := g.data.locate(lat, lng)
	if i < 0 {
		if level != "province" {
			return false, nil
		}
		// No district covers the point — Taiwan is published at province
		// level only, and coastal gaps leave slivers — so fall back to the
		// province grid, exactly as Reverse does.
		pi := g.data.locateProvince(lat, lng)
		return pi >= 0 && g.data.adcodes[pi][:2] == adcode[:2], nil
	}

	districtCode := g.data.adcodes[i]
	switch level {
	case "province":
		return districtCode[:2] == adcode[:2], nil
	case "district":
		return districtCode == adcode, nil
	default:
		return g.data.parents[i] == adcode, nil
	}
}
