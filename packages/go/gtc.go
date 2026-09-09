package geotoolcn

// Reader for the .gtc binary. Standard library only, no cgo.
//
// Format: SPEC.md §4. Behaviour: SPEC.md §2 and §3.
//
// A lookup is a binary search in a run-length table; only when that misses does
// any geometry get decoded — roughly 23% of queries, against an average of two
// candidate polygons.

import (
	"encoding/binary"
	"fmt"
	"math"
	"sort"
	"unicode/utf8"
)

// Levels in the order their IDs are stored in.
var Levels = [3]string{"province", "city", "district"}

const (
	magic                 = 0x4e435447 // "GTCN" little-endian
	supportedFormatVersion = 1
	metaRecordSize        = 28
)

const (
	sectionMeta = iota + 1
	sectionNames
	sectionGeom
	sectionGeomIndex
	sectionGridSolid
	sectionGridMixedCells
	sectionGridMixedPtrs
	sectionGridMixedLists
	sectionGridProvSolid
	sectionGridProvMixedCells
	sectionGridProvMixedPtrs
	sectionGridProvMixedLists
)

// FormatError reports a file that cannot be read as a .gtc.
type FormatError struct{ Reason string }

func (e *FormatError) Error() string { return "gtc: " + e.Reason }

type ring struct{ xs, ys []float64 }

type geometry struct {
	bbox     [4]int32
	polygons [][]ring
}

type grid struct {
	runStart, runLength, runValue []uint32
	mixedCells                    []uint32
	mixedPtrs, mixedLists         []uint32
}

type gtcData struct {
	raw       []byte
	dataset   uint8
	precision uint8
	scale     float64

	originLng, originLat, gridStep float64
	gridWidth, gridHeight          int

	recordCount int
	adcodes     []string
	levels      []uint8
	parents     []string // "" when none
	names       []string
	lats, lngs  []float64

	byCode      map[string]int
	byName      map[string][]int
	levelRanges map[string][2]int

	geomBlob    []byte
	geomIndex   []uint32
	hasGeometry bool
	geomCache   []*geometry
	geomDecoded []bool

	districtGrid, provinceGrid grid
}

// u32Slice reinterprets a byte range as uint32s.
//
// Decoded rather than cast: Go gives no aligned reinterpretation without
// unsafe, and the whole point of this package is that it builds with
// CGO_ENABLED=0 and no unsafe pointer tricks. Copying the ~500k entries the
// full index carries costs about a millisecond.
func u32Slice(b []byte) []uint32 {
	out := make([]uint32, len(b)/4)
	for i := range out {
		out[i] = binary.LittleEndian.Uint32(b[i*4:])
	}
	return out
}

func newGTCData(raw []byte) (*gtcData, error) {
	if len(raw) < 32 || binary.LittleEndian.Uint32(raw) != magic {
		return nil, &FormatError{"not a .gtc file"}
	}
	formatVersion := binary.LittleEndian.Uint16(raw[4:])
	if formatVersion != supportedFormatVersion {
		return nil, &FormatError{fmt.Sprintf(
			"format version %d is not supported (this build reads version %d)",
			formatVersion, supportedFormatVersion)}
	}

	d := &gtcData{raw: raw}
	d.dataset = raw[6]
	d.precision = raw[7]
	d.scale = math.Pow(10, float64(d.precision))
	sectionCount := int(binary.LittleEndian.Uint16(raw[12:]))
	d.originLng = float64(int32(binary.LittleEndian.Uint32(raw[16:]))) / 1e6
	d.originLat = float64(int32(binary.LittleEndian.Uint32(raw[20:]))) / 1e6
	d.gridStep = float64(binary.LittleEndian.Uint32(raw[24:])) / 1e6
	d.gridWidth = int(binary.LittleEndian.Uint16(raw[28:]))
	d.gridHeight = int(binary.LittleEndian.Uint16(raw[30:]))

	sections := make(map[int][]byte, sectionCount)
	for i := 0; i < sectionCount; i++ {
		base := 32 + 24*i
		kind := int(binary.LittleEndian.Uint16(raw[base:]))
		offset := binary.LittleEndian.Uint64(raw[base+8:])
		length := binary.LittleEndian.Uint64(raw[base+16:])
		sections[kind] = raw[offset : offset+length]
	}

	d.geomBlob = sections[sectionGeom]
	d.hasGeometry = len(d.geomBlob) > 0
	d.geomIndex = u32Slice(sections[sectionGeomIndex])

	d.districtGrid = loadGrid(sections, sectionGridSolid, sectionGridMixedCells,
		sectionGridMixedPtrs, sectionGridMixedLists)
	d.provinceGrid = loadGrid(sections, sectionGridProvSolid, sectionGridProvMixedCells,
		sectionGridProvMixedPtrs, sectionGridProvMixedLists)

	d.buildIndexes(sections[sectionMeta], sections[sectionNames])
	return d, nil
}

