<!-- translation-of: SPEC.md sha256:391634386a80c75c8657e9b6f8bbe07b7027e8f48270cb24a8299a9efa5e169a -->

# GeoToolCN Specification v1

> Format version `format_version = 1` · Status: draft · Last updated: 2026-09-09

**[SPEC.md](SPEC.md) (Chinese) is normative.** This translation exists so that
contributors who do not read Chinese can port the library; where the two
disagree, the Chinese text wins. `scripts/check_translations.py` fails CI if
`SPEC.md` changes without this file being updated, so the two cannot drift
silently.

This document is the single source of truth for every GeoToolCN implementation.
An implementation that satisfies it passes the whole `conformance/` suite;
conversely, any disagreement surfaced by conformance should be resolved by
clarifying this file, not by special-casing one language.

Suggested reading order: §1 data model → §2 API behaviour → §3 tie-breaking
rules → §4 the GTC binary format. If you only implement the `mini` tier (no
geometry), §4.6 and §3.3 can be skipped.

**Terminology**: all coordinates here are WGS-84. `adcode` means a 6-digit
administrative division code of the People's Republic of China.

---

## 1. Data model

### 1.1 Region

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Division name, e.g. `"北京市"` |
| `code` | string | 6-digit adcode, e.g. `"110000"`. **Always a string** — never an integer, which loses leading-zero semantics and invites cross-language divergence |
| `level` | enum | `"province"` \| `"city"` \| `"district"` |
| `latitude` | float | Representative point latitude |
| `longitude` | float | Representative point longitude |

The **representative point** must be computed at build time from
**original-precision** geometry and stored in META; runtimes read it directly.
Do not recompute it from quantised geometry — measured drift is up to 1.6 m at
1e-5 quantisation.

### 1.2 ReverseResult

Three nullable fields: `province`, `city`, `district`, each a `Region` or null.

### 1.3 TreeNode

```
{ "value": "<adcode>", "label": "<name>", "children": [TreeNode, ...] }
```

Whether `children` is present must follow this table **exactly**, or the
conformance tree hash will not match:

| Node | `children` |
|------|-----------|
| Province | **Always present**; `[]` when it has no sub-divisions (台湾省 is such a case) |
| City | **Always present**; `[]` when empty |
| District (leaf) | **Absent** — not `[]`, not `null` |

⚠️ This trips up ports: Go's `json:"children,omitempty"` drops empty arrays too,
so province nodes lose the key. A custom `MarshalJSON` is needed to distinguish
"nil (leaf)" from "empty but non-nil".

The tree hash is the SHA-256 of the UTF-8 bytes of a canonical JSON
serialisation of the whole tree (**keys sorted, no whitespace, non-ASCII not
escaped**). Note that Go's `encoding/json` escapes `<`, `>` and `&` by default —
use `SetEscapeHTML(false)`.

### 1.4 Hierarchy

- A province adcode is always `<first two digits> + "0000"`.
- **A district's parent city must not be derived as `adcode[:4] + "00"`.** That
  rule produces non-existent codes such as `419000` for the 30
  province-directly-governed county-level divisions (adcode blocks `4190` 济源,
  `4290` 仙桃/潜江/天门/神农架, `4690` Hainan, `6590` Xinjiang). Parentage must
  come from the `parent` field written into META at build time.
- Municipalities and SARs (adcode prefix in `{11, 12, 31, 50, 81, 82}`, hereafter
  the **MERGED prefixes**) have no separate prefecture level: their districts'
  `parent` is the province adcode.

---

## 2. API behaviour contract

Each language adapts casing to its own conventions (`reverse_batch` /
`reverseBatch` / `ReverseBatch`); the semantics must be identical.

### 2.1 `reverse(lat, lng) -> ReverseResult`

```
1. If (lat, lng) falls in a district:
     district = that district
     province = lookup(district.code[:2] + "0000")
     city:
       if district.parent == province.code  -> copy of province, level = "city"
       else                                 -> lookup(district.parent)
       if district.parent is null           -> null
2. Otherwise:
     province = point-in-polygon over the province layer (may be null)
     city     = point-in-polygon over the city layer (may be null)
     if city is null and province is not null and province has a MERGED prefix
                                            -> city = copy of province, level = "city"
     district = null
```

