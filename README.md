# GeoToolCN

[![PyPI](https://img.shields.io/pypi/v/geotool-cn)](https://pypi.org/project/geotool-cn/)
[![npm](https://img.shields.io/npm/v/@geotoolcn/core)](https://www.npmjs.com/package/@geotoolcn/core)
[![Go Reference](https://pkg.go.dev/badge/github.com/13Cohen/GeoToolCN/packages/go/v3.svg)](https://pkg.go.dev/github.com/13Cohen/GeoToolCN/packages/go/v3)
[![Test](https://github.com/13Cohen/GeoToolCN/actions/workflows/test.yml/badge.svg)](https://github.com/13Cohen/GeoToolCN/actions/workflows/test.yml)
[![Published packages](https://github.com/13Cohen/GeoToolCN/actions/workflows/post-release.yml/badge.svg?event=schedule)](https://github.com/13Cohen/GeoToolCN/actions/workflows/post-release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

中国行政区划离线地理编码工具，覆盖全部省、市、区县，无需 API 密钥或网络。
Python、Node.js、Go 三种实现，外加一个覆盖其余语言的 CLI / HTTP 服务。

[English](README_EN.md)

## 功能特点

- **逆地理编码** — 经纬度坐标 → 省 / 市 / 区县
- **正向地理编码** — 地名或行政区划代码 → 经纬度坐标
- **行政区划树** — 省→市→区县三级树，适用于前端级联选择器
- **坐标系转换** — WGS-84 / GCJ-02 / BD-09 互转，以及球面距离
- **零依赖** — 每种实现都只用各自语言的标准库，6 MB 内置数据，冷启动几十毫秒
- **跨语言一致** — 三种实现读同一份数据文件，通过同一套 38,000+ 条一致性用例

## 安装

```bash
pip install geotool-cn                                # Python 3.9+
npm install @geotoolcn/core                           # Node.js 18+ / TypeScript
go get github.com/13Cohen/GeoToolCN/packages/go/v3    # Go 1.21+，无 cgo
```

其他语言可用 CLI 或 HTTP 服务，二进制内置数据，无需运行时：

```bash
docker run --rm -p 8080:8080 ghcr.io/13cohen/geotoolcn
curl 'localhost:8080/reverse?lat=39.9042&lng=116.4074'

# 或从 Releases 下载单文件二进制（linux / macOS / windows）
geotoolcn reverse 39.9042 116.4074 | jq -r .district.name
```

全部子命令、HTTP 路由与退出码约定见 [docs/CLI.md](docs/CLI.md)。

## 快速上手

### Python

```python
from GeoToolCN import GeoTool

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

模块级快捷函数使用共享的单例实例，省去手动创建 `GeoTool`：

```python
from GeoToolCN import reverse, search, get_administrative_tree

result = reverse(39.9, 116.4)
regions = search("朝阳区", province="北京市")   # 消歧：北京和长春都有朝阳区
tree = get_administrative_tree()             # 级联选择器用的三级树
```

### Node.js / TypeScript

```js
import { reverse, search, getAdministrativeTree } from "@geotoolcn/core";

const r = reverse(39.9042, 116.4074);
r.district.name;                          // 东城区
search("朝阳区", { province: "北京市" });  // 消歧
getAdministrativeTree();                  // [{ value, label, children }, ...]
```

自带 TypeScript 声明，ESM，零依赖。详见 [packages/node](packages/node/README.md)。

### Go

```go
import geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"

geo, _ := geotoolcn.New()
r := geo.Reverse(39.9042, 116.4074)
fmt.Println(r.Province.Name, r.District.Name)   // 北京市 东城区
```

数据经 `go:embed` 内嵌，`CGO_ENABLED=0` 可交叉编译。详见 [packages/go](packages/go/README.md)。

## API 参考

三种实现的 API 一一对应（Node 用驼峰命名，Go 用大写方法名），语义由 [SPEC.md](SPEC.md) 统一规定。
下面以 Python 为准。

### `GeoTool(data_dir=None)`

创建地理编码实例。默认读取内置的 `china.full.gtc`；传入一个目录（内含 `china.full.gtc`）
或直接传 `.gtc` 文件路径可使用自定义数据，见[更新数据](#更新数据)。

### `geo.reverse(lat, lng) → ReverseResult`

对单个 WGS-84 坐标进行逆地理编码。省、市、区县三级由区县的 adcode 推导，保证互相一致；
落在中国境外时三级均为 `None`。

### `geo.reverse_batch(coords) → list[ReverseResult]`

对多个 `(lat, lng)` 坐标对进行批量逆地理编码，顺序与输入一致。

### `geo.search(query, *, level=None, province=None, city=None, fuzzy=True, regex=False) → list[Region]`

按地名或 adcode 搜索。设置 `level` 为 `"province"`、`"city"` 或 `"district"` 可缩小搜索范围。使用 `province` 或 `city` 参数可消除同名区划的歧义（接受地名或 adcode）。默认开启模糊匹配（按子串）。

`regex=True` 可将查询串按正则表达式匹配 —— 这是 2.0.x 及更早版本的默认行为：

```python
geo.search("东.区")               # 0 条：按字面匹配
geo.search("东.区", regex=True)   # 18 条："." 作为正则通配符
```

```python
# "朝阳区"在北京和长春都存在
geo.search("朝阳区")                     # 返回两个结果
geo.search("朝阳区", province="北京市")    # 仅返回北京的
geo.search("朝阳区", city="长春市")        # 仅返回长春的
```

### `geo.list_regions(level) → list[Region]`

列出指定级别（`"province"`、`"city"` 或 `"district"`）的所有行政区划，按 adcode 升序。

### `geo.get_region(code) → Region | None`

按 adcode 查询单个区划，依次搜索省、市、区县，返回首个命中。

### `geo.lookup_adcode(adcode) → ReverseResult | None`

按 adcode 返回完整的省 / 市 / 区县链。

### `geo.is_in_china(lat, lng) → bool` / `geo.is_in_region(lat, lng, adcode) → bool`

包含判定。

### `get_administrative_tree() → list[dict]`

返回省→市→区县三级行政区划树。每个节点格式：`{"value": "adcode", "label": "名称", "children": [...]}`。覆盖 34 个省级单位（含台湾、香港、澳门），2874 个区县。直辖市和特别行政区的市级节点 `value` 使用省级代码。首次调用后缓存。

### 坐标转换

`wgs84_to_gcj02`、`gcj02_to_wgs84`、`gcj02_to_bd09`、`bd09_to_gcj02`、`wgs84_to_bd09`、`bd09_to_wgs84`
以及 `distance(lat1, lng1, lat2, lng2)`（球面距离，千米）。

> ⚠️ 转换函数的参数顺序是 **`(lng, lat)`**，经度在前，与 GIS 惯例一致；`reverse`、`distance` 等则是纬度在前。
> 传反了不会报错 —— 交换后的坐标落在中国范围外，函数原样返回输入。

### 数据类

```python
from dataclasses import dataclass

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

| 操作 | v2（geopandas） | v3（内置 .gtc） |
|------|----------------|----------------|
| 第三方依赖 | ~135 MB | **无** |
| 安装体积 | ~163 MB | **6.15 MB** |
| 冷启动（含 import） | ~1450 ms | **~37 ms** |
| 数据加载 | ~1200 ms | **~9 ms** |
| 单次逆编码 | ~250 μs | **~5 μs** |
| 批量 1000 点 | ~110 ms | **~5 ms** |
| 常驻内存 | ~170 MB | **~30 MB** |

v3 把空间索引预计算进内置的二进制数据文件：约 77% 的查询直接命中查找表、零几何运算，
其余平均只需对 2 个多边形做射线法判定。因此不再需要 R-tree、GEOS 或任何几何库 ——
这也是每种语言约 600 行纯标准库代码就能移植的原因。

## 测试与一致性

- **一致性套件**：`conformance/` 下 38,000+ 条语言中立的用例，覆盖 SPEC §2 的全部公开函数，
  每种实现（含已发布到 PyPI / npm / Go proxy 的版本）都必须 100% 通过
- **结构不变量**：`tests/test_invariants.py` 对全部 3271 个区划断言性质，不依赖黄金值
- **差分对拍**：`conformance/differential.py` 用 20 万随机点对照 geopandas 参考实现
- **发布后验证**：每次发布后从各自的包仓库安装，再跑一遍上述套件；每日定时重跑

如何证明测试有效：故意注入错误，看套件抓不抓得到。数字见 [PORTING.md](PORTING.md)。

## 更新数据

GeoJSON 边界数据和行政区划树使用**同一数据源**（DataV.GeoAtlas）：

```bash
python scripts/fetch_datav_geojson.py    # 下载 GeoJSON，GCJ-02 → WGS-84，生成差异报告
python pipeline/build_gtc.py             # 从 GeoJSON 构建 china.full.gtc（需要 geopandas）
python scripts/validate_gtc.py --round-trip
python conformance/generate.py           # 重新生成一致性套件，审阅 diff 后提交
```

`fetch_datav_geojson.py` 会递归下载省/市/区县边界、转换坐标系、更新 `DATA_VERSION.json`，
并生成 `DATA_UPDATE_REPORT.md` 记录与上次的差异。运行时只需要 `.gtc` 文件，
GeoJSON 是构建输入，不随包分发。

使用自定义数据：

```python
geo = GeoTool(data_dir="/path/to/china.full.gtc")
```

## 数据来源

| 字段 | 值 |
|------|-----|
| 数据源 | [DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas)（阿里云 DataV 地理小工具） |
| 覆盖范围 | 34 省 / 363 市 / 2874 区县 |
| 坐标系 | WGS-84（原始 GCJ-02 已转换） |
| 编码体系 | 6 位 adcode |
| 最近更新 | 2026 年 3 月 |

## 移植到新语言

约 600 行代码加一个适配器。契约见 [SPEC.md](SPEC.md)，步骤与验收清单见 [PORTING.md](PORTING.md)。

## 参与贡献

修 bug、改行为、更新数据、加测试各走什么流程，见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

MIT