func loadGrid(sections map[int][]byte, solid, cells, ptrs, lists int) grid {
	solidSection := sections[solid]
	runCount := int(binary.LittleEndian.Uint32(solidSection))
	flat := u32Slice(solidSection[4 : 4+12*runCount])

	g := grid{
		runStart:   make([]uint32, runCount),
		runLength:  make([]uint32, runCount),
		runValue:   make([]uint32, runCount),
		mixedPtrs:  u32Slice(sections[ptrs]),
		mixedLists: u32Slice(sections[lists]),
	}
	for i := 0; i < runCount; i++ {
		g.runStart[i] = flat[i*3]
		g.runLength[i] = flat[i*3+1]
		g.runValue[i] = flat[i*3+2]
	}
	cellsSection := sections[cells]
	mixedCount := int(binary.LittleEndian.Uint32(cellsSection))
	g.mixedCells = u32Slice(cellsSection[4 : 4+4*mixedCount])
	return g
}

func (d *gtcData) buildIndexes(meta, names []byte) {
	d.recordCount = int(binary.LittleEndian.Uint32(meta))
	n := d.recordCount

	d.adcodes = make([]string, n)
	d.levels = make([]uint8, n)
	d.parents = make([]string, n)
	d.names = make([]string, n)
	d.lats = make([]float64, n)
	d.lngs = make([]float64, n)
	d.byCode = make(map[string]int, n)
	d.byName = make(map[string][]int, n)
	d.levelRanges = make(map[string][2]int, len(Levels))
	d.geomCache = make([]*geometry, n)
	d.geomDecoded = make([]bool, n)

	offset := 4
	for i := 0; i < n; i++ {
		adcode := binary.LittleEndian.Uint32(meta[offset:])
		level := meta[offset+4]
		parent := binary.LittleEndian.Uint32(meta[offset+8:])
		nameOffset := binary.LittleEndian.Uint32(meta[offset+12:])
		nameLength := binary.LittleEndian.Uint16(meta[offset+16:])
		lat := int32(binary.LittleEndian.Uint32(meta[offset+20:]))
		lng := int32(binary.LittleEndian.Uint32(meta[offset+24:]))
		offset += metaRecordSize

		code := fmt.Sprintf("%06d", adcode)
		d.adcodes[i] = code
		d.levels[i] = level
		if parent != 0 {
			d.parents[i] = fmt.Sprintf("%06d", parent)
		}
		name := string(names[nameOffset : uint32(nameOffset)+uint32(nameLength)])
		d.names[i] = name
		d.lats[i] = float64(lat) / 1e6
		d.lngs[i] = float64(lng) / 1e6

		if _, seen := d.byCode[code]; !seen {
			d.byCode[code] = i
		}
		d.byName[name] = append(d.byName[name], i)
	}

	// Records are sorted by (level, adcode), so each level is contiguous.
	for levelID, levelName := range Levels {
		start, end := -1, -1
		for i := 0; i < n; i++ {
			if int(d.levels[i]) == levelID {
				if start == -1 {
					start = i
				}
				end = i + 1
			}
		}
		if start == -1 {
			d.levelRanges[levelName] = [2]int{0, 0}
		} else {
			d.levelRanges[levelName] = [2]int{start, end}
		}
	}
	_ = utf8.RuneCountInString // names are UTF-8 by construction
}

// indexOf finds a record by adcode, optionally constrained to a level.
func (d *gtcData) indexOf(code, level string) int {
	i, ok := d.byCode[code]
	if !ok {
		return -1
	}
	if level != "" && Levels[d.levels[i]] != level {
		// A code can exist at two levels (东莞市 is both city and district).
		r := d.levelRanges[level]
		for j := r[0]; j < r[1]; j++ {
			if d.adcodes[j] == code {
				return j
			}
		}
		return -1
	}
	return i
}