**The upper levels must be derived from the district's adcode; do not run three
independent point-in-polygon tests.** The source data contradicts itself in
several places: 加格达奇区 (232718) is administered by Heilongjiang but sits
inside Inner Mongolia's province polygon; several district polygons extend past
their own province outline onto offshore islands; city polygons overlap at
prefecture borders, so one point can be claimed by two cities. Independent
lookups produce self-contradictory results such as `province=None` alongside
`city=舟山市`.

> If the `full` / `lite` tier carries no city-layer geometry (see §4.1), `city`
> in step 2 is always null. This is registered divergence `DIV-101`, measured at
> 0.023% of points.

### 2.2 `reverse_batch(coords) -> ReverseResult[]`

Per point, equivalent to `reverse`. Empty input returns an empty list. Order
matches the input.

### 2.3 `search(query, level?, province?, city?, fuzzy=true, regex=false) -> Region[]`

```
1. If query is all digits -> exact adcode lookup
2. Otherwise              -> exact name match
3. If no exact match and fuzzy is true -> substring match
4. Apply the province / city filters in turn, if given
```

- **`fuzzy` is plain substring matching** (case-sensitive literal containment),
  not a regex. Regex dialects are incompatible across languages (Python `re`,
  Go RE2 and JS `RegExp` differ), and putting one in the spec would stop
  conformance from ever converging.
- `regex` is an **optional** extension, provided only by Python for 2.0.x
  compatibility; other languages need not implement it.
- `level` restricts the search; when absent, search `province` → `city` →
  `district` in that order.
- `province` / `city` filters accept **a name or an adcode**; membership is
  decided per §2.4.

**Result ordering**: by level (`province` < `city` < `district`), then by adcode
ascending within a level.

### 2.4 Parent filtering

**Decide by adcode relationship, never by geometric containment.**
A region's representative point can lie outside its parent's polygon — islands
especially — which is why the old implementation returned nothing for
`search("嵊泗县", province="浙江省")`.

```
under province P: region.code[:2] == P.code[:2]
under city C:     region.level == "district" -> region.parent == C.code
                  otherwise                  -> region.code == C.code
```

### 2.5 `list_regions(level) -> Region[]`

Every region at that level, **sorted by adcode ascending**. An invalid `level`
raises the language's idiomatic argument error.

### 2.6 `get_region(code) -> Region?`

Look up by adcode, searching `province` → `city` → `district`, returning the
first hit.

### 2.7 `lookup_adcode(adcode) -> ReverseResult?`

```
1. Not 6 digits -> return null
2. Determine the level from the adcode:
     ends with "0000" -> province
     ends with "00"   -> city
     otherwise        -> district
3. province = lookup(adcode[:2] + "0000")
4. city:
     MERGED prefix        -> copy of province (level = "city")
     level is district    -> lookup(that adcode's parent)
     level is city        -> lookup(adcode)
5. district = lookup(adcode) in the district layer
     Note: try this even when the level was judged to be city, because the
     prefecture-level cities with no subdivisions (东莞 441900, 中山 442000,
     儋州 460400, 嘉峪关 620200) exist in both the city and district layers
6. All three null -> return null; otherwise return the triple
```

### 2.8 `is_in_china(lat, lng) -> bool`

Equivalent to `reverse(lat, lng).province != null`.

### 2.9 `is_in_region(lat, lng, adcode) -> bool`

```
1. Malformed or unknown adcode -> raise the language's idiomatic argument
   error (do not return false)
2. Level is city and the prefix is MERGED -> test the province polygon instead
3. Otherwise -> point-in-polygon against that adcode's polygon (§3.3)
```

### 2.10 `get_administrative_tree() -> TreeNode[]`

Province → city → district. Provinces sorted by adcode; `children` at every
level sorted by `value`. A province with a MERGED prefix has exactly one city
node whose `value` equals the province adcode. 台湾省 (710000) has no
sub-divisions, so its `children` is an empty array.

### 2.11 Coordinate conversions

Six conversions: `wgs84_to_gcj02`, `gcj02_to_wgs84`, `gcj02_to_bd09`,
`bd09_to_gcj02`, `wgs84_to_bd09`, `bd09_to_wgs84`; plus `distance` (kilometres).

