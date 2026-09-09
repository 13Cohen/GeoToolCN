# CLAUDE.md - GeoToolCN

## Project Overview
Offline geocoding toolkit for Chinese administrative regions. Converts GPS coordinates to province/city/district and supports forward geocoding by name or adcode. Published on PyPI as `geotool-cn`.

## Quick Reference
- **Language**: Python 3.9+
- **Dependencies**: geopandas (>=0.14), shapely (>=2)
- **Package**: `GeoToolCN/` (source), published as `geotool-cn`
- **Tests**: `tests/test_geotool.py` — run with `pytest`
- **Build**: `pyproject.toml` only (setuptools backend, no setup.py)
- **CI/CD**: `.github/workflows/test.yml` — pytest matrix (3.9–3.12) + data validation on push/PR;
  `.github/workflows/publish.yml` — auto-publish to PyPI on GitHub release

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

# Update bundled data (fetches from DataV API, converts GCJ-02→WGS-84)
python scripts/fetch_datav_geojson.py

# Build package
python -m build

# Install in dev mode
pip install -e .
```

## Architecture
- `GeoToolCN/__init__.py` — Public API exports + module-level convenience functions (lazy singleton)
- `GeoToolCN/core.py` — Core implementation: `GeoTool`, `Region`, `ReverseResult` classes
- `GeoToolCN/admin_tree.py` — Administrative tree builder (zero geopandas dependency)
- `GeoToolCN/_hierarchy.py` — Parent/merged-prefix rules shared by `core` and `admin_tree`,
  stdlib-only so the tree builder stays free of geopandas
- `GeoToolCN/data/*.geojson` — Bundled GeoJSON files (province/city/district boundaries)
- `GeoToolCN/data/china_admin.json` — Lightweight admin division data for tree builder
- `GeoToolCN/data/DATA_VERSION.json` — Data version metadata (source, date, counts)
- `scripts/fetch_datav_geojson.py` — Fetch & convert data from DataV API, generates diff report
- `scripts/generate_admin_data.py` — Legacy script (腾讯 Excel → china_admin.json, no longer used)
- `tests/test_geotool.py` — pytest test suite for geocoding (module-scoped fixture)
- `tests/test_admin_tree.py` — pytest test suite for admin tree
- `tests/test_invariants.py` — structural invariants (INV-01..12); asserts properties that
  must hold for *every* region, so one test yields thousands of assertions
- `scripts/validate_data.py` — 10 categories of bundled-data checks; run in CI
- `SPEC.md` — the cross-language contract: API semantics, tie-breaking rules, GTC binary
  format. Behaviour changes go here first, then into the implementation
- `conformance/` — language-neutral golden suite (~35k cases). `generate.py` rebuilds it
  from this implementation, `run.py` checks any implementation against it via a
  line-protocol adapter, `known-divergences.yaml` lists the differences that are allowed
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
- R-tree spatial index via GeoPandas `sindex` for O(log n) point-in-polygon
- `reverse_batch()` loops `reverse()`; `gpd.sjoin()` measured slower at every batch size
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

## Repository
- **Main branch**: `master`
- **Author**: Cohen
- **License**: MIT
- **GitHub**: https://github.com/13Cohen/GeoToolCN