// geometryAt decodes one region's polygons, caching the result.
//
// Deferred because most lookups never need it: a solid grid cell answers
// outright, and eagerly parsing the ~1M vertices would cost seconds.
func (d *gtcData) geometryAt(index int) *geometry {
	if d.geomDecoded[index] {
		return d.geomCache[index]
	}
	d.geomDecoded[index] = true

	start, end := d.geomIndex[index], d.geomIndex[index+1]
	if start == end {
		return nil
	}

	buf := d.geomBlob
	pos := int(start)
	g := &geometry{}
	for i := 0; i < 4; i++ {
		g.bbox[i] = int32(binary.LittleEndian.Uint32(buf[pos+i*4:]))
	}
	pos += 16

	// Counts are plain unsigned varints; coordinates are zigzagged. Mixing the
	// two up doubles every ring count and runs the decoder off the end.
	readUvarint := func() uint64 {
		var result uint64
		var shift uint
		for {
			b := buf[pos]
			pos++
			result |= uint64(b&0x7f) << shift
			if b&0x80 == 0 {
				return result
			}
			shift += 7
		}
	}
	readSvarint := func() int64 {
		v := readUvarint()
		return int64(v>>1) ^ -int64(v&1)
	}

	polygonCount := int(readUvarint())
	g.polygons = make([][]ring, polygonCount)
	for p := 0; p < polygonCount; p++ {
		ringCount := int(readUvarint())
		rings := make([]ring, ringCount)
		for r := 0; r < ringCount; r++ {
			pointCount := int(readUvarint())
			xs := make([]float64, pointCount)
			ys := make([]float64, pointCount)
			var x, y int64
			for i := 0; i < pointCount; i++ {
				x += readSvarint()
				y += readSvarint()
				xs[i] = float64(x)
				ys[i] = float64(y)
			}
			rings[r] = ring{xs: xs, ys: ys}
		}
		g.polygons[p] = rings
	}

	d.geomCache[index] = g
	return g
}

// pointInRing is even-odd ray casting, exactly as SPEC §3.3 defines it.
func pointInRing(xs, ys []float64, x, y float64) bool {
	inside := false
	n := len(xs)
	j := n - 1
	for i := 0; i < n; i++ {
		yi, yj := ys[i], ys[j]
		if (yi > y) != (yj > y) {
			if x < xs[i]+(y-yi)*(xs[j]-xs[i])/(yj-yi) {
				inside = !inside
			}
		}
		j = i
	}
	return inside
}

func (d *gtcData) contains(index int, qx, qy float64) bool {
	g := d.geometryAt(index)
	if g == nil {
		return false
	}
	if qx < float64(g.bbox[0]) || qx > float64(g.bbox[2]) ||
		qy < float64(g.bbox[1]) || qy > float64(g.bbox[3]) {
		return false
	}
	for _, rings := range g.polygons {
		if !pointInRing(rings[0].xs, rings[0].ys, qx, qy) {
			continue
		}
		inHole := false
		for _, hole := range rings[1:] {
			if pointInRing(hole.xs, hole.ys, qx, qy) {
				inHole = true
				break
			}
		}
		if !inHole {
			return true
		}
	}
	return false
}

func (d *gtcData) locateIn(g *grid, lat, lng float64) int {
	if !d.hasGeometry {
		return -1
	}
	col := int(math.Floor((lng - d.originLng) / d.gridStep))
	row := int(math.Floor((lat - d.originLat) / d.gridStep))
	if col < 0 || col >= d.gridWidth || row < 0 || row >= d.gridHeight {
		return -1
	}
	cellID := uint32(row*d.gridWidth + col)

	// Largest run whose start is <= cellID.
	i := sort.Search(len(g.runStart), func(k int) bool {
		return g.runStart[k] > cellID
	}) - 1
	if i >= 0 && cellID < g.runStart[i]+g.runLength[i] {
		return int(g.runValue[i])
	}

	j := sort.Search(len(g.mixedCells), func(k int) bool {
		return g.mixedCells[k] >= cellID
	})
	if j >= len(g.mixedCells) || g.mixedCells[j] != cellID {
		return -1
	}

	qx := lng * d.scale
	qy := lat * d.scale
	// Candidates were written in ascending adcode order (SPEC §3.4).
	for slot := g.mixedPtrs[j]; slot < g.mixedPtrs[j+1]; slot++ {
		index := int(g.mixedLists[slot])
		if d.contains(index, qx, qy) {
			return index
		}
	}
	return -1
}

func (d *gtcData) locate(lat, lng float64) int {
	return d.locateIn(&d.districtGrid, lat, lng)
}

// locateProvince answers points that fall in no district: Taiwan is published
// at province level only, and coastal gaps leave slivers between districts.
func (d *gtcData) locateProvince(lat, lng float64) int {
	return d.locateIn(&d.provinceGrid, lat, lng)
}
