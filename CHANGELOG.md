# 更新日志

本文件记录 GeoToolCN 的重要变更。版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 行为变更（3.1.0，DIV-106 ~ DIV-108，见 [MIGRATION_v3.md](MIGRATION_v3.md)「3.1.0 的行为变更」）

- **`is_in_region()` 与 `reverse()` 永远一致。** SPEC §2.9 原文是「对该 adcode 的多边形做
  点在多边形判定」，3.0.0 的实现却是「区县网格首命中 == adcode」，只有省级走省多边形——
  源数据区县多边形两两重叠 2801 对，两种语义在重叠带上相反，省级还让加格达奇区
  `reverse().province=230000` 而 `is_in_region(...,"230000")=False`。SPEC 改为「等价于比较
  `reverse()` 对应层级」，三方同步。黄金集新增 300 对重叠带样本，照旧文实现的移植会失败。
- **`lookup_adcode()` 对不存在的编码返回 `None`**，不再返回半截结果（`440399` 只有省、
  `110199` 有省有市），`is not None` 可作存在性判断。
- **`search()`**：`city="北京市"` / `city="110000"` 可用（市层没有直辖市，但 `reverse()` 与
  行政树都把省当作它们的市返回）；空/空白查询返回 `[]`（以前返回全部 3271 条）；`level` 非法
  抛参数错误（以前 Python `KeyError`、Node `TypeError: undefined is not iterable`、Go 静默空）；
  非字符串 query 抛 `TypeError`；「全为数字」限定 ASCII，全角 `１１００００` 按名称匹配。
- `get_administrative_tree()` 每次返回深拷贝；`Region` / `ReverseResult` 改为 `frozen=True`，
  可哈希。
- 一致性套件 38,348 → 39,438 条；`known-divergences.yaml` 首段更正为「黄金集由 Python 实现生成，
  独立性靠差分对拍保证」。

### 修复（不改变任何一致性用例的答案）

### 修复

- **Go：几何缓存的数据竞争。** `geometryAt` 用一个普通布尔位标记"已解码"，先置位后填缓存，
  没有任何同步。多个 goroutine 同时首次访问同一多边形时，后来者会看到"已解码"但缓存槽为空
  （答成"不在此区县"）或半构造（`index out of range` panic）。`serve` 恰好就是这种用法。
  改为每条记录一个 `sync.Once`；新增 `PreloadGeometry()`，`serve` 启动时调用。
  `go test -race` 与并发对比测试进 `go test`。库文档中"除 `Reverse` 外并发安全"的说法不准确，
  已改为"并发安全"。
- **Python：`GeoTool` 无法释放资源。** `GTCData.close()` 在导出的 memoryview 未 release 时关
  mmap，必抛 `BufferError`；每个实例常驻两个文件描述符直到 GC。现在读完头就关文件，`close()`
  先 release 各视图，`GeoTool` 提供 `close()`、上下文管理器与 `__del__`；关闭后再调用抛
  `ValueError`。
- **NaN / ±Inf 坐标。** Python 抛 `ValueError: cannot convert float NaN to integer`（`reverse_batch`
  一个坏点炸整批），Go 的 `int(math.Floor(NaN))` 因平台而异。SPEC §2.1 现在规定：非有限坐标
  等于境外，返回空结果；`is_in_china` / `is_in_region` 返回 false。三方一致。
- **`distance()` 对近对跖点抛 `math domain error`**（Python）。舍入让 haversine 项略大于 1，
  `sqrt(1 - a)` 取负。改为与 Node / Go 相同的 `asin(min(1, sqrt(a)))`。
- **Python 参考实现违反 SPEC §4.6。** 网格定位用 `int()`（向零截断）而非 `floor`；原点以西/以南
  一个步长内的点会落到第 0 列/行。内置数据在那里没有格子，所以不可观测，但 Go / Node 按 SPEC
  实现，参考实现与规范不一致本身是缺陷。
- **损坏的 `.gtc`。** 截断或篡改的文件在三方分别以 `struct.error` / `KeyError`、`RangeError` /
  `TypeError`、slice-bounds panic 失败。现在打开时校验文件头长度、节表、节偏移、必需节、META
  记录数、NAMES 与 GEOM_INDEX 偏移、网格指针，统一报各语言的格式错误。`GeoTool` 新增
  `verify_checksums=` 参数透出 CRC 校验。
