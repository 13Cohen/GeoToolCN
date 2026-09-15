# GeoToolCN

[![PyPI](https://img.shields.io/pypi/v/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![npm](https://img.shields.io/npm/v/@geotoolcn/core)](https://www.npmjs.com/package/@geotoolcn/core)
[![Go Reference](https://pkg.go.dev/badge/github.com/13Cohen/GeoToolCN/packages/go/v3.svg)](https://pkg.go.dev/github.com/13Cohen/GeoToolCN/packages/go/v3)
[![Test](https://github.com/13Cohen/GeoToolCN/actions/workflows/test.yml/badge.svg)](https://github.com/13Cohen/GeoToolCN/actions/workflows/test.yml)
[![Published packages](https://github.com/13Cohen/GeoToolCN/actions/workflows/post-release.yml/badge.svg?event=schedule)](https://github.com/13Cohen/GeoToolCN/actions/workflows/post-release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Offline geocoding for Chinese administrative divisions — every province, city and
district, with no API key and no network. Implementations in Python, Node.js and Go,
plus a CLI / HTTP server for everything else.

[中文](README.md)

## Features

- **Reverse geocoding** — coordinates → province / city / district
- **Forward geocoding** — name or adcode → coordinates
- **Administrative tree** — three-level province → city → district tree for cascader widgets
- **Coordinate systems** — WGS-84 / GCJ-02 / BD-09 conversions and great-circle distance
- **Zero dependencies** — each implementation uses only its language's standard library; 6 MB of bundled data, cold start in tens of milliseconds
- **Consistent across languages** — all three read the same data file and pass the same 38,000+ conformance cases

## Installation

```bash
pip install geotool-cn                                # Python 3.9+
npm install @geotoolcn/core                           # Node.js 18+ / TypeScript
go get github.com/13Cohen/GeoToolCN/packages/go/v3    # Go 1.21+, no cgo
```

For any other language, use the CLI or the HTTP server. The binary embeds the data and needs no runtime:

```bash
docker run --rm -p 8080:8080 ghcr.io/13cohen/geotoolcn
curl 'localhost:8080/reverse?lat=39.9042&lng=116.4074'

# or download a single static binary from Releases (linux / macOS / windows)
geotoolcn reverse 39.9042 116.4074 | jq -r .district.name
```

Every subcommand, HTTP route and exit-code convention: [docs/CLI_EN.md](docs/CLI_EN.md).

## Quick Start

### Python

```python
from GeoToolCN import GeoTool

geo = GeoTool()

# Reverse geocoding (coordinates → divisions)
result = geo.reverse(39.9, 116.4)
print(result.province.name)   # 北京市
print(result.district.name)   # 东城区
print(result.district.code)   # 110101

# Forward geocoding (name / code → coordinates)
regions = geo.search("深圳市")
print(regions[0].latitude, regions[0].longitude)

# Batch
results = geo.reverse_batch([(39.9, 116.4), (31.2, 121.5)])

# Every province
provinces = geo.list_regions("province")

# By adcode
region = geo.get_region("110000")
```

Module-level shortcuts share one lazily created instance:

```python
from GeoToolCN import reverse, search, get_administrative_tree

result = reverse(39.9, 116.4)
regions = search("朝阳区", province="北京市")   # disambiguate: Beijing and Changchun both have one
regions = search("朝阳区", city="110000")      # a municipality works as the city too, matching reverse().city
tree = get_administrative_tree()             # the three-level tree for cascaders
```

### Node.js / TypeScript

```js
import { reverse, search, getAdministrativeTree } from "@geotoolcn/core";

const r = reverse(39.9042, 116.4074);
r.district.name;                          // 东城区
search("朝阳区", { province: "北京市" });  // disambiguate
getAdministrativeTree();                  // [{ value, label, children }, ...]
```

Ships TypeScript declarations. ESM, zero dependencies. See [packages/node](packages/node/README.md).

### Go

```go
import geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"

geo, _ := geotoolcn.New()
r := geo.Reverse(39.9042, 116.4074)
fmt.Println(r.Province.Name, r.District.Name)   // 北京市 东城区
```

Data is embedded with `go:embed`; cross-compiles with `CGO_ENABLED=0`. See [packages/go](packages/go/README.md).

## API Reference

The three implementations expose the same API one-to-one (camelCase in Node, exported
methods in Go); the semantics are fixed by [SPEC.md](SPEC.md). Python shown below.

### `GeoTool(data_dir=None)`

Create an instance. Reads the bundled `china.full.gtc` by default. Pass a directory
containing `china.full.gtc`, or the path to a `.gtc` file, to use your own build — see
[Updating Data](#updating-data).

### `geo.reverse(lat, lng) → ReverseResult`

Reverse-geocode one WGS-84 coordinate. Province and city are derived from the district's
adcode so the three levels are always mutually consistent. All three are `None` outside China.

### `geo.reverse_batch(coords) → list[ReverseResult]`

Reverse-geocode many `(lat, lng)` pairs; output order matches input.

### `geo.search(query, *, level=None, province=None, city=None, fuzzy=True, regex=False) → list[Region]`

Search by name or adcode. Narrow with `level` (`"province"`, `"city"` or `"district"`).
Disambiguate same-named divisions with `province` or `city` (name or adcode). Fuzzy
(substring) matching is on by default.

`regex=True` treats the query as a regular expression — the default in 2.0.x and earlier:

```python
geo.search("东.区")               # 0 results: matched literally
geo.search("东.区", regex=True)   # 18 results: "." is a wildcard
```

```python
# "朝阳区" exists in both Beijing and Changchun
geo.search("朝阳区")                     # both
geo.search("朝阳区", province="北京市")    # Beijing only
geo.search("朝阳区", city="长春市")        # Changchun only
```

### `geo.list_regions(level) → list[Region]`

Every division at a level, ascending by adcode.

### `geo.get_region(code) → Region | None`

One division by adcode; province, then city, then district, first hit wins.

### `geo.lookup_adcode(adcode) → ReverseResult | None`

The full province / city / district chain for an adcode, or `None` when the
level the adcode names does not exist (since 3.1; `440399` used to return a
partial result holding only the province) — so `is not None` means "this adcode
exists".

### `geo.is_in_china(lat, lng) → bool` / `geo.is_in_region(lat, lng, adcode) → bool`

Containment tests. `is_in_region` is equivalent to comparing the matching level
of `reverse()` with `adcode`, so the two always agree — it is **not** a
point-in-polygon test against that region's polygon: district polygons overlap
in 2,801 pairs in the source data, a point belongs to one district, and
`reverse()` has already made that choice. A malformed or unknown `adcode`
raises `ValueError`.

### `get_administrative_tree() → list[dict]`

The province → city → district tree. Each node is
`{"value": "adcode", "label": "name", "children": [...]}`. Covers 34 province-level
divisions (including Taiwan, Hong Kong and Macao) and 2874 districts. Municipalities and
SARs use the province code for their city node. Cached after the first call.

### Coordinate conversions

`wgs84_to_gcj02`, `gcj02_to_wgs84`, `gcj02_to_bd09`, `bd09_to_gcj02`, `wgs84_to_bd09`,
`bd09_to_wgs84`, and `distance(lat1, lng1, lat2, lng2)` (great-circle, kilometres).

> ⚠️ The conversion functions take **`(lng, lat)`** — longitude first, as in GIS convention —
> while `reverse`, `distance` and every other call take latitude first. Swapping them does
> not raise: the swapped coordinate falls outside China and is returned unchanged.

### Data classes

```python
from dataclasses import dataclass

@dataclass
class Region:
    name: str        # "北京市"
    code: str        # "110000" (6-digit adcode)
    level: str       # "province" | "city" | "district"
    latitude: float  # representative point
    longitude: float

@dataclass
class ReverseResult:
    province: Region | None
    city: Region | None
    district: Region | None
```

## Performance

| Operation | v2 (geopandas) | v3 (bundled .gtc) |
|-----------|----------------|-------------------|
| Third-party dependencies | ~135 MB | **none** |
| Installed size | ~163 MB | **6.15 MB** |
| Cold start (incl. import) | ~1450 ms | **~37 ms** |
| Data load | ~1200 ms | **~9 ms** |
| One reverse lookup | ~250 μs | **~5 μs** |
| Batch of 1000 | ~110 ms | **~5 ms** |
| Resident memory | ~170 MB | **~30 MB** |

v3 precomputes the spatial index into the bundled binary: about 77% of lookups hit a table
and touch no geometry at all, and the rest average two ray-casting tests. That is why there
is no R-tree, no GEOS and no geometry library — and why a port is roughly 600 lines of
standard-library code.

## Testing and consistency

- **Conformance suite** — 38,000+ language-neutral cases under `conformance/`, covering every
  public function in SPEC §2. Every implementation must pass 100%, including the versions
  published to PyPI, npm and the Go proxy
- **Structural invariants** — `tests/test_invariants.py` asserts properties over all 3271
  divisions with no golden values
- **Differential test** — `conformance/differential.py` checks 200,000 random points against
  the geopandas reference implementation
- **Post-release verification** — after every publish, each package is installed from its
  registry and the suite is run against *that*; repeated daily

How we know the tests test something: faults are injected deliberately and the suite must
catch them. The numbers are in [PORTING_EN.md](PORTING_EN.md).

## Updating Data

Boundaries and the administrative tree come from a **single source** (DataV.GeoAtlas):

```bash
python scripts/fetch_datav_geojson.py    # download GeoJSON, GCJ-02 → WGS-84, diff report
python pipeline/build_gtc.py             # build china.full.gtc from it (needs geopandas)
python scripts/validate_gtc.py --round-trip
python conformance/generate.py           # regenerate the suite; review the diff, commit
bash packages/go/scripts/sync-data.sh    # the Go module's copy is committed; CI compares the two
```

`fetch_datav_geojson.py` downloads province / city / district boundaries recursively,
converts the coordinate system, updates `DATA_VERSION.json` and writes
`DATA_UPDATE_REPORT.md` with the differences from the previous data (added / removed /
renamed, keyed by adcode). If any region fails to download it **writes nothing** and exits
non-zero (`--allow-partial` overrides); files are staged in a temporary directory and moved
into place together, so an interrupted run cannot leave a mixed-vintage set. Only the
`.gtc` is needed at runtime; the GeoJSON is build input and is not shipped.

To use your own build:

```python
geo = GeoTool(data_dir="/path/to/china.full.gtc")
```

## Data Source

| Field | Value |
|-------|-------|
| Source | [DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas) (Alibaba Cloud DataV) |
| Coverage | 34 provinces / 363 cities / 2874 districts |
| CRS | WGS-84 (converted from GCJ-02) |
| Codes | 6-digit adcode |
| Last updated | March 2026 (`content_sha256` in `DATA_VERSION.json` is the dataset's identity; the fetch date is for humans) |

**License and disclaimer.** MIT covers the code in this repository only. The boundary
data shipped with every package comes from DataV.GeoAtlas; this project has **neither a
license from the provider nor verified its redistribution terms** — see [NOTICE](NOTICE).
Before redistributing the data, using it commercially, or presenting it as an authoritative
statement of administrative divisions, consult the provider's terms and the surveying and
mapping laws that apply to you. The boundaries are a geocoding convenience, not a legal
statement of divisions.

**Known coverage gaps** (limitations of the source, not defects of this project):

- **Taiwan** has a province-level boundary only: `reverse()` returns the province, no district.
- **三沙市** (460300): the 西沙区 (460301) polygons do not include 永兴岛, the seat of the city
  itself — `reverse(16.834, 112.338)` is empty and `is_in_china()` is `False`. About 0.3% of
  random points in the South China Sea resolve.
- The **nine-dash line** has been removed from the data (see `DATA_UPDATE_REPORT.md`); the
  South China Sea is not inside China for this library.
- **Conversion residual**: GCJ-02 → WGS-84 is a single-step inverse; every vertex carries a
  systematic ~0.6 m (median) to ~5 m (edges) offset on top of the source's own accuracy. An
  attribution within 1 m of a boundary is noise — do not base decisions on it.
- District polygons **overlap** in 2,801 pairs (mostly the 兵团 cities inside 新疆 counties
  and along the 青海/西藏 border); a point in an overlap band belongs to one district, by
  the rule in SPEC §3.4.

## Porting to another language

About 600 lines plus an adapter. The contract is [SPEC_EN.md](SPEC_EN.md); the steps and
acceptance checklist are in [PORTING_EN.md](PORTING_EN.md).

## Contributing

The workflow for fixing a bug, changing a behaviour, updating the data or adding a test:
[CONTRIBUTING_EN.md](CONTRIBUTING_EN.md).

## License

MIT