⚠️ **Argument order is not consistent within this package.** Check each one when
porting:

| Function | Signature | Returns |
|----------|-----------|---------|
| The six conversions | `(lng, lat)` — **longitude first** | `(lng, lat)` |
| `distance` | `(lat1, lng1, lat2, lng2)` — latitude first | kilometres |
| All `GeoTool` methods | `(lat, lng)` — latitude first | — |

This is a **silent-failure** trap: passing `(lat, lng)` to a conversion does not
raise, because the swapped longitude (originally a latitude, so |v| < 90)
usually falls outside the China bounding box, and the function returns the input
unchanged under the "pass through outside China" rule. Both `INV-08` in
`test_invariants.py` and the conformance generator were once silently testing
nothing for exactly this reason.

Coordinates outside China are returned unchanged, decided by:

```
out_of_china = !(72.004 < lng < 137.8347 && 0.8293 < lat < 55.8271)
```

The constants must match digit for digit:

```
A  = 6378245.0
EE = 0.00669342162296594
X_PI = π × 3000 / 180
EARTH_RADIUS_KM = 6371.0
```

> ⚠️ **Conformance cannot catch a mistyped constant.** Changing `A` to
> `6378245.5` (0.5 m) moves output by at most 7.6e-10 degrees ≈ **0.084 mm**
> across the whole dataset — below the 1e-9 degree comparison tolerance.
> Truncating `EE` to 13 significant digits moves it by 1e-10 mm. Such errors are
> physically meaningless, but it means **constant correctness can only be
> guaranteed by code review**, not by tests. Compare the table above character by
> character when porting.
> (`EARTH_RADIUS_KM` is the exception: it scales `distance` linearly, so
> conformance does catch it.)

`gcj02_to_wgs84` is a **single-step subtraction** rather than an iterative
inverse, so the round trip is inherently lossy. Measured over 20,000 random
points inside China:

| Conversion pair | Median | p99 | Max |
|-----------------|--------|-----|-----|
| `wgs84 ↔ gcj02` | 0.64 m | 3.20 m | 4.75 m |
| `gcj02 ↔ bd09` | 0.05 m | 0.17 m | 0.22 m |
| `wgs84 ↔ bd09` | 0.64 m | 3.22 m | 4.72 m |

An implementation's round-trip error should sit in the same range. If one is
markedly more accurate it is using an iterative inverse — a **different
algorithm**, which will diverge from the other implementations, so revise this
specification first.

---

## 3. Tie-breaking rules

This is where cross-language implementations drift silently. Follow each rule
literally.

### 3.1 Rounding

**Always round half away from zero** (`0.5 → 1`, `-0.5 → -1`).

⚠️ Language defaults differ: Python's `round()` is banker's rounding
(`round(0.5) == 0`); JavaScript's `Math.round` is half-up
(`Math.round(-0.5) == -0`). Neither matches this specification, so implement it
explicitly:

```
round_half_away(x) = sign(x) * floor(abs(x) + 0.5)
```

### 3.2 Quantisation

```
quantize(v)   = round_half_away(v * 10^precision)      -> integer
dequantize(q) = q / 10^precision                       -> float
```

`precision` comes from the file header (5 for `full`, 4 for `lite`).

Before any geometric test, scale the query coordinate by the same `precision`
as a **float, without rounding**, so the query point is not snapped onto the
quantisation lattice:

```
qx = lng * 10^precision      (stays a float)
qy = lat * 10^precision
```

### 3.3 Point in polygon

Use **even-odd ray casting**, edge by edge:

```
inside = false
for i in 0..n-1:
    j = (i - 1 + n) mod n
    if (ys[i] > y) != (ys[j] > y):
        xint = xs[i] + (y - ys[i]) * (xs[j] - xs[i]) / (ys[j] - ys[i])
        if x < xint:
            inside = !inside
```

- Rings are closed (first point repeated), so make sure it is not counted twice.
- Polygons with holes: inside the outer ring **and** not inside any inner ring.
- MultiPolygons: a hit in any part is a hit.
- **A point exactly on the boundary counts as inside.** The algorithm above
  decides such points by floating-point chance, so conformance makes no
  assertions at numeric boundaries; implementations need no special handling.
