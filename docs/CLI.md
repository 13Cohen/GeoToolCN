# geotoolcn 命令行与 HTTP 服务

> [English](CLI_EN.md)

一个静态二进制，内置全部数据，覆盖没有语言绑定的场景：shell 脚本、PHP / Ruby / Java /
C# 等任何能发 HTTP 请求或起子进程的环境。它是 [Go 实现](../packages/go/README.md)的薄封装，
输出与 Python、Node、Go 三个库完全一致。

## 安装

**下载二进制**（[Releases](https://github.com/13Cohen/GeoToolCN/releases)，tag 前缀 `cli-v`）：

| 平台 | 文件 |
|------|------|
| Linux x86-64 / ARM64 | `geotoolcn-linux-amd64` / `geotoolcn-linux-arm64` |
| macOS Intel / Apple Silicon | `geotoolcn-darwin-amd64` / `geotoolcn-darwin-arm64` |
| Windows x86-64 | `geotoolcn-windows-amd64.exe` |

```bash
curl -Lo geotoolcn https://github.com/13Cohen/GeoToolCN/releases/latest/download/geotoolcn-linux-amd64
chmod +x geotoolcn
```

**容器镜像**（`linux/amd64`、`linux/arm64`，基于 `scratch`，约 18 MB）：

```bash
docker run --rm -p 8080:8080 ghcr.io/13cohen/geotoolcn            # 起 HTTP 服务
docker run --rm ghcr.io/13cohen/geotoolcn reverse 39.9042 116.4074   # 或直接跑子命令
```

**从源码**（需要 Go 1.21+，无需 cgo）：

```bash
go install github.com/13Cohen/GeoToolCN/packages/go/v3/cmd/geotoolcn@latest
```

## 约定

所有子命令**输出 JSON 到 stdout**，两空格缩进，非 ASCII 不转义，便于直接 `| jq`。

出错时 **stdout 保持为空**，错误以 JSON 写到 stderr：`{"error":"..."}`。
这保证 `geotoolcn ... | jq` 永远不会吃到半截结果。

退出码：

| 码 | 含义 |
|----|------|
| `0` | 成功 |
| `1` | 运行时失败：坐标无法解析、adcode 不存在、转换不支持 |
| `2` | 用法错误：缺少子命令、未知子命令 |

## 子命令

### `reverse <lat> <lng>`

坐标 → 省 / 市 / 区县。**纬度在前。**

```bash
$ geotoolcn reverse 39.9042 116.4074
{
  "province": { "name": "北京市", "code": "110000", "level": "province", "latitude": 40.2481, "longitude": 116.632868 },
  "city":     { "name": "北京市", "code": "110000", "level": "city",     "latitude": 40.2481, "longitude": 116.632868 },
  "district": { "name": "东城区", "code": "110101", "level": "district", "latitude": 39.917839, "longitude": 116.416357 }
}

$ geotoolcn reverse 39.9042 116.4074 | jq -r .district.name
东城区
```

境外坐标三级均为 `null`，退出码仍为 `0`（这是一个合法答案，不是错误）：

```bash
$ geotoolcn reverse 0 0
{ "province": null, "city": null, "district": null }
```

### `lookup <adcode>`

adcode → 完整层级链。与 `reverse` 输出同构。

```bash
$ geotoolcn lookup 419001            # 济源市：省直辖县级市，city 即自身
{
  "province": { "name": "河南省", "code": "410000", ... },
  "city":     { "name": "济源市", "code": "419001", ... },
  "district": { "name": "济源市", "code": "419001", ... }
}

$ geotoolcn lookup 999999
{"error":"未找到 adcode \"999999\""}      # → stderr，退出码 1
```

### `search <query> [--level L] [--province P] [--city C] [--exact]`

按名称或 adcode 搜索。**`<query>` 必须是第一个参数**，标志跟在后面。

| 标志 | 说明 |
|------|------|
| `--level` | 限定 `province` / `city` / `district` |
| `--province` | 限定省份，接受名称或 adcode |
| `--city` | 限定城市，接受名称或 adcode |
| `--exact` | 关闭子串模糊匹配 |

```bash
$ geotoolcn search 朝阳区                          # 北京和长春各一个
$ geotoolcn search 朝阳区 --province 北京市         # 只要北京的
$ geotoolcn search 深圳 --exact                    # 精确匹配 "深圳"：0 条（全名是"深圳市"）
$ geotoolcn search 440300                          # 按 adcode
```

查询串按**字面**匹配，`.`、`*`、`[` 等不是通配符。无结果时输出 `[]`（不是 `null`），退出码 `0`。

### `tree`

省 → 市 → 区县三级树，适用于级联选择器。

```bash
$ geotoolcn tree | jq '.[0]'
{
  "value": "110000",
  "label": "北京市",
  "children": [
    { "value": "110000", "label": "北京市", "children": [ { "value": "110101", "label": "东城区" }, ... ] }
  ]
}
```

省、市节点始终有 `children`（可为空数组）；区县节点没有该字段。
直辖市与特别行政区的市级节点 `value` 使用省级代码。34 个省级单位，2874 个区县。

### `convert <from> <to> <lng> <lat>`

坐标系转换。`from` / `to` 取 `wgs84` / `gcj02` / `bd09`，不区分大小写。

> ⚠️ **经度在前**，与 GIS 惯例一致；`reverse` 则是纬度在前。传反了不会报错 ——
> 交换后的坐标落在中国范围外，函数原样返回输入。

```bash
$ geotoolcn convert wgs84 gcj02 116.4074 39.9042
{ "lng": 116.41364225378803, "lat": 39.90560334316507 }
```

支持全部六个方向。`wgs84 → wgs84` 这类同系转换不支持，退出码 `1`。

### `serve [--addr :8080]`

起 HTTP 服务，见下一节。路由列表打印到 stderr，stdout 保持干净。

### `version` / `help`

`version` 输出 `{"version": "3.0.0"}`；`help` 输出用法。`--version`、`-v`、`--help`、`-h` 是别名。

## HTTP 服务

```bash
geotoolcn serve --addr :8080
```

所有响应 `Content-Type: application/json; charset=utf-8`，非 ASCII 不转义。
只支持 `GET`。

| 路由 | 参数 | 成功 | 失败 |
|------|------|------|------|
| `/reverse` | `lat`、`lng` | `200` ReverseResult | `400` 参数缺失或非数值 |
| `/lookup` | `adcode` | `200` ReverseResult | `404` 不存在 |
| `/search` | `q`；可选 `level`、`province`、`city`、`exact=1` | `200` Region[] | `400` 缺少 `q` |
| `/regions` | `level` | `200` Region[] | `400` level 非法 |
| `/tree` | — | `200` TreeNode[] | — |
| `/healthz` | — | `200` `{"status":"ok","version":"…"}` | — |

失败响应体为 `{"error":"..."}`。

```bash
$ curl 'localhost:8080/reverse?lat=39.9042&lng=116.4074' | jq -r .district.name
东城区

$ curl 'localhost:8080/search?q=朝阳区&province=北京市'
[{"name":"朝阳区","code":"110105","level":"district","latitude":39.948547,"longitude":116.530723}]

$ curl -i 'localhost:8080/lookup?adcode=999999'
HTTP/1.1 404 Not Found
{"error":"未找到 adcode \"999999\""}
```

中文参数需要 URL 编码（`curl` 会自动处理，多数 HTTP 客户端也会；手写 URL 时注意）。

### 部署提示

- 服务无状态，数据只读，可任意水平扩展；每个实例常驻内存约 30 MB
- `ReadHeaderTimeout` 为 5 秒，其余超时未设置 —— 放在反向代理后面时由代理控制
- 镜像以 `nobody`（uid 65534）运行，基于 `scratch`，没有 shell；调试请用 `docker run ... reverse ...` 直接跑子命令
- `/healthz` 用于就绪探针

## 与库的关系

CLI 直接调用 Go 库，没有自己的逻辑。库通过与 Python、Node 实现相同的 38,000+ 条一致性用例；
CLI 的测试（`packages/go/cmd/geotoolcn/main_test.go`）把每个子命令和路由的输出与库的返回值
逐字段比对，因此三者的答案总是一致的。

每次发布后 `scripts/verify_published.py` 会下载 Release 里的二进制和 GHCR 镜像，
把上面所有子命令和路由各跑一遍。
