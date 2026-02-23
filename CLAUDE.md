# CLAUDE.md - GeoToolCN (columbus)

## Project Overview
Offline geocoding toolkit for Chinese administrative regions. Converts GPS coordinates to province/city/district and supports forward geocoding by name or GB code. Published on PyPI as `geotool-cn`.

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
- `scripts/generate_admin_data.py` — One-time script to regenerate china_admin.json from Tencent Excel
- `tests/test_geotool.py` — pytest test suite for geocoding (module-scoped fixture)
- `tests/test_admin_tree.py` — pytest test suite for admin tree

### Key Classes
- **`GeoTool`**: Main API class — `reverse()`, `reverse_batch()`, `search()`, `list_regions()`, `get_region()`
- **`Region`**: Dataclass — `name`, `code`, `level`, `latitude`, `longitude`
- **`ReverseResult`**: Dataclass — optional `province`, `city`, `district` (each a `Region`)

### Performance Patterns
- R-tree spatial index via GeoPandas `sindex` for O(log n) point-in-polygon
- `gpd.sjoin()` for batch spatial joins
- Dict-based `name_index` and `code_index` for O(1) lookups

## Code Conventions
- **Naming**: PascalCase classes, snake_case functions, UPPER_CASE constants, `_` prefix for private
- **Type hints**: Modern style with `from __future__ import annotations`, union `X | None`
- **Data structures**: `@dataclass` for value objects
- **Docstrings**: NumPy-style (Parameters/Returns sections)
- **Testing**: pytest with class-based organization, module-scoped fixtures

## Data — Dual Sources

### Source 1: 天地图 GeoJSON (geocoding)
- Purpose: `reverse()`, `search()`, `list_regions()`, `get_region()` — spatial queries
- Source: [天地图](https://cloudcenter.tianditu.gov.cn/administrativeDivision/) (September 2025)
- Format: GeoJSON MultiPolygon, WGS-84 CRS
- Codes: 9-digit GB codes (e.g., `156410000` = 河南省)
- Files: `china_province.geojson`, `china_city.geojson`, `china_district.geojson`

### Source 2: 腾讯 LBS Excel (admin tree)
- Purpose: `get_administrative_tree()` — UI cascader / dropdown data
- Source: [腾讯位置服务](https://lbs.qq.com/service/webService/webServiceGuide/search/webServiceDistrict#9)
- Format: 6-digit adcodes + comma-separated names → compiled to `china_admin.json`
- Codes: 6-digit adcodes (e.g., `410000` = 河南省)
- Update: download latest Excel → `python scripts/generate_admin_data.py`

## Repository
- **Main branch**: `master`
- **Author**: Cohen
- **License**: MIT
- **GitHub**: https://github.com/13Cohen/GeoToolCN