- Reject by bounding box first.

### 3.4 Candidate iteration order

When a mixed grid cell holds several candidates, iterate them **by ascending
adcode** and return the first that contains the point. This is what makes every
implementation agree on a point even where the source polygons overlap.

### 3.5 Search matching

- Exact match first; substring matching only when there is no exact match and
  `fuzzy` is true.
- Substring matching is literal containment: no regex, no case folding, no
  Unicode normalisation.
- Result ordering: see §2.3.

---

## 4. The GTC binary format

Little-endian, 8-byte aligned, `mmap`-able. Integer index tables are stored
fixed-width so that implementations can read them without decoding.

### 4.1 Dataset tiers

| `dataset` | Name | Contents | Measured size |
|-----------|------|----------|---------------|
| 0 | `mini` | META + NAMES, no geometry | **0.13 MB** |
| 1 | `lite` | + 1e-4 geometry + 0.1° grid | **3.58 MB** |
| 2 | `full` | + 1e-5 geometry + 0.05° grid | **5.95 MB** |

The `mini` tier supports every API except `reverse`, `reverse_batch`,
`is_in_china` and `is_in_region`. Calling a geometry-dependent API should raise
a clear error rather than return an empty result.

### 4.2 Header (32 bytes)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| 0 | 4 | `magic` | ASCII `"GTCN"` |
| 4 | 2 | `format_version` | u16, `1` for this spec. An implementation must refuse a major version it does not know |
| 6 | 1 | `dataset` | u8, see §4.1 |
| 7 | 1 | `precision` | u8, quantisation exponent |
| 8 | 4 | `data_version` | u32, e.g. `20260307` |
| 12 | 2 | `section_count` | u16 |
| 14 | 2 | — | reserved, zero |
| 16 | 4 | `grid_origin_lng` | i32, quantised by 1e6 |
| 20 | 4 | `grid_origin_lat` | i32, quantised by 1e6 |
| 24 | 4 | `grid_step` | u32, quantised by 1e6 (0.05° → `50000`) |
| 28 | 2 | `grid_width` | u16, columns |
| 30 | 2 | `grid_height` | u16, rows |

### 4.3 Section table

Immediately after the header, `section_count` entries of 24 bytes each:

| Offset | Size | Field |
|--------|------|-------|
| 0 | 2 | `type` (below) |
| 2 | 2 | reserved, zero |
| 4 | 4 | `crc32`, CRC-32 (IEEE) of the section's bytes |
| 8 | 8 | `offset`, byte offset from the start of the file |
| 16 | 8 | `length`, byte length |

| `type` | Section | Notes |
|--------|---------|-------|
| 1 | `META` | Division metadata |
| 2 | `NAMES` | UTF-8 string pool |
| 3 | `GEOM` | Quantised geometry |
| 4 | `GEOM_INDEX` | Geometry offset table |
| 5 | `GRID_SOLID` | **District** grid: solid runs |
| 6 | `GRID_MIXED_CELLS` | District grid: mixed cell ids |
| 7 | `GRID_MIXED_PTRS` | District grid: candidate slice pointers |
| 8 | `GRID_MIXED_LISTS` | District grid: candidate lists |
| 9 | `GRID_PROV_SOLID` | **Province** grid, same structure as 5–8 |
| 10 | `GRID_PROV_MIXED_CELLS` | |
| 11 | `GRID_PROV_MIXED_PTRS` | |
| 12 | `GRID_PROV_MIXED_LISTS` | |

Sections are ordered by `type` ascending, `offset` is 8-byte aligned, and
padding is allowed.

### 4.4 The META section

```
u32  record_count
then record_count records of 28 bytes each:
  u32  adcode
  u8   level          0=province 1=city 2=district
  u8   reserved[3]
  u32  parent         parent adcode; 0 when there is none
  u32  name_offset    byte offset into the NAMES section
  u16  name_length    UTF-8 byte count
  u16  reserved
  i32  lat            representative point, quantised by 1e6
  i32  lng
```

Records are sorted by `(level, adcode)` ascending. **A record's index is its
region_index**, which both the grid index and `GEOM_INDEX` refer to.