- **Go 的 `mini` 档静默返回空**，SPEC 要求抛错。现在以 `ErrNoGeometry` 为值 panic，与 Node 的
  `throw` 对应。
- **Go `TreeNode` 以值方式序列化时丢失 `"children":[]`**（`MarshalJSON` 是指针接收者且字段带
  `omitempty`）。改为值接收者、去掉 `omitempty`。
- **Go `Search` 在父级过滤找不到父级时返回 `nil`**，CLI / HTTP 输出 `null` 而文档承诺 `[]`。
- **Node 坐标转换收到字符串时静默做字符串拼接**（`"116.4" + 0.006` → `"116.40.006"`）。
  现在对非 `number` 参数抛 `TypeError`，与 Python 一致。
- `GTCFormatError` / `GeometryUnavailable` 从 `GeoToolCN` 顶层导出。

### CLI / HTTP 服务

- 坐标参数拒绝 `NaN` / `Inf` / 超出 ±90、±180 的值（CLI 退出码 `1`，HTTP `400`），
  不再与"境外"的空结果混为一谈。
- 只接受 `GET` / `HEAD`，其它方法 `405`；未知路径 `404`；两者都是 JSON 错误体。
  `/lookup` 缺少 `adcode` 从 `404` 改为 `400`。`/search` 与 `search` 子命令的 `level` 非法时报错。
- 加 `ReadTimeout` / `WriteTimeout` / `IdleTimeout`；`SIGTERM` / `SIGINT` 优雅退出（容器 PID 1
  以前直接以退出码 2 中断在途请求）；先绑定端口再打印"listening"。
- `search` 子命令：以 `-` 开头的查询串按放错位置的选项处理；未知选项以 JSON 报错、退出码 `1`，
  不再是 Go 的用法文本与退出码 `2`。
- `version` / `help` / `tree` / `convert` 不再加载数据集。版本号未注入时从 Go 记录的模块版本
  读取，`go install ...@v3.x.y` 的二进制不再报硬编码值。
- Dockerfile：`ARG VERSION` 注入，镜像不再永远报 `3.0.0`；改为交叉编译而非 QEMU 模拟；
  基础镜像从已停止安全更新的 Go 1.22 升到 1.26；`.dockerignore` 排除 `.env` 与 GeoJSON。

### 发布流程

- **版本号以仓库为准，tag 必须一致。** 以前 `release.yml` 从 tag 反写 `pyproject.toml` /
  `package.json`，于是 git 里那份永远不是真的（`pip install git+…@py-v3.0.0rc1` 装出来是 3.0.0）。
  新增 `scripts/release_gate.sh`：tag 不在 master 上、版本与 manifest 不一致、Go 主版本与
  `go.mod` 后缀不一致，任一情况拒绝发布。
- **发布前测产物，不测源码树。** Python 装 wheel 进干净 venv、Node 装 `npm pack` 的 tarball、
  CLI 跑刚编出的二进制，全部走 `verify_published.py --artifact`（新增），与发布后验证同一套检查。
  以前 `verify` 只在发布之后跑，只能告诉你号已经烧掉了。
- 预发布：npm 发到 `next`、GitHub Release 标 pre-release、镜像不动 `latest`。以前任何 `cli-v*`
  都覆盖 `latest`，rc 会成为 `releases/latest`。
- 镜像加 semver tag（`3.0.1` / `3.0` / `3`）与 `sha-*`；Release 附 `SHA256SUMS` 与构建证明；
  npm `--provenance`。
- 所有 action 锁到 commit SHA，`dependabot.yml` 每周更新；三个 workflow 顶层 `contents: read`。
- `verify_published.py`：`sorted(tags)[-1]` 字典序会把 `3.9.0` 排在 `3.10.0` 后、`rc1` 排在正式版后，
  改为按版本比较；Go 伪版本检测 `startswith("v0.0.0-")` 在 `/v3` 模块下恒假，改为匹配时间戳-哈希尾；
  镜像检查加版本比对。
