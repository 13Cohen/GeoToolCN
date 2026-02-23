# GeoToolCN

[![PyPI](https://img.shields.io/pypi/v/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![Python](https://img.shields.io/pypi/pyversions/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Offline geocoding toolkit for Chinese administrative regions.
Covers all provinces, cities, and districts with no API keys or network access required.

中国行政区划离线地理编码工具，覆盖全部省、市、区县，无需 API 密钥或网络。

## Features

- **Reverse geocoding** — coordinate → province / city / district
- **Forward geocoding** — name or GB admin code → coordinates
- **Batch processing** — reverse-geocode thousands of coordinates in one call
- **R-tree spatial index** — fast point-in-polygon lookup
- **Typed dataclasses** — structured `Region` and `ReverseResult` objects
- **Zero network** — fully offline, bundled GeoJSON data

## Installation

```bash
pip install geotool-cn
```

## Quick Start

```python
from geotool_cn import GeoTool

geo = GeoTool()

# Reverse geocoding (coordinate → admin regions)
result = geo.reverse(39.9, 116.4)
print(result.province.name)   # 北京市
print(result.district.name)   # 东城区
print(result.district.code)   # 156110101

# Forward geocoding (name/code → coordinates)
regions = geo.search("深圳市")
print(regions[0].latitude, regions[0].longitude)

# Batch reverse geocoding
results = geo.reverse_batch([(39.9, 116.4), (31.2, 121.5)])

# List all provinces
provinces = geo.list_regions("province")

# Lookup by GB code
region = geo.get_region("156110000")
```

### Convenience Functions

Module-level shortcuts that use a shared singleton instance:

```python
from geotool_cn import reverse, search, reverse_batch, list_regions, get_region

result = reverse(39.9, 116.4)
regions = search("深圳市")
```

## API Reference

### `GeoTool(data_dir=None)`

Create a geocoding instance. Pass `data_dir` to use custom GeoJSON files instead of the bundled data.

### `geo.reverse(lat, lng) → ReverseResult`

Reverse-geocode a single WGS-84 coordinate.

### `geo.reverse_batch(coords) → list[ReverseResult]`

Reverse-geocode many `(lat, lng)` pairs at once using spatial join.

### `geo.search(query, *, level=None, province=None, city=None, fuzzy=True) → list[Region]`

Search by region name or GB admin code. Set `level` to `"province"`, `"city"`, or `"district"` to narrow results. Use `province` or `city` to disambiguate regions with the same name (accepts name or GB code). Fuzzy matching is enabled by default.

```python
# "朝阳区" exists in both Beijing and Changchun
geo.search("朝阳区")                     # returns both
geo.search("朝阳区", province="北京市")    # only Beijing's
geo.search("朝阳区", city="长春市")        # only Changchun's
```

### `geo.list_regions(level) → list[Region]`

List all regions at a given level (`"province"`, `"city"`, or `"district"`).

### `geo.get_region(code) → Region | None`

Look up a single region by its GB admin code.

### Data Classes

```python
@dataclass
class Region:
    name: str        # "北京市"
    code: str        # "156110000"
    level: str       # "province" | "city" | "district"
    latitude: float  # representative point latitude
    longitude: float # representative point longitude

@dataclass
class ReverseResult:
    province: Region | None
    city: Region | None
    district: Region | None
```

## Performance

| Operation | Before | GeoToolCN v1.0 |
|-----------|--------|----------------|
| Load data | Every call (~2s) | Once on init (~2s) |
| Single reverse | ~2s (brute-force) | ~1ms (R-tree index) |
| Batch 1000 pts | ~2000s | ~1s (spatial join) |
| Forward search | ~0.5s (scan) | <0.1ms (dict index) |

## Custom Data

Download the latest data from [天地图](https://cloudcenter.tianditu.gov.cn/administrativeDivision/), rename to `china_province.geojson`, `china_city.geojson`, `china_district.geojson`, and pass the directory:

```python
geo = GeoTool(data_dir="/path/to/data")
```

## Data Source / 数据来源

[天地图](https://cloudcenter.tianditu.gov.cn/administrativeDivision/) (updated September 2025)

## License

MIT
