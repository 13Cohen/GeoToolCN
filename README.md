# GeoToolCN

[![PyPI](https://img.shields.io/pypi/v/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![Python](https://img.shields.io/pypi/pyversions/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

中国行政区划离线地理编码工具，覆盖全部省、市、区县，无需 API 密钥或网络。

[English](README_EN.md)

## 功能特点

- **逆地理编码** — 经纬度坐标 → 省 / 市 / 区县
- **正向地理编码** — 地名或行政区划代码 → 经纬度坐标
- **批量处理** — 一次调用即可逆编码数千个坐标点
- **R-tree 空间索引** — 快速点在多边形查询
- **类型化数据类** — 结构化的 `Region` 和 `ReverseResult` 对象
- **行政区划树** — 省→市→区县三级树，适用于前端级联选择器，无需 geopandas
- **零网络依赖** — 完全离线，内置数据

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
print(result.district.code)   # 110101

# 正向地理编码（地名/代码 → 坐标）
regions = geo.search("深圳市")
print(regions[0].latitude, regions[0].longitude)

# 批量逆地理编码
results = geo.reverse_batch([(39.9, 116.4), (31.2, 121.5)])

# 列出所有省份
provinces = geo.list_regions("province")

# 按 adcode 查询
region = geo.get_region("110000")
```

### 行政区划树

省→市→区县三级树，适用于前端级联选择器（Cascader）等场景。**无需 geopandas**。

```python
from geotool_cn import get_administrative_tree

tree = get_administrative_tree()
# tree[0] = {"value": "110000", "label": "北京市", "children": [...]}
```

直辖市（北京、天津、上海、重庆）和特别行政区（香港、澳门）的市级节点 `value` 使用省级代码。结果按 `value` 升序排列，首次调用后缓存。

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

按地名或 adcode 搜索。设置 `level` 为 `"province"`、`"city"` 或 `"district"` 可缩小搜索范围。使用 `province` 或 `city` 参数可消除同名区划的歧义（接受地名或 adcode）。默认开启模糊匹配。

```python
# "朝阳区"在北京和长春都存在
geo.search("朝阳区")                     # 返回两个结果
geo.search("朝阳区", province="北京市")    # 仅返回北京的
geo.search("朝阳区", city="长春市")        # 仅返回长春的
```

### `geo.list_regions(level) → list[Region]`

列出指定级别（`"province"`、`"city"` 或 `"district"`）的所有行政区划。

### `geo.get_region(code) → Region | None`

按 adcode 查询单个区划。

### `get_administrative_tree() → list[dict]`

返回省→市→区县三级行政区划树。每个节点格式：`{"value": "adcode", "label": "名称", "children": [...]}`。覆盖 34 个省级单位（含台湾、香港、澳门），2800+ 区县。该函数不依赖 geopandas，首次调用后缓存。

### 数据类

```python
@dataclass
class Region:
    name: str        # "北京市"
    code: str        # "110000" (6位 adcode)
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

## 更新数据

GeoJSON 边界数据和行政区划树使用**同一数据源**（DataV.GeoAtlas），通过脚本一键更新：

```bash
python scripts/fetch_datav_geojson.py
```

脚本会：
1. 从 DataV API 递归下载省/市/区县边界数据
2. 将坐标从 GCJ-02 转换为 WGS-84
3. 生成 `china_province.geojson`、`china_city.geojson`、`china_district.geojson` 和 `china_admin.json`
4. 更新 `DATA_VERSION.json`（记录数据源、日期、数量）
5. 生成 `DATA_UPDATE_REPORT.md`（与上次数据的差异报告）
6. 自动运行数据校验（数量、adcode、层级关系、几何有效性、地标抽检等）

也可单独运行校验：

```bash
python scripts/validate_data.py
```

也可传入自定义数据目录：

```python
geo = GeoTool(data_dir="/path/to/data")
```

## 数据来源

| 字段 | 值 |
|------|-----|
| 数据源 | [DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas)（阿里云 DataV 地理小工具） |
| 覆盖范围 | 34 省 / 363 市 / 2874 区县 |
| 坐标系 | WGS-84（原始 GCJ-02 已转换） |
| 编码体系 | 6 位 adcode |
| 最近更新 | 2026 年 3 月 |

## 许可证

MIT