- `pyproject.toml` 构建依赖 `setuptools>=77`（PEP 639 字符串 `license` 需要）。
- `release.yml` 删除无 job 处理的 `data-*` 触发器与在分支上无效的 `workflow_dispatch`。
- **每日守护不再静默。** 定时验证失败时开 issue（`post-release-failure` 标签），恢复后关闭；
  每次运行重新启用自身，抵消 GitHub「60 天无提交即禁用定时 workflow」的规则；`npm whoami`
  探活 `NPM_TOKEN` 并在到期前 14 天报错。README 加徽章。
- **CI 覆盖面。** Python 矩阵加 3.13 / 3.14，加 Windows 与 macOS 各一行（`pyproject.toml`
  声称 OS Independent 但从未在 Linux 之外跑过）；Node 测 18 / 20 / 22 / 24；新增 `docker` job
  在每个 PR 里按发布方式构建双平台镜像并运行 amd64（以前 Dockerfile 只在真实 tag 时首次执行）；
  所有 job 加 `timeout-minutes`；`cancel-in-progress` 只对 PR 生效，master 上每次合并保留自己的结果。
- `.gitattributes` 关闭行尾转换：Windows 上 `core.autocrlf=true` 会重写 README 的 CRLF 和翻译
  文件，让 `check_translations.py` 全红。

### 文档

- SPEC §2.1 引用的 `DIV-004` 应为 `DIV-101`。
- SPEC §4.1 补充各语言对 `mini` 档和损坏文件的报错方式。

## [3.0.0] — 2026-09-10

两件事：**Python 实现移除了 geopandas 与 shapely**，以及**同一套能力现在有了 Node.js、Go
和 CLI 三种额外形态**，全部读同一份数据文件，通过同一套 38,000+ 条一致性用例。

Python 的公开 API 没有增删。升级指南见 [MIGRATION_v3.md](MIGRATION_v3.md)。

### 新增：多语言实现

| 生态 | 安装 | 说明 |
|------|------|------|
| Node.js / TypeScript | `npm install @geotoolcn/core` | ESM，零依赖，自带 `.d.ts`；Node 18+ |
| Go | `go get github.com/13Cohen/GeoToolCN/packages/go/v3` | 无 cgo，数据 `go:embed`，`CGO_ENABLED=0` 可交叉编译 |
| CLI / HTTP | GitHub Releases 五平台二进制；`ghcr.io/13cohen/geotoolcn` 镜像（amd64 / arm64） | 覆盖没有绑定的语言。用法见 [docs/CLI.md](docs/CLI.md) |

三种实现的 API 一一对应（Node 用驼峰，Go 用大写方法名），语义由 [SPEC.md](SPEC.md) 统一规定，
每种实现约 600 行标准库代码。移植到新语言的步骤与验收清单见 [PORTING.md](PORTING.md)。

### 变更：Python 实现

| 指标 | v2.1.0 | v3.0.0 |
|------|--------|--------|
| 第三方依赖 | geopandas + shapely（约 135 MB） | **无** |
| 安装体积 | ~163 MB | **6.15 MB** |
| 冷启动（含 import） | ~1450 ms | **~37 ms** |
| 数据加载 | ~1200 ms | **~9 ms** |
| 单次 `reverse` | ~250 μs | **~5 μs** |
| 常驻内存 | ~170 MB | **~30 MB** |

空间索引改为构建期预计算进一个二进制数据文件（`.gtc`）：约 77% 的查询直接命中查找表、
零几何运算，其余平均只需对 2 个多边形做射线法判定。

- **`data_dir` 参数**现在接受 `.gtc` 文件路径或含 `china.full.gtc` 的目录，不再接受
  装有 GeoJSON 的目录。绝大多数用户不传该参数，不受影响。

- **区县空隙处的 `city` 恒为 `None`。** 数据文件保留全部 363 条地级市元数据
  （名称、代表点、层级关系），但不再保留其多边形 —— 市级归属由区县 adcode 推导。
  实测发生率约 0.023%；此时 `province` 仍正确返回。

- **边界附近的归属可能变化。** 坐标量化到 1e-5 度（约 1.11 米）。实测 16,509 个反查
  用例中 10 条（0.061%）变化，全部距争议边界 0.019 ~ 0.460 米。

