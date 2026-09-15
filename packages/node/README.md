# @geotoolcn/core

Offline geocoding for Chinese administrative divisions — every province, city and district. **Zero dependencies**, no API key, no network.

The Node.js implementation of [GeoToolCN](https://github.com/13Cohen/GeoToolCN). Shares one data file and one 38,000+-case conformance suite with the Python and Go implementations.

[中文文档在下方 ↓](#中文)

## Install

```bash
npm install @geotoolcn/core
```

Node.js ≥ 18. ESM only — `import` works everywhere; `require()` of this package needs Node ≥ 20.19 or ≥ 22.12, where `require(esm)` is supported. TypeScript declarations included.

## Usage

```js
import { reverse, search, getAdministrativeTree } from "@geotoolcn/core";

// Reverse geocoding (coordinates → divisions)
const r = reverse(39.9042, 116.4074);
r.province.name;   // 北京市
r.district.name;   // 东城区
r.district.code;   // 110101

// Forward search
search("深圳市");                        // [{ code: "440300", ... }]
search("朝阳区", { province: "北京市" }); // disambiguate: Beijing and Changchun both have one
```

The province → city → district tree, for cascader widgets:

```js
const tree = getAdministrativeTree();
// [{ value: "110000", label: "北京市", children: [...] }, ...]
```

Reuse one instance to avoid reloading the data:

```js
import { GeoTool } from "@geotoolcn/core";
const geo = new GeoTool();
```

## API

| Method | Description |
|--------|-------------|
| `reverse(lat, lng)` | Coordinate → `{ province, city, district }`; all `null` outside China |
| `reverseBatch(coords)` | Batch; takes `[[lat, lng], ...]`, output order matches input |
| `search(query, options?)` | By name or adcode. `options`: `level`, `province`, `city`, `fuzzy` |
| `listRegions(level)` | Every division at a level, ascending by adcode |
| `getRegion(code)` | One division by adcode |
| `lookupAdcode(adcode)` | adcode → the full province / city / district chain |
| `isInChina(lat, lng)` | Containment |
| `isInRegion(lat, lng, adcode)` | Containment in one division |
| `getAdministrativeTree()` | The three-level tree |

Coordinate conversions: `wgs84ToGcj02`, `gcj02ToWgs84`, `gcj02ToBd09`, `bd09ToGcj02`, `wgs84ToBd09`, `bd09ToWgs84`, and `distance`.

> ⚠️ The six conversion functions take **`(lng, lat)` — longitude first** — and return `[lng, lat]`; `distance(lat1, lng1, lat2, lng2)` and every `GeoTool` method take latitude first. Swapping them does not throw: the swapped coordinate falls outside China and is returned unchanged.

## Performance

| Operation | Time |
|-----------|------|
| Load data | ~10 ms |
| One `reverse` | ~1.3 μs |
| Package size | ~6 MB, boundaries included |

The spatial index is precomputed into the bundled binary at build time: about 77% of lookups hit a table and touch no geometry; the rest average two ray-casting tests.

## Conformance

Passes the **same** 38,000+ conformance cases as the Python and Go implementations, including an identical administrative-tree hash. The contract is [`SPEC_EN.md`](https://github.com/13Cohen/GeoToolCN/blob/master/SPEC_EN.md). After every release the published tarball is installed from npm and run against the suite again.

## Data

[DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas), converted from GCJ-02 to WGS-84. 34 provinces / 363 cities / 2874 districts.

## License

MIT

---

<a id="中文"></a>

# @geotoolcn/core（中文）

中国行政区划离线地理编码，覆盖全部省、市、区县。**零依赖**，无需 API 密钥或网络。

Node.js 上的 [GeoToolCN](https://github.com/13Cohen/GeoToolCN) 实现，与 Python 包共用同一份数据文件与一致性测试集。

## 安装

```bash
npm install @geotoolcn/core
```

## 使用

```js
import { reverse, search, getAdministrativeTree } from "@geotoolcn/core";

// 逆地理编码（坐标 → 行政区划）
const r = reverse(39.9042, 116.4074);
r.province.name;   // 北京市
r.district.name;   // 东城区
r.district.code;   // 110101

// 正向搜索
search("深圳市");                        // [{ code: "440300", ... }]
search("朝阳区", { province: "北京市" }); // 消歧
```

行政区划树，适用于级联选择器：

```js
const tree = getAdministrativeTree();
// [{ value: "110000", label: "北京市", children: [...] }, ...]
```

复用同一实例可避免重复加载数据：

```js
import { GeoTool } from "@geotoolcn/core";
const geo = new GeoTool();
```

## API

| 方法 | 说明 |
|------|------|
| `reverse(lat, lng)` | 坐标 → `{ province, city, district }` |
| `reverseBatch(coords)` | 批量，入参 `[[lat, lng], ...]` |
| `search(query, options?)` | 按名称或 adcode 搜索 |
| `listRegions(level)` | 列出某级全部区划，按 adcode 升序 |
| `getRegion(code)` | 按 adcode 查单个区划 |
| `lookupAdcode(adcode)` | adcode → 完整省市区链 |
| `isInChina(lat, lng)` | 是否在中国境内 |
| `isInRegion(lat, lng, adcode)` | 是否在指定区划内 |
| `getAdministrativeTree()` | 省→市→区县三级树 |

坐标转换：`wgs84ToGcj02`、`gcj02ToWgs84`、`gcj02ToBd09`、`bd09ToGcj02`、`wgs84ToBd09`、`bd09ToWgs84`，以及 `distance`。

> ⚠️ 六个转换函数取 **`(lng, lat)`，经度在前**，返回 `[lng, lat]`；而 `distance(lat1, lng1, lat2, lng2)` 与所有 `GeoTool` 方法是纬度在前。传错顺序不会报错 —— 交换后的经度落在中国范围外，函数按「境外坐标原样返回」把输入原样返回。

## 性能

| 操作 | 耗时 |
|------|------|
| 加载数据 | ~10 ms |
| 单次 `reverse` | ~1.3 μs |
| 包体积 | ~6 MB（含全部边界数据） |

空间索引在构建期预计算进内置的二进制数据文件：约 77% 的查询直接命中查找表、零几何运算，其余平均只需对 2 个多边形做射线法判定。

## 一致性

本实现通过与 Python 参考实现**完全相同**的 38,000+ 条一致性用例。契约见仓库中的 [`SPEC.md`](https://github.com/13Cohen/GeoToolCN/blob/master/SPEC.md)。

## 环境要求

Node.js ≥ 18。纯 ESM 包：`import` 在任何版本可用；`require()` 需要 Node ≥ 20.19 或 ≥ 22.12（支持 `require(esm)` 的版本）。

## 数据来源

[DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas)，GCJ-02 已转换为 WGS-84。

## License

MIT
