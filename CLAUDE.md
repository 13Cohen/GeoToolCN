# CLAUDE.md - GeoToolCN

## Project Overview
Offline geocoding toolkit for Chinese administrative regions. Converts GPS coordinates to province/city/district and supports forward geocoding by name or adcode. Published on PyPI as `geotool-cn`.

## Quick Reference
- **Language**: Python 3.9+
- **Dependencies**: none at runtime. geopandas/shapely are dev-only extras,
  needed to rebuild the data and to run the differential test
- **Package**: `GeoToolCN/` (source), published as `geotool-cn`
- **Tests**: `tests/test_geotool.py` — run with `pytest`
- **Build**: `pyproject.toml` only (setuptools backend, no setup.py)
- **CI/CD**: `.github/workflows/test.yml` — tests, conformance matrix and dependency
  assertions on push/PR; `.github/workflows/release.yml` — publishes per ecosystem from
  its own tag prefix (`py-v*`, `npm-v*`, `cli-v*`, `packages/go/v*`)

## Commands
```bash
# Run all tests
pytest

# Run specific test class
pytest tests/test_geotool.py::TestReverse

# Structural invariants only (100% adcode coverage, no golden values)
pytest tests/test_invariants.py

# Validate bundled data
python scripts/validate_data.py

# Conformance suite (regenerate only after an intentional behaviour change)
python conformance/run.py
python conformance/generate.py

# Differential test against the geopandas oracle (needs the dev extras)
python conformance/differential.py -n 200000

# Rebuild the shipped dataset and validate it
python pipeline/build_gtc.py
python scripts/validate_gtc.py --round-trip

# The other tiers (SPEC §4.1) — built in CI, not committed
python pipeline/build_gtc.py --dataset lite --out /tmp/china.lite.gtc

# Guard README's CRLF endings against script-driven edits
python scripts/check_line_endings.py

# Update bundled data (fetches from DataV API, converts GCJ-02→WGS-84)
python scripts/fetch_datav_geojson.py

# Build package
python -m build

# Install in dev mode
pip install -e .
```

## Architecture
- `GeoToolCN/__init__.py` — Public API exports + module-level convenience functions (lazy singleton)
- `GeoToolCN/core.py` — `GeoTool`, `Region`, `ReverseResult`, on top of the .gtc reader
- `GeoToolCN/_gtc.py` — .gtc binary reader (stdlib only); the model for every port
- `pipeline/build_gtc.py` — builds the .gtc from GeoJSON; all the expensive work lives here
- `reference/geopandas_impl.py` — the geopandas implementation, kept as an oracle for
  `conformance/differential.py`. Not shipped, not published
- `GeoToolCN/admin_tree.py` — Administrative tree builder (zero geopandas dependency)
- `GeoToolCN/_hierarchy.py` — Parent/merged-prefix rules shared by `core` and `admin_tree`,
  stdlib-only so the tree builder stays free of geopandas
- `GeoToolCN/data/china.full.gtc` — the shipped dataset (6 MB)
- `GeoToolCN/data/*.geojson` — pipeline input; in the repo but NOT in the wheel (28 MB)
- `GeoToolCN/data/china_admin.json` — Lightweight admin division data for tree builder
- `GeoToolCN/data/DATA_VERSION.json` — Data version metadata (source, date, counts)
- `scripts/fetch_datav_geojson.py` — Fetch & convert data from DataV API, generates diff report
- `scripts/generate_admin_data.py` — Legacy script (腾讯 Excel → china_admin.json, no longer used)
- `tests/test_geotool.py` — pytest test suite for geocoding (module-scoped fixture)
- `tests/test_admin_tree.py` — pytest test suite for admin tree
- `tests/test_invariants.py` — structural invariants (INV-01..12); asserts properties that
  must hold for *every* region, so one test yields thousands of assertions
- `scripts/validate_data.py` — 10 categories of source-GeoJSON checks; run in CI
- `scripts/validate_gtc.py` — L0 checks on a built `.gtc`: CRC, metadata ordering, parent
  coverage, representative points, every solid grid run, and a cross-check against the
  source geometry. `--round-trip` also asserts the build is deterministic
- `SPEC.md` — the cross-language contract: API semantics, tie-breaking rules, GTC binary
  format. Behaviour changes go here first, then into the implementation
- `conformance/` — language-neutral golden suite (~35k cases). `generate.py` rebuilds it
  from this implementation, `run.py` checks any implementation against it via a
  line-protocol adapter, `known-divergences.yaml` lists the differences that are allowed
- `conformance/adapters/` — one file per language binding; adding a language means
  adding an adapter here and a row to the CI matrix
- `packages/node/` — `@geotoolcn/core`, zero dependencies, ESM. Plain JS with JSDoc plus a
  hand-written `index.d.ts`: no build step, so nothing to keep in sync with the source
- `packages/go/` — no cgo, dataset via `go:embed`. Imported as
  `github.com/13Cohen/GeoToolCN/packages/go`, released by tagging `packages/go/v3.0.0`;
  both shapes are what Go requires of a module in a subdirectory.
  `packages/go/data/china.full.gtc` is committed — the only duplicated copy in the repo —
  because `go get` fetches only what git holds and `go:embed` cannot reach outside the
  module directory
