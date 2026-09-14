# geotoolcn (Go)

Offline geocoding for Chinese administrative divisions — every province, city and district. **Pure Go, no cgo, zero dependencies**, data embedded.

The Go implementation of [GeoToolCN](https://github.com/13Cohen/GeoToolCN). Shares one data file and one 38,000+-case conformance suite with the Python and Node implementations.

[中文文档在下方 ↓](#中文)

## Install

```bash
go get github.com/13Cohen/GeoToolCN/packages/go/v3
```

Both suffixes in the import path are mandatory and have different origins:

- `packages/go` — the module lives in a subdirectory of a monorepo. Go resolves modules straight from git, so the path is the repository path.
- `/v3` — Go requires the import path to end in `/vN` from major version 2 onwards. **Omitting it does not fail `go build` or `go test`** — only other people's `go get` from the proxy rejects it, which is how this repository came to tag an unfetchable release once.

The package name is still `geotoolcn`:

```go
import geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"
```

## Usage

```go
package main

import (
    "fmt"

    geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"
)

func main() {
    geo, err := geotoolcn.New()
    if err != nil {
        panic(err)
    }

    r := geo.Reverse(39.9042, 116.4074)
    fmt.Println(r.Province.Name, r.District.Name) // 北京市 东城区

    // Disambiguate same-named divisions
    found := geo.Search("朝阳区", geotoolcn.SearchOptions{Province: "北京市"})
    fmt.Println(found[0].Code) // 110105

    tree, _ := geotoolcn.GetAdministrativeTree()
    fmt.Println(len(tree)) // 34
}
```

A `GeoTool` is safe for concurrent use from any number of goroutines once `New` or `Open` returns. Geometry is decoded lazily, one region at a time, and each decode is guarded so concurrent first requests for the same polygon wait on one decode rather than race. A long-running server can call `PreloadGeometry()` once at start-up to take the whole ~1M-vertex parse (~100–200 ms) up front instead of as a stall on the first request to each region.

`Reverse`, `ReverseBatch`, `IsInChina` and `IsInRegion` panic with `ErrNoGeometry` on a dataset that carries no geometry (the `mini` tier); the other methods work on any tier.

## API

| Method | Description |
|--------|-------------|
| `New()` / `Open(path)` | Embedded data / an external `.gtc` |
| `Reverse(lat, lng)` | Coordinate → `ReverseResult{Province, City, District}`; all nil outside China |
| `ReverseBatch(coords)` | Batch; takes `[][2]float64{{lat, lng}, ...}` |
| `Search(query, opts)` | By name or adcode |
| `ListRegions(level)` | Every division at a level, ascending by adcode; error on an invalid level |
| `GetRegion(code)` | One division by adcode |
| `LookupAdcode(adcode)` | adcode → the full chain |
| `IsInChina(lat, lng)` | Containment |
| `IsInRegion(lat, lng, adcode)` | Containment in one division; error if the adcode is invalid or unknown |
| `GetAdministrativeTree()` | The three-level tree |

Coordinate conversions: `WGS84ToGCJ02`, `GCJ02ToWGS84`, `GCJ02ToBD09`, `BD09ToGCJ02`, `WGS84ToBD09`, `BD09ToWGS84`, and `Distance`.

> ⚠️ The six conversion functions take **`(lng, lat)` — longitude first**; `Distance(lat1, lng1, lat2, lng2)` and every `GeoTool` method take latitude first. Swapping them does not error: the swapped coordinate falls outside China and is returned unchanged.

The zero value of `SearchOptions` means "every level, fuzzy on". `NoFuzzy` is named in the negative precisely so the zero value matches the other implementations' `fuzzy=true` default.

## Performance

| Operation | Time |
|-----------|------|
| `New()` | ~30 ms |
| One `Reverse` | **155 ns** |
| Binary size | ~9.7 MB, boundaries included |

The spatial index is precomputed into the embedded binary at build time: about 77% of lookups hit a table and touch no geometry; the rest average two ray-casting tests.

## Cross-compilation

No cgo, so it cross-compiles with `CGO_ENABLED=0`:

```bash
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build ./...
```

## Conformance

Passes the **same** 38,000+ conformance cases as the Python and Node implementations, including an identical administrative-tree hash. The contract is [`SPEC_EN.md`](https://github.com/13Cohen/GeoToolCN/blob/master/SPEC_EN.md). After every release the module is fetched from the proxy and run against the suite again.

## Versioning

A release is a tag — there is no registry to upload to; the Go proxy resolves git tags directly. For a module in a subdirectory Go dictates the tag shape:

```
packages/go/v3.0.0
```

`data/china.full.gtc` is **committed** because `go get` fetches only what git holds and `go:embed` cannot reach outside the module directory. It is the one duplicated copy of the dataset in the repository.

## CLI and HTTP server

`cmd/geotoolcn` in this module is a static binary exposing the same API as subcommands and as an HTTP service, for languages with no binding. See [docs/CLI_EN.md](https://github.com/13Cohen/GeoToolCN/blob/master/docs/CLI_EN.md).

## Data

[DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas), converted from GCJ-02 to WGS-84. 34 provinces / 363 cities / 2874 districts.

## License

MIT

---

<a id="中文"></a>

# geotoolcn (Go)（中文）

中国行政区划离线地理编码，覆盖全部省、市、区县。**纯 Go，无 cgo，零依赖**，数据内嵌。

Go 版 [GeoToolCN](https://github.com/13Cohen/GeoToolCN) 实现，与 Python、Node 实现共用同一份数据文件与一致性测试集。

## 安装

```bash
go get github.com/13Cohen/GeoToolCN/packages/go/v3
```

导入路径里的两段后缀各有来历，都不能省：

- `packages/go` —— 本模块位于 monorepo 子目录。Go module 从 git 直接解析，路径即仓库路径。
- `/v3` —— Go 从主版本 2 起要求导入路径以 `/vN` 结尾。**省掉它不会在 `go build` 或
  `go test` 时报错**，只有别人从 proxy `go get` 时才会被拒绝，所以本仓库确实先打出过一个
  这样的无效 tag 才发现。

包名仍是 `geotoolcn`：

```go
import geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"
```

## 使用

```go
package main

import (
    "fmt"

    geotoolcn "github.com/13Cohen/GeoToolCN/packages/go/v3"
)

func main() {
    geo, err := geotoolcn.New()
    if err != nil {
        panic(err)
    }

    r := geo.Reverse(39.9042, 116.4074)
    fmt.Println(r.Province.Name, r.District.Name) // 北京市 东城区

    // 同名区划消歧
    found := geo.Search("朝阳区", geotoolcn.SearchOptions{Province: "北京市"})
    fmt.Println(found[0].Code) // 110105

    tree, _ := geotoolcn.GetAdministrativeTree()
    fmt.Println(len(tree)) // 34
}
```

`GeoTool` 在 `New` / `Open` 返回后可被任意数量的 goroutine 并发使用。几何按区划惰性解码，
每个区划的解码有同步保护：同一多边形的并发首次请求会等待同一次解码，而不是互相竞争。
常驻服务可以在启动时调用一次 `PreloadGeometry()`，把约 100 万顶点的解析（约 100–200 ms）
一次付清，避免每个区划首次被访问时的停顿。

`Reverse` / `ReverseBatch` / `IsInChina` / `IsInRegion` 在没有几何的数据集（`mini` 档）上
以 `ErrNoGeometry` 为值 panic；其余方法在任何档位都可用。

## API

| 方法 | 说明 |
|------|------|
| `New()` / `Open(path)` | 使用内嵌数据 / 外部 `.gtc` |
| `Reverse(lat, lng)` | 坐标 → `ReverseResult{Province, City, District}` |
| `ReverseBatch(coords)` | 批量，入参 `[][2]float64{{lat, lng}, ...}` |
| `Search(query, opts)` | 按名称或 adcode 搜索 |
| `ListRegions(level)` | 列出某级全部区划，按 adcode 升序 |
| `GetRegion(code)` | 按 adcode 查单个区划 |
| `LookupAdcode(adcode)` | adcode → 完整省市区链 |
| `IsInChina(lat, lng)` | 是否在中国境内 |
| `IsInRegion(lat, lng, adcode)` | 是否在指定区划内；adcode 非法或不存在时返回 error |
| `GetAdministrativeTree()` | 省→市→区县三级树 |

坐标转换：`WGS84ToGCJ02`、`GCJ02ToWGS84`、`GCJ02ToBD09`、`BD09ToGCJ02`、`WGS84ToBD09`、`BD09ToWGS84`，以及 `Distance`。

> ⚠️ 六个转换函数取 **`(lng, lat)`，经度在前**；而 `Distance(lat1, lng1, lat2, lng2)` 与所有 `GeoTool` 方法是纬度在前。传错顺序不会报错 —— 交换后的经度落在中国范围外，函数按「境外坐标原样返回」把输入原样返回。

`SearchOptions` 的零值等价于「搜索全部层级、开启模糊匹配」。`NoFuzzy` 之所以取反命名，正是为了让零值保持与其他实现一致的 `fuzzy=true` 默认。

## 性能

| 操作 | 耗时 |
|------|------|
| `New()` | ~30 ms |
| 单次 `Reverse` | **155 ns** |
| 二进制体积 | ~9.7 MB（含全部边界数据） |

空间索引在构建期预计算进内嵌的二进制数据文件：约 77% 的查询直接命中查找表、零几何运算，其余平均只需对 2 个多边形做射线法判定。

## 交叉编译

不使用 cgo，因此 `CGO_ENABLED=0` 下可直接交叉编译：

```bash
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build ./...
```

## 一致性

本实现通过与 Python、Node 实现**完全相同**的 38,000+ 条一致性用例，包括同一个行政区划树哈希。契约见 [`SPEC.md`](https://github.com/13Cohen/GeoToolCN/blob/master/SPEC.md)。

## 版本

发布即打 tag，无需上传任何 registry —— Go proxy 直接解析 git tag。子目录 module 的 tag
形式由 Go 规定：

```
packages/go/v3.0.0
```

数据文件 `data/china.full.gtc` **随仓库提交**，因为 `go get` 只能拿到 git 里的内容，
而 `go:embed` 无法引用模块目录之外的文件。这也是本仓库唯一一份重复存放的数据。

## 数据来源

[DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas)，GCJ-02 已转换为 WGS-84。

## License

MIT
