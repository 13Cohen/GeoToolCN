# geotoolcn-go

中国行政区划离线地理编码，覆盖全部省、市、区县。**纯 Go，无 cgo，零依赖**，数据内嵌。

Go 版 [GeoToolCN](https://github.com/13Cohen/GeoToolCN) 实现，与 Python、Node 实现共用同一份数据文件与一致性测试集。

## 安装

```bash
go get github.com/13Cohen/geotoolcn-go
```

## 使用

```go
package main

import (
    "fmt"

    geotoolcn "github.com/13Cohen/geotoolcn-go"
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

`GeoTool` 在 `New` 返回后可并发读取，但 `Reverse` 会惰性解码几何 —— 高并发下请每个
goroutine 持有一个实例，或自行加锁。

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

本实现通过与 Python、Node 实现**完全相同**的 35,000+ 条一致性用例，包括同一个行政区划树哈希。契约见 [`SPEC.md`](https://github.com/13Cohen/GeoToolCN/blob/master/SPEC.md)。

## 数据来源

[DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas)，GCJ-02 已转换为 WGS-84。

## License

MIT