- **`__version__` 改为从已安装的包元数据读取**，不再是源码里的字面量。此前的字面量与
  `pyproject.toml` 已经不一致，第一个候选版本 `3.0.0rc1` 装下来报告自己是 `2.1.0`。

- `GeoTool._levels`、`.gdf` 等私有属性随 geopandas 一并移除。

### 修复

- **`is_in_china()` 不再与 `reverse()` 互相矛盾。** v2 的 `is_in_china` 直接判省级
  多边形，而 `reverse` 由区县 adcode 反推 province，导致离岛出现
  `is_in_china=False` 却同时 `reverse().province=浙江省`。

- **区县空隙处的 `city` 不再跨省。** v2 在该情形下仍独立判定 city 图层，可能返回
  另一个省的市（如重庆市境内返回恩施州）。

- **重叠区县的归属定序。** 部分区县多边形彼此重叠，v2 取空间索引的返回顺序，
  结果依赖 GEOS 内部实现、可能随库升级漂移。现按 adcode 升序取第一个。

- **README 里的 Python 示例自 1.0.0 起就无法运行。** 每个示例都写 `from geotool_cn import`，
  而包一直只能 `import GeoToolCN`。已修正，并新增测试逐块执行 README 里的全部示例。

### 新增：契约与测试

- `SPEC.md` / `SPEC_EN.md` — 跨语言契约：API 语义、歧义规则、`.gtc` 二进制格式。
  英文版记录所译源文件的哈希，CI 在两者漂移时失败
- `conformance/` — 38,348 条语言中立用例，覆盖 SPEC §2 的**全部** 11 个公开函数；
  任何语言的实现都必须 100% 通过。`known-divergences.yaml` 登记允许的差异
- `scripts/verify_published.py` 与 `.github/workflows/post-release.yml` — 发布后从各自的
  包仓库安装，再对**装下来的东西**跑一遍套件。每次发布自动触发，每日定时重跑
- `pipeline/build_gtc.py` — 从 GeoJSON 构建 `.gtc`；`scripts/validate_gtc.py` 校验产物
- `reference/geopandas_impl.py` — geopandas 实现，保留为差分对拍的 oracle，不再发布
- `.github/workflows/release.yml` — 四个生态各自从自己的 tag 前缀发布：
  `py-v*`、`npm-v*`、`packages/go/v*`、`cli-v*`

### 发布过程中发现并修复

以下问题在打 tag 之后才暴露，均已在 `3.0.0` 正式版发布前修复，记录于此以免重蹈：

- `npm version` 在仓库版本号已等于 tag 版本时报 "Version not changed" 并退出，导致
  首次 npm 发布失败。版本注入改为幂等脚本，并加入发布前测试
- Go module 路径缺少 Go 对 v2+ 主版本强制要求的 `/v3` 后缀。本地 `go build` / `go test` /
  交叉编译全部通过，只有从 proxy `go get` 时被拒绝。被发布后验证抓到
- 一致性套件漏了 `reverse_batch`、`list_regions`、`get_region` 三个函数 —— 三个实现各自
  实现了、各自通过了单元测试，但没有任何东西保证它们彼此一致。补齐后三者确认一致

### 已知的运维约束

- npm 发布 token 于 **2026-12-09** 过期（npm 对写权限 token 强制 90 天上限）；
  **2027 年 1 月起** npm 移除 granular token 直接发布的能力，届时必须切换到
  Trusted Publishing。详见 [docs/RELEASING.md](docs/RELEASING.md)

---

## [2.1.0] — 2026-09-09

修复一批行政层级不自洽的问题。**这些修复会改变部分坐标的返回结果**，详见下方「结果变化」。

### 修复

- **离岛坐标不再返回空的 province。** 省级边界不覆盖某些离岛，而区县级覆盖，旧版会返回
  `province=None` 却同时返回 `city=舟山市` 这样自相矛盾的结果。受影响区划包括嵊泗县
  (330922)、玉环市 (331083)、重庆潼南区 (500152)、新疆博乐市 (652701) 等。