`NAMES` is a UTF-8 string pool with no separators, sliced by
`(name_offset, name_length)`.

### 4.5 The GEOM and GEOM_INDEX sections

`GEOM_INDEX` is `u32[record_count + 1]`; entry `i` is where region `i` starts
within `GEOM`, and the last entry equals the length of `GEOM`. A region with no
geometry has equal start and end offsets.

Each region in `GEOM` is encoded as:

```
i32  bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y    (quantised)
uvarint  polygon_count
per polygon:
  uvarint  ring_count                (first ring is the exterior, the rest are holes)
  per ring:
    uvarint  point_count
    point_count pairs of (dx, dy), both zigzag varints,
    delta from the previous point; the first is relative to (0, 0)
```

> ⚠️ **Counts are plain unsigned varints; coordinates are zigzag varints.**
> Do not mix them up. The prototype zigzagged every integer, which doubled every
> ring count and ran the decoder off the end of the section.

Varints are LEB128: the low 7 bits of each byte carry data, the top bit is the
continuation flag. Zigzag encodes as `(n << 1) ^ (n >> 63)` and decodes as
`(u >> 1) ^ -(u & 1)`.

### 4.6 The grid index

```
col = floor((lng - grid_origin_lng / 1e6) / (grid_step / 1e6))
row = floor((lat - grid_origin_lat / 1e6) / (grid_step / 1e6))
if col or row is out of range -> the point is outside coverage, return null
cell_id = row * grid_width + col
```

There are **two grids: district-level (sections 5–8) and province-level
(sections 9–12)**, identical in structure.

The province grid is **not an optional optimisation**: 台湾省 has province-level
boundaries only, so routing every containment test through the district grid
reports the whole island as outside China; the gaps between coastal districts
need it as a fallback too. Step 2 of §2.1 and the province paths in §2.8 and
§2.9 all depend on it. Omitting this grid during implementation was caught by
`INV-04` (a region must contain its own representative point).

Both the `lite` and `full` tiers must carry all 12 sections; in the `mini` tier
the geometry and grid sections have length 0.

**`GRID_SOLID`** — cells lying wholly inside a single region, run-length encoded:

```
u32  run_count
then run_count entries of 12 bytes each:
  u32  start_cell
  u32  length          number of consecutive cells
  u32  region_index
```

Runs are sorted by `start_cell`, non-overlapping, and **must not span a row**
(`start_cell` and `start_cell + length - 1` must share a `row`). Look them up by
binary search.

**`GRID_MIXED_*`** — cells that need a geometric test:

```
GRID_MIXED_CELLS  u32 count, then u32[count] of cell_ids ascending
GRID_MIXED_PTRS   u32[count + 1], slicing LISTS
GRID_MIXED_LISTS  u32[] of region_index; each cell's candidates sorted by adcode
```

An empty cell (in neither SOLID nor MIXED) means nothing covers that location.

> Fixed-width storage is a **trade between size and load time**. Measured: a
> naive per-cell `int32` index is 6.76 MB; fixed-width runs are 2.06 MB and load
> in about 7 ms; fully varint-compressed is 0.65 MB but takes about 60 ms to
> load. Fixed-width wins because npm and PyPI already compress in transit, so
> saving 1.4 MB is not worth 8× the startup cost.

### 4.7 The lookup algorithm

```
lookup(lat, lng):
    compute cell_id; out of range -> null
    binary search GRID_SOLID: a hit returns region_index directly   <- ~77% of queries end here
    binary search GRID_MIXED_CELLS: a miss returns null
    take that cell's candidate list (already sorted by adcode)
    for each: reject by bbox, then test point-in-polygon; return the first hit
    no hit -> null
```

---

## 5. Conformance requirements

- An implementation must pass every case in `conformance/`, without
  special-casing individual cases.
- Any difference from the reference implementation must be registered in
  `conformance/known-divergences.yaml`; **an unregistered difference is a
  regression.**
- The bar for a new language implementation is in
  `docs/RFC-002-testing-and-acceptance.md` §7.

## 6. Change process

Any change to this specification must also update `format_version` (when the
binary layout changes) or the conformance dataset (when behaviour changes), and
be described in `CHANGELOG.md`.
