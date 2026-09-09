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

// GeoTool answers geocoding queries. Safe for concurrent reads after New
// returns, except that Reverse lazily decodes geometry; use one per goroutine
// or guard it if you need concurrency.
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
func (g *GeoTool) Search(query string, opts SearchOptions) []*Region {
	d := g.data
	levels := Levels[:]
	if opts.Level != "" {
		levels = []string{opts.Level}
	}

	var matches []int
	for _, levelName := range levels {
		r, ok := d.levelRanges[levelName]
		if !ok {
			continue
		}
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
	d := g.data
	var parentCode string
	if digitsPattern.MatchString(parentQuery) {
		if d.indexOf(parentQuery, parentLevel) < 0 {
			return nil
		}
		parentCode = parentQuery
	} else {
		r := d.levelRanges[parentLevel]
		found := -1
		for _, i := range d.byName[parentQuery] {
			if i >= r[0] && i < r[1] {
				found = i
				break
			}
		}
		if found < 0 {
			return nil
		}
		parentCode = d.adcodes[found]
	}

	out := regions[:0:0]
	for _, region := range regions {
		if g.isUnder(region, parentLevel, parentCode) {
			out = append(out, region)
		}
	}
	return out
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

// LookupAdcode returns the full chain for a 6-digit adcode, or nil.
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

	var city *Region
	switch {
	case mergedPrefixes[prefix2]:
		city = provinceAsCity(province)
	case level == "district":
		if i := g.data.indexOf(adcode, "district"); i >= 0 {
			if parent := g.data.parents[i]; parent != "" {
				city = g.regionByCode(parent, "city")
			}
		}
	default:
		city = g.regionByCode(adcode, "city")
	}

	// Prefecture-level cities with no subdivisions (东莞, 中山, 儋州, 嘉峪关)
	// appear at both levels under one code, so try either way.
	district := g.regionByCode(adcode, "district")

	if province == nil && city == nil && district == nil {
		return nil
	}
	return &ReverseResult{Province: province, City: city, District: district}
}

// IsInChina reports whether a coordinate falls within China's territory.
func (g *GeoTool) IsInChina(lat, lng float64) bool {
	return g.data.locate(lat, lng) >= 0 || g.data.locateProvince(lat, lng) >= 0
}

// IsInRegion reports whether a coordinate falls within a specific region.
// It errors on a malformed or unknown adcode rather than reporting false.
func (g *GeoTool) IsInRegion(lat, lng float64, adcode string) (bool, error) {
	level := adcodeLevel(adcode)
	if level == "" {
		return false, fmt.Errorf("geotoolcn: invalid adcode %q", adcode)
	}
	if g.data.indexOf(adcode, "") < 0 {
		return false, fmt.Errorf("geotoolcn: region not found for adcode %q", adcode)
	}

	if level == "province" {
		// Answer from the province grid: Taiwan has no districts, so routing
		// this through the district lookup reports false for the whole island.
		pi := g.data.locateProvince(lat, lng)
		return pi >= 0 && g.data.adcodes[pi][:2] == adcode[:2], nil
	}

	i := g.data.locate(lat, lng)
	if i < 0 {
		return false, nil
	}
	districtCode := g.data.adcodes[i]
	if level == "district" {
		return districtCode == adcode, nil
	}
	if mergedPrefixes[adcode[:2]] {
		return districtCode[:2] == adcode[:2], nil
	}
	return g.data.parents[i] == adcode, nil
}