- **city 与 district 不再互相矛盾。** 数据源的 city 层与 district 层在部分边界处彼此重叠，
  同一个点会被两个市同时认领。旧版对每一层独立做点在多边形判定，于是出现
  `city=包头市` + `district=乌拉特前旗`（该旗实属巴彦淖尔市）这类结果。现在上级由区县的
  adcode 推导，层级天然自洽。同类修复还涉及苏州/嘉兴、温州/丽水、阜阳/亳州、汕尾/揭阳等边界。

- **加格达奇区 (232718) 的省份归属。** 该区行政上属黑龙江省大兴安岭地区，地理位置却在内蒙古
  自治区境内。旧版返回 `province=内蒙古自治区`，现返回 `province=黑龙江省`。

- **`lookup_adcode()` 现在能解析省直辖县级行政区。** 济源市 (419001)、仙桃市 (429004)、
  神农架林区 (429021)、海南与新疆的县级市等 30 个区划，旧版 `lookup_adcode()` 返回的
  `city` 恒为 `None`，因为 `adcode[:4] + "00"` 会算出 `419000` 这类不存在的编码。

- **`lookup_adcode()` 现在能解析不设区的地级市。** 东莞市 (441900)、中山市 (442000)、
  儋州市 (460400)、嘉峪关市 (620200) 的 `district` 字段旧版恒为 `None`，与 `reverse()`
  对同一编码的判定不一致。

- **`search(..., province=…)` 不再丢掉离岛。** 旧版用「代表点是否落在父级多边形内」做过滤，
  而离岛的代表点本就在省级边界之外，导致 `search("嵊泗县", province="浙江省")` 返回空列表。
  现改为按 adcode 归属过滤。

- **`reverse_batch()` 不再比逐个调用还慢。** 旧版对每个点执行一次全表扫描（O(n²)），1000 个点
  耗时 870 ms，而同样的点逐个调用 `reverse()` 只需 310 ms。现在 1000 个点约 110 ms。

- **`get_administrative_tree()` 不再重复挂载省直辖县级行政区。** 旧版按 adcode 前 4 位
  给市节点匹配下级，而海南 15 个县级市共用前缀 `4690`，于是每一个都被挂在全部 15 个市节点
  之下；湖北 4 个、新疆 10 个同理。树的叶子数因此虚增到 3186（实际 2874）。

- **`list_regions()` 与 `search()` 的返回按 adcode 升序。** 旧版返回 GeoJSON 文件顺序，
  该顺序几乎已是升序，仅 330114 排在 330113 之前 —— 正因差异极小，依赖它会让每个后续
  语言实现都要复现这个怪癖。

- `GeoToolCN.__version__` 此前一直停留在 `"1.0.1"`，与实际发布版本不符。

### 变更

- **`search(fuzzy=True)` 改为纯子串匹配。** 旧版底层使用 pandas `str.contains()` 的默认
  正则模式，属于未文档化的行为：`search("东.区")` 会匹配所有「东?区」形式的名称（18 条），
  而 `search("[")` 直接抛出 `re.error`。

  如需旧行为，传入 `regex=True`：

  ```python
  geo.search("东.区", regex=True)   # 18 条，与 2.0.x 一致
  geo.search("东.区")               # 0 条，按字面匹配
  ```

### 新增

- `tests/test_invariants.py` — 结构不变量测试套件。不同于逐个挑选样例的测试，它断言的是对
  **每一个**行政区划都必须成立的性质，因此单是「反查区划自身的代表点应返回该区划」一条就产生
  2874 个断言，把 adcode 覆盖率从 0.5% 提升到 100%；且不含黄金值，数据更新后不会失效。

- `.github/workflows/test.yml` — 此前仓库只有发版 workflow，测试从未在 CI 中执行过。现在
  push 与 PR 都会在 Python 3.9–3.12 上运行完整测试套件，并校验内置数据。

### 结果变化

若你的系统存储过 `reverse()` / `reverse_batch()` / `lookup_adcode()` 的历史结果，上述修复会让
少量坐标的返回值发生变化。实测在 8748 个采样点中约 0.8% 的点其 `city` 或 `province` 字段有变，
变化后的结果与行政区划树一致。建议对存量数据做一次回归比对。
