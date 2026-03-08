# CLAUDE.md - GeoToolCN

## Project Overview
Offline geocoding toolkit for Chinese administrative regions. Converts GPS coordinates to province/city/district and supports forward geocoding by name or adcode. Published on PyPI as `geotool-cn`.

## Quick Reference
- **Language**: Python 3.9+
- **Dependencies**: geopandas (>=0.14), shapely (>=2)
- **Package**: `GeoToolCN/` (source), published as `geotool-cn`
- **Tests**: `tests/test_geotool.py` — run with `pytest`
- **Build**: `pyproject.toml` only (setuptools backend, no setup.py)
- **CI/CD**: `.github/workflows/publish.yml` — auto-publish to PyPI on GitHub release

## Commands
```bash
# Run all tests
pytest

# Run specific test class
pytest tests/test_geotool.py::TestReverse

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
- `GeoToolCN/data/*.geojson` — Bundled GeoJSON files (province/city/district boundaries)
- `GeoToolCN/data/china_admin.json` — Lightweight admin division data for tree builder
- `GeoToolCN/data/DATA_VERSION.json` — Data version metadata (source, date, counts)
- `scripts/fetch_datav_geojson.py` — Fetch & convert data from DataV API, generates diff report
- `scripts/generate_admin_data.py` — Legacy script (腾讯 Excel → china_admin.json, no longer used)
- `tests/test_geotool.py` — pytest test suite for geocoding (module-scoped fixture)
- `tests/test_admin_tree.py` — pytest test suite for admin tree
- `DATA_UPDATE_REPORT.md` — Auto-generated report from last data update

### Key Classes
- **`GeoTool`**: Main API class — `reverse()`, `reverse_batch()`, `search()`, `list_regions()`, `get_region()`
- **`Region`**: Dataclass — `name`, `code` (6-digit adcode), `level`, `latitude`, `longitude`
- **`ReverseResult`**: Dataclass — optional `province`, `city`, `district` (each a `Region`)

### Performance Patterns
- R-tree spatial index via GeoPandas `sindex` for O(log n) point-in-polygon
- `gpd.sjoin()` for batch spatial joins
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
