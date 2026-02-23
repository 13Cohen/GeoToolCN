# GeoToolCN

[![PyPI](https://img.shields.io/pypi/v/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![Python](https://img.shields.io/pypi/pyversions/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

中国行政区划离线地理编码工具，覆盖全部省、市、区县，无需 API 密钥或网络。

[English](README_EN.md)

## 功能特点

- **逆地理编码** — 经纬度坐标 → 省 / 市 / 区县
- **正向地理编码** — 地名或国标行政区划代码 → 经纬度坐标
- **批量处理** — 一次调用即可逆编码数千个坐标点
- **R-tree 空间索引** — 快速点在多边形查询
- **类型化数据类** — 结构化的 `Region` 和 `ReverseResult` 对象
- **零网络依赖** — 完全离线，内置 GeoJSON 数据

## 安装

```bash
pip install geotool-cn
```

## 快速上手

```python
from geotool_cn import GeoTool

geo = GeoTool()

# 逆地理编码（坐标 → 行政区划）
result = geo.reverse(39.9, 116.4)
print(result.province.name)   # 北京市
print(result.district.name)   # 东城区
print(result.district.code)   # 156110101

# 正向地理编码（地名/代码 → 坐标）
regions = geo.search("深圳市")
print(regions[0].latitude, regions[0].longitude)

# 批量逆地理编码
results = geo.reverse_batch([(39.9, 116.4), (31.2, 121.5)])

# 列出所有省份
provinces = geo.list_regions("province")

# 按国标代码查询
region = geo.get_region("156110000")
```

### 便捷函数

模块级快捷方式，使用共享的单例实例：

```python
from geotool_cn import reverse, search, reverse_batch, list_regions, get_region

result = reverse(39.9, 116.4)
regions = search("深圳市")
```

## API 参考

### `GeoTool(data_dir=None)`

创建地理编码实例。传入 `data_dir` 可使用自定义 GeoJSON 文件替代内置数据。

### `geo.reverse(lat, lng) → ReverseResult`

对单个 WGS-84 坐标进行逆地理编码。

### `geo.reverse_batch(coords) → list[ReverseResult]`

使用空间连接对多个 `(lat, lng)` 坐标对进行批量逆地理编码。

### `geo.search(query, *, level=None, province=None, city=None, fuzzy=True) → list[Region]`

按地名或国标行政区划代码搜索。设置 `level` 为 `"province"`、`"city"` 或 `"district"` 可缩小搜索范围。使用 `province` 或 `city` 参数可消除同名区划的歧义（接受地名或国标代码）。默认开启模糊匹配。

```python
# "朝阳区"在北京和长春都存在
geo.search("朝阳区")                     # 返回两个结果
geo.search("朝阳区", province="北京市")    # 仅返回北京的
geo.search("朝阳区", city="长春市")        # 仅返回长春的
```

### `geo.list_regions(level) → list[Region]`

列出指定级别（`"province"`、`"city"` 或 `"district"`）的所有行政区划。

### `geo.get_region(code) → Region | None`

按国标行政区划代码查询单个区划。

### 数据类

```python
@dataclass
class Region:
    name: str        # "北京市"
    code: str        # "156110000"
    level: str       # "province" | "city" | "district"
    latitude: float  # 代表点纬度
    longitude: float # 代表点经度

@dataclass
class ReverseResult:
    province: Region | None
    city: Region | None
    district: Region | None
```

## 性能

| 操作 | 优化前 | GeoToolCN v1.0 |
|------|--------|----------------|
| 加载数据 | 每次调用 (~2s) | 初始化一次 (~2s) |
| 单次逆编码 | ~2s（暴力遍历） | ~1ms（R-tree 索引） |
| 批量 1000 点 | ~2000s | ~1s（空间连接） |
| 正向搜索 | ~0.5s（扫描） | <0.1ms（字典索引） |

## 自定义数据

从[天地图](https://cloudcenter.tianditu.gov.cn/administrativeDivision/)下载最新数据，分别命名为 `china_province.geojson`、`china_city.geojson`、`china_district.geojson`，然后传入目录路径：

```python
geo = GeoTool(data_dir="/path/to/data")
```

## 数据来源

[天地图](https://cloudcenter.tianditu.gov.cn/administrativeDivision/)（2025 年 9 月更新）

## 许可证

MIT