- `packages/go/cmd/geotoolcn/` — the CLI and HTTP server, covering languages with no
  binding. Go because it produces one static binary with the dataset inside
- `PORTING.md` — what to implement, which mutations prove the suite covers your code,
  and the checklist for getting a port merged
- `SPEC_EN.md` / `PORTING_EN.md` — English translations for contributors who do not read
  Chinese. The Chinese originals are normative; each translation records the SHA-256 of
  the source it was written from and `scripts/check_translations.py` fails CI when they
  drift. After editing a source: update the translation, then run that script with
  `--update`
- `docs/RELEASING.md` — which tag publishes what, and the credentials each needs.
  Records that NPM_TOKEN expires 2026-12-09: npm caps write tokens at 90 days, so
  the npm job fails alone while the other three ecosystems keep working
- `DATA_UPDATE_REPORT.md` — Auto-generated report from last data update

### Hierarchy Resolution — read before touching `reverse()`
The province/city/district chain is derived from the **district's adcode**, not from three
independent point-in-polygon tests.  The source layers genuinely disagree: 加格达奇区 is
administered by 黑龙江 but sits inside 内蒙古's province polygon, some district polygons
extend past their province onto offshore islands, and city polygons overlap across
prefecture borders.  Independent per-level lookups produce self-contradictory results.
- `_parent_city` (built in `_build_parent_index`) maps district adcode → city adcode.
  Do **not** use `adcode[:4] + "00"` — it is wrong for the 30 province-directly-governed
  county-level divisions (blocks 4190/4290/4690/6590), yielding codes like `419000`.
- Independent per-level lookup survives only as the fallback for points where no district
  matches (offshore gaps).

### Key Classes
- **`GeoTool`**: Main API class — `reverse()`, `reverse_batch()`, `search()`, `list_regions()`, `get_region()`
- **`Region`**: Dataclass — `name`, `code` (6-digit adcode), `level`, `latitude`, `longitude`
- **`ReverseResult`**: Dataclass — optional `province`, `city`, `district` (each a `Region`)

### Performance Patterns
- The grid index answers ~77% of lookups from a run-length table with no geometry at all;
  the rest average 2 candidate polygons. That is why no geometry library is needed
- Polygons are decoded lazily and cached — parsing all ~1M vertices up front would cost seconds
- Integer tables are fixed-width so `array.frombytes` over the mmap is a memcpy
- Dict-based `name_index` and `code_index` for O(1) lookups
- `make_valid()` on load to fix invalid geometries from data source

## Code Conventions
- **Naming**: PascalCase classes, snake_case functions, UPPER_CASE constants, `_` prefix for private
- **Type hints**: Modern style with `from __future__ import annotations`, union `X | None`
- **Data structures**: `@dataclass` for value objects
- **Docstrings**: NumPy-style (Parameters/Returns sections)
- **Testing**: pytest with class-based organization, module-scoped fixtures

## Data — Unified Source

All data (GeoJSON boundaries + admin tree) comes from a **single source**: DataV.GeoAtlas (阿里云 DataV).

- **Source**: [DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas) (API: `geo.datav.aliyun.com`)
- **Update script**: `python scripts/fetch_datav_geojson.py`
- **Format**: GeoJSON MultiPolygon, converted from GCJ-02 to WGS-84
- **Codes**: 6-digit adcodes (e.g., `410000` = 河南省)
- **Files**: `china_province.geojson`, `china_city.geojson`, `china_district.geojson`, `china_admin.json`
- **Version tracking**: `DATA_VERSION.json` records source, fetch date, and counts
- **Diff report**: `DATA_UPDATE_REPORT.md` auto-generated on each update with added/removed regions
- **Coverage**: 34 provinces, 363 cities, 2874 districts (Taiwan province-level only)

### Updating Data
1. Run `python scripts/fetch_datav_geojson.py` (takes ~5 min, needs internet)
2. Review generated `DATA_UPDATE_REPORT.md` for changes
3. Run `pytest` to verify nothing broke
4. Commit the updated data files

## Ports
Every implementation reads the same `.gtc` and is held to the same conformance suite.
Behaviour changes go into `SPEC.md` first, then into each implementation.

```bash
python conformance/run.py                                              # Python
python conformance/run.py --adapter cmd --cmd "node conformance/adapters/node.mjs"
cd packages/go && CGO_ENABLED=0 go build -o /tmp/gtc-adapter ./cmd/conformance-adapter
python conformance/run.py --adapter cmd --cmd /tmp/gtc-adapter
```

The tree hash is the fiddliest thing to match: `children` must be present (possibly
empty) on province and city nodes and absent on leaves, and the canonical JSON sorts
keys, omits spaces and does not escape non-ASCII. See SPEC §1.3.

Each binding's dataset is a copy, gitignored so the 6 MB binary is committed once rather
than once per language. After rebuilding the `.gtc`:

```bash
node packages/node/scripts/sync-data.mjs   # gitignored, rebuilt on demand
bash packages/go/scripts/sync-data.sh      # commit the result: go get needs it in git
```

## Repository
- **Main branch**: `master`
- **Author**: Cohen
- **License**: MIT
- **GitHub**: https://github.com/13Cohen/GeoToolCN
