# RFC-001：GeoToolCN 多语言支持方案

> 状态：草案 · 日期：2026-09-09 · 作者：Cohen
> 目标：把 GeoToolCN 从「一个 Python 库」变成「一份跨语言可用的中国行政区划离线地理编码能力」

---

## 1. 现状与问题

| 维度 | 现状 | 问题 |
|------|------|------|
| 语言覆盖 | 仅 Python（PyPI `geotool-cn`） | TS/JS、Go、Java、Rust 用户无法使用 |
| 依赖 | `geopandas>=0.14` + `shapely>=2` | 安装体积约 120MB，含 GEOS C 扩展；Serverless / 边缘 / 浏览器环境难以落地 |
| 数据 | 28MB GeoJSON 直接打包 | 体积大、解析慢（每次冷启动约 2s），不适合按包分发到 npm / Go module |
| 逻辑复用 | 算法与 Python/GeoPandas 强耦合 | 换语言 = 从零重写，且行为无法保证一致 |

**核心判断**：这个项目真正的资产是**数据 + 行政区划语义规则**，而不是 Python 代码。
只要把资产做成语言中立的产物，各语言的运行时可以做得非常薄。

---

## 2. 三个实测事实（决定了架构选择）

以下数字均在当前仓库数据（DataV 2026-03，34 省 / 363 市 / 2874 区县）上实测得出，不是估算。

### 事实 1：city 层几何数据是冗余的

adcode 的前 4 位即可从区县推出地级市，前 2 位推出省。反查只需 **district + province 两层**多边形
（province 用于台湾、海域、区县数据缺口的兜底）。

```
现状  province 24,950 + city 140,494 + district 987,927 = 1,153,371 顶点
方案  province 24,950 +                district 987,927 = 1,012,877 顶点   (-12%，且逻辑更简单)
```

### 事实 2：数据可以压到 1/8，且几何简化不是正确的杠杆

定点量化 + zigzag varint 差分编码，实测（province + district）：

| 精度 | 含义 | 原始 | gzip |
|------|------|------|------|
| 1e-6 | 约 0.1 m | 4.24 MB | 4.07 MB |
| **1e-5** | **约 1 m** | **3.71 MB** | **3.22 MB** |
| **1e-4** | **约 10 m** | **2.50 MB** | **2.20 MB** |

对比现状 28 MB GeoJSON，**缩小 8～12 倍**。

反直觉的一点：**Douglas-Peucker 几何简化几乎没用**——100 m 容差只减少 24% 顶点
（987,927 → 746,516），50 m 容差只减 8%。因为 DataV 数据的顶点密度本身已经比较合理。
**降低坐标精度（量化）才是真正的杠杆，几何简化不是。**

### 事实 3：空间索引可以预计算成一张查找表，运行时不需要 R-tree

对区县层建规则网格，实测两种粒度：

| 网格 | 单元大小 | 总格数 | 空格 | 实心格（直接出答案） | 混合格（需判定） | 非空格中实心占比 | 混合格平均候选 |
|------|---------|--------|------|---------------------|-----------------|----------------|--------------|
| 0.1° | ~11×9 km | 321,300 | 69% | 58,759 (18%) | 39,620 (12%) | 59.7% | 2.13 |
| **0.05°** | **~5.5×4.5 km** | 1,285,200 | 70% | 298,517 (23%) | 90,814 (7%) | **76.7%** | **2.00** |

**推荐 0.05°**：约 77% 的查询直接查表命中、零几何运算；剩余 23% 平均只需对 **2 个**多边形
做射线法判定。也就是说运行时根本不需要 R-tree、不需要 GEOS、不需要任何几何库。

> 索引本身很小：空格占 70% 不存储；实心格按行做行程编码；混合格用稀疏
> `(cell_id → 候选列表)` varint 编码。0.05° 网格实测约 90,814 混合格 × 2 候选，
> 索引合计约 600 KB（gzip 后更小）。0.1° 网格约 300 KB，可作为 `lite` 档的选择。

### 结论

> **把全部复杂度前移到构建期。运行时只剩「哈希查表 + 2～3 次射线法」，
> 小到每种语言都能用纯原生代码写完，约 500–800 行，零第三方依赖。**

这个结论直接决定了下面的架构选型（见 §5：为什么不选 Rust core + FFI）。

---

## 3. 架构：三层 + 一个契约

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1  数据构建管线（Python，构建期，仓库内，不分发）        │
│   DataV 抓取 → GCJ-02→WGS-84 → 校验 → 量化 → 建网格索引       │
│                          ↓                                   │
│              产出 .gtc 二进制（mini / lite / full）            │
├─────────────────────────────────────────────────────────────┤
│ Layer 2  GTC 二进制格式 —— 语言中立契约（SPEC.md）             │
│   mmap 友好 / 小端 / 分节 / 带校验和 / 格式版本号              │
├─────────────────────────────────────────────────────────────┤
│ Layer 3  各语言瘦运行时（每种约 500–800 行，零依赖）           │
│   Python · TS/JS · Go · Rust · Java · C# · …                 │
├─────────────────────────────────────────────────────────────┤
│ 横切：conformance/ 语言无关黄金测试集（所有实现必须 100% 通过） │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 GTC 二进制格式（草案）

小端、8 字节对齐、可 mmap：

```
Header (32B)
  magic       "GTCN"      4B
  format_ver  u16                  运行时拒绝不兼容的大版本
  dataset     u8                   0=mini 1=lite 2=full
  precision   u8                   量化指数（4 或 5）
  data_ver    u32                  数据日历版本，如 20260307
  section_cnt u16
  reserved

Section Table  [ type u16 | offset u64 | length u64 | crc32 u32 ] × N

Sections
  META    区划表：adcode u32 / level u8 / parent u32 / name_ref u32 / center(量化 lng,lat)
  NAMES   名称字符串池 + 按名称排序的索引数组（二分查找）+ 2-gram 倒排（模糊搜索）
  GEOM    每区划：[环数][每环：点数 + zigzag varint 差分点对] + 预计算 bbox
  GRID    网格：原点 / 步长 / 宽高 + 实心格行程编码 + 混合格稀疏候选表
```

行政区划树不单独存储，由 META 在运行时构建（现有 `admin_tree.py` 逻辑）。

### 3.2 三档数据集

| 档位 | 内容 | 文件体积 | gzip 后 | 典型用途 |
|------|------|---------|---------|---------|
| `mini` | META + NAMES，无几何 | **0.13 MB** | ~60 KB | 级联选择器、adcode 查询、名称搜索、坐标转换。浏览器首选 |
| `lite` | + 1e-4 几何（约 10 m）+ 0.1° 网格 | **3.58 MB** | ~1.6 MB | 绝大多数业务反查 |
| `full` | + 1e-5 几何（约 1 m）+ 0.05° 网格 | **5.95 MB** | **~2.6 MB** | 需要边界精度的场景（默认） |

> `full` 的 5.95 MB 为**实测值**：几何 3.76 MB + 区县网格 1.74 MB + 省级网格 0.33 MB。
> 省级网格是实现阶段追加的——台湾只有省级边界，缺了它全岛都会被判为境外。
> 索引采用「定宽行程编码」，是体积与加载速度的折中——详见 §11.3。

---

## 4. 各语言分发形态

| 语言 | 包 | 分发方式 | 关键收益 |
|------|-----|---------|---------|
| **Python** | `geotool-cn` v3 | PyPI，纯 Python（numpy 可选加速） | **移除 geopandas/shapely**，安装体积 ~120MB → ~4MB，冷启动 2s → <100ms |
| **TS/JS** | `@geotoolcn/core` + `@geotoolcn/data-{mini,lite,full}` | npm，ESM + CJS | 零依赖；Node 18+ / Deno / Bun / 浏览器 / Cloudflare Workers 全覆盖；数据分包按需装 |
| **Go** | `github.com/13Cohen/GeoToolCN/packages/go`（`go:embed` 内嵌数据） | Go module（git tag） | **纯 Go，无 cgo**，`CGO_ENABLED=0` 可交叉编译 |
| **Rust** | `geotoolcn` | crates.io | 后续；同时作为可选 WASM 加速包的源 |
| **Java / Kotlin** | Maven Central | 后续 / 社区 | |
| **C# / .NET** | NuGet | 后续 / 社区 | |
| **长尾**（PHP / Ruby / Elixir / Shell…） | `geotoolcn` CLI 单文件二进制 + Docker | GitHub Releases + GHCR | `geotoolcn serve` 起本地 HTTP 服务；`geotoolcn reverse 39.9 116.4` 管道调用 |

数据分发独立于代码：`.gtc` 产物发到 GitHub Releases（带 SHA256），各语言包内 pin 一个数据版本，
同时支持运行时指定外部 `.gtc` 路径（替代现有的 `data_dir` 参数）。

### 统一 API 契约

各语言按自身命名惯例调整大小写，语义必须完全一致：

```
reverse(lat, lng)                  -> ReverseResult{province, city, district}
reverseBatch(coords)               -> ReverseResult[]
search(query, {level, province, city, fuzzy}) -> Region[]
listRegions(level)                 -> Region[]
getRegion(code)                    -> Region | null
lookupAdcode(adcode)               -> ReverseResult | null
isInChina(lat, lng)                -> bool
isInRegion(lat, lng, adcode)       -> bool
getAdministrativeTree()            -> TreeNode[]
wgs84ToGcj02 / gcj02ToWgs84 / gcj02ToBd09 / bd09ToGcj02 / wgs84ToBd09 / bd09ToWgs84
distance(lat1, lng1, lat2, lng2)
```

即当前 Python v2 的公开 API 全集——**不新增、不删减**，保证 Python 用户零成本升级。

---

## 5. 为什么不选「Rust core + FFI 绑定」

这是最直接的备选方案（PyO3 + napi-rs + cgo + wasm-bindgen），需要明确说明为何不选。

**它的优势是真实的**：单一实现、无逻辑重复、性能最好。

**但代价在本项目上不划算**：

1. **Go 会被迫用 cgo** —— 破坏交叉编译，`CGO_ENABLED=0` 不可用，Go 社区对此高度排斥。
   一个「离线地理编码库」要求用户装 C 工具链，基本等于劝退。
2. **浏览器体验差** —— 需要加载 3MB wasm + 3MB 数据。而纯 TS 实现只需加载数据。
3. **预编译产物矩阵爆炸** —— 每个语言 × OS × arch × ABI（glibc/musl）都要出包，
   ARM、musl、FreeBSD 这些长尾的维护成本长期存在。
4. **社区贡献门槛陡增** —— 有人想加 Java 或 C# 支持时，要面对 JNI/P-Invoke，而不是写 600 行纯代码。
5. **性能优势在本场景无意义** —— 见 §2 事实 3，运行时只有查表 + 2～3 次射线法。
   Rust 相对纯 Go/纯 TS 的差距在「约 10μs vs 约 50μs」量级，对业务毫无影响。

**折中路径（保留后路）**：先做各语言原生实现。若日后「百万点级批量反查」成为真实瓶颈，
再补一个**可选**的 Rust/WASM 加速包——它共用同一份 `.gtc` 和同一套 conformance，
属于纯增量，不影响主线架构。

---

## 6. 一致性保障（本方案成败的关键）

多语言项目最容易死在「各实现行为悄悄漂移」。对策是两件事：**SPEC 钉死歧义** + **黄金测试集强制**。

### 6.1 SPEC.md 必须明确规定的歧义点

| 歧义点 | 规定 |
|--------|------|
| 点落在多边形边界上 | 射线法 + on-edge 一律视为 **inside** |
| 混合格多候选命中 | 按 **adcode 升序**遍历，取第一个 contains 的结果 |
| 量化取整 | **round-half-away-from-zero**。⚠️ Python 的 `round()` 是 banker's rounding，JS 的 `Math.round` 是 half-up——不钉死必然产生跨语言差异 |
| 模糊搜索 | 先精确匹配；无结果时才做 substring 包含匹配 |
| 搜索结果排序 | 先按 level（province < city < district），再按 adcode 升序 |
| 直辖市 / 特别行政区 | 前缀 `11 12 31 50 81 82` 的 city 由 province 派生，`level` 字段置为 `"city"`（沿用现有 v2 行为，见 `MIGRATION_v2.md`） |
| 坐标转换边界 | `_out_of_china` 的 bbox 判定阈值逐位对齐 |

### 6.2 conformance/ 黄金测试集（语言无关 JSON）

```
conformance/
├── reverse.jsonl      20,000 个坐标 → 期望的 province/city/district adcode 链
│                      含：随机采样 + 边界密集采样 + 飞地 / 海岛 / 境外 / 直辖市专项
├── lookup.jsonl       adcode → 期望层级链
├── search.jsonl       查询串 + 参数 → 期望结果序列（含同名区县歧义用例）
├── coords.jsonl       坐标转换往返用例，带容差
├── containment.jsonl  isInChina / isInRegion
└── tree.sha256        行政区划树的规范化 JSON 哈希
```

由 Python 参考实现生成，人工抽检关键用例。

**准入门槛**：任何语言实现要进主仓 / 被官方列出，必须
（a）100% 通过 conformance，（b）在 CI 矩阵中有对应 job。

---

## 7. 工程形态：多语言到底是怎么组织和发布的

这是最容易误解的一节，先排除三种常见猜测：

- ❌ **不是开多个 git 分支**
- ❌ **不是转译 / 编译**（不存在 Python → Go/TS 的自动转换）
- ✅ **是一个 monorepo，每种语言一个目录，各自发布到各自的包管理器**

### 7.1 什么是共享的，什么是重写的

**代码不共享，数据和契约共享。** 这是理解整个方案的关键：

| 产物 | 来源 | 是否每语言重复 |
|------|------|--------------|
| `.gtc` 数据文件（约 3.7 MB） | 构建管线生成一次 | ❌ 所有语言用同一个二进制文件 |
| `SPEC.md` 行为规范 | 人写一次 | ❌ |
| `conformance/` 测试集（2 万用例） | 生成一次 | ❌ 所有语言跑同一套 |
| **运行时代码（约 600 行）** | **人手写** | ✅ **每种语言重写一遍** |

Go 版就是手写 Go，TS 版就是手写 TS。没有任何转译。

### 7.2 为什么"每语言重写 600 行"是可接受的

因为 §2 的三个实测把索引全部预计算掉了，每种语言实际要写的是：

```
.gtc 二进制读取 / 分节解析          ~200 行
varint 解码 + 多边形解码            ~80 行
网格查表 + 射线法点在多边形内        ~100 行   ← 唯一的"算法"，且平均只判 2 个多边形
名称 / adcode 索引查询 + 搜索        ~120 行
坐标转换 WGS84 / GCJ02 / BD09       ~80 行    ← 纯数学，各语言有现成实现可参考
行政区划树构建                       ~60 行
```

没有 R-tree、没有几何库、没有 CRS、没有空间连接。熟悉该语言的人一周可移植完，
且**跑 conformance 就能客观证明它是否正确**。

> **反过来说**：如果不做 GTC 格式这一层、让每种语言直接啃 28 MB GeoJSON 并自建 R-tree，
> 那等于要在每种语言里重写一个 geopandas——那种情况下 Rust + FFI 才是对的选择。
> **是数据格式的设计让「多语言原生实现」从不可行变成可行的。**

### 7.3 为什么否决分支与转译

| 方案 | 否决理由 |
|------|---------|
| **多分支** | CI 无法在一次 PR 里矩阵跑所有语言的一致性测试；数据更新要 cherry-pick N 次；实现之间无法 diff 对照 |
| **转译** | 不存在能产出**惯用**、可读、可调试的 Go/TS 的可靠工具；转译产物没人愿意贡献、出 bug 无法在目标语言排查；而且我们要去掉的恰恰是 geopandas，转译会把它一起带过去 |

### 7.4 仓库结构

```
GeoToolCN/                          （单一 monorepo）
├── SPEC.md                         ← 唯一真源：GTC 格式 + API 行为规范
├── docs/RFC-001-multi-language.md
├── data/                           源 GeoJSON（转 git-lfs）
├── pipeline/                       Python 构建管线：fetch → 转换 → 校验 → 生成 .gtc
├── conformance/                    语言无关黄金测试集
├── packages/
│   ├── python/    pyproject.toml   → PyPI      geotool-cn
│   ├── node/      package.json     → npm       @geotoolcn/core
│   ├── go/        go.mod           → Go module（含 data/，见下）
│   └── rust/      Cargo.toml       → crates.io geotoolcn （后续）
└── .github/workflows/
    ├── conformance.yml             每个 PR：矩阵跑全部语言 × 同一套测试集
    ├── release-data.yml            tag data-*  → 构建 .gtc → GitHub Release + npm data 包
    ├── release-python.yml          tag py-v*   → twine upload
    ├── release-node.yml            tag npm-v*  → npm publish
    └── release-go.yml              tag go-v*   → 同步到镜像仓库
```

每个语言目录就是该生态里一个**标准的、独立的包**，内含自己的构建配置、测试、README。
用户完全不需要知道其他语言的存在。

### 7.5 各语言的发布通道

| 语言 | 触发 | 动作 | 用户安装 |
|------|------|------|---------|
| Python | tag `py-v3.0.0` | `python -m build` + `twine upload` | `pip install geotool-cn` |
| TS/JS | tag `npm-v1.0.0` | `npm publish`（core + data 分包） | `npm install @geotoolcn/core` |
| Go | tag `packages/go/v1.0.0` | 无需发布，proxy 直接解析 tag | `go get github.com/13Cohen/GeoToolCN/packages/go` |
| Rust | tag `rs-v1.0.0` | `cargo publish` | `cargo add geotoolcn` |
| 长尾语言 | tag `cli-v1.0.0` | 交叉编译二进制 + 推 GHCR | `docker run ghcr.io/13cohen/geotoolcn serve` |

**⚠️ Go 的特殊处理**：Go module 没有中心化 registry，`go get` **直接从 git 拉源码**。
这带来两个后果：

1. 子目录 module 的导入路径必须是 `github.com/13Cohen/GeoToolCN/packages/go`，
   版本 tag 必须写成 `packages/go/v1.0.0`。

   > **修正（发布 v3.0.0 时发现）**：上面这条只对 v0/v1 成立。Go 从主版本 2 起额外要求
   > 导入路径以 `/vN` 结尾，因此实际路径是 `github.com/13Cohen/GeoToolCN/packages/go/v3`，
   > 而 tag 仍是 `packages/go/v3.0.0`（tag 前缀是目录，不含 `/v3`）。
   > 这个疏漏在本地完全不可见 —— `go build`、`go test`、`go vet` 全部通过，连 CI 的
   > 交叉编译都是绿的，只有从 proxy `go get` 时才会被拒绝。
   > 它是被 `scripts/verify_published.py` 抓到的，也正是那个脚本存在的理由。
2. **更关键**：`go:embed` 只能引用模块目录内的文件，且 `go get` 只能拿到 git 里的内容。
   因此 `packages/go/data/china.full.gtc` **必须提交**，成为仓库里唯一一份重复存放的数据。

> 实现阶段曾配置镜像仓库 `13Cohen/geotoolcn-go`（protobuf、googleapis 的做法），
> 由 CI 在发布时把数据复制进去，主仓库因此只存一份。**后改为单仓库方案**：
> 多 6 MB 换掉「一个额外仓库 + 一个可能悄悄失效的同步 job」，更符合本项目
> 「所有语言同一个仓库」的取向。代价是导入路径较长，以及每次数据更新在历史里多 6 MB。

### 7.6 数据是怎么进到各个包里的

`.gtc` 由管线生成一次，然后按各生态的惯例进包：

| 语言 | 方式 |
|------|------|
| Python | `package-data` 打进 wheel（现在已是这个模式） |
| TS/JS | 拆成 `@geotoolcn/data-mini` / `-lite` / `-full` 独立 npm 包，core 声明 peer 依赖，用户按需装；浏览器可改为运行时 `fetch` CDN |
| Go | 独立 module + `go:embed`，避免主 module 每次数据更新都涨体积 |
| Rust | `include_bytes!` 或 feature flag 控制档位 |

### 7.7 版本策略（数据与代码解耦）

- **数据**：日历版本 `data-2026.03`，发到 GitHub Releases（`.gtc` + SHA256）
- **各语言包**：SemVer，包内 pin 一个数据版本；同时支持运行时指定外部 `.gtc` 路径
  （替代现有的 `data_dir` 参数）
- **格式**：`format_version`，运行时拒绝不兼容大版本

数据更新时：一次 `data-*` tag 触发所有语言包的自动发版，无需人工同步 N 次。

---

## 8. 路线图

| 阶段 | 内容 | 预估 | 产出 |
|------|------|------|------|
| **P0** | 冻结契约：写 `SPEC.md` v1；用现有 Python 生成 conformance 数据集。**不改任何行为** | 1–2 周 | SPEC + 测试集 |
| **P1** | 管线 + 格式：`pipeline/` 产出 `.gtc`；Python 改用 `.gtc`、**去 geopandas** → 发 `geotool-cn` v3 | 2–3 周 | 参考实现 + 格式验证 |
| **P2** | TS/JS：`@geotoolcn/core` + 数据分包 + 浏览器 demo | 2–3 周 | **覆盖面最大的一步** |
| **P3** | Go：`geotoolcn-go`，纯 Go 无 cgo | 2 周 | |
| **P4** | CLI 二进制 + Docker HTTP 服务 + 「新增语言」移植模板与贡献指南 | 1 周 | 覆盖长尾语言 |
| **P5** | 社区：Rust / Java / C#；可选 WASM 加速包 | 持续 | |

P0/P1 是必须自己做的（定契约 + 验证格式）；P2 之后每一步都是可并行、可外包给社区的独立任务。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Python v3 破坏性变更 | 现有用户 | 公开 API 全兼容，只换实现；若用户依赖 `GeoDataFrame` 内部属性会受影响 → v2 分支维护 6 个月 + `MIGRATION_v3.md` |
| 量化导致边界结果回归 | 正确性 | conformance 覆盖 2 万点含边界密集采样；`full` 档 1 m 精度远小于行政边界本身的数据误差；默认用 `full` |
| 浏览器场景数据仍偏大 | 采用率 | `mini` 档 150 KB 覆盖大部分前端需求（级联选择器 / adcode 查询）；反查场景可在 P4 加按省分片的 GRID 按需加载 |
| 多语言维护成本失控 | 长期 | 靠 SPEC + conformance 锁死成本；实现薄到一个人一周可移植；准入门槛保证质量 |
| 跨语言浮点 / 取整差异 | 隐蔽 bug | §6.1 逐条钉死；conformance 专门覆盖边界坐标与取整临界值 |
| 数据更新需同步多个包 | 运维 | 数据独立版本 + 单一 Release 触发各语言包的自动化发版 workflow |

---

## 11. 实验验证：去掉 geopandas 的实际影响

§2 的三个事实和 §4 的性能主张原本都是**推断**。为验证，构建了完整可运行原型
（`.context/scratch/gtc-proto/`，约 250 行）：`build_gtc.py` 构建 `.gtc`，
`runtime.py` 是零依赖纯标准库运行时，`compare.py` 与现有 geopandas 实现逐点对拍。

### 11.1 性能实测

| 指标 | 现有（geopandas） | GTC 原型（纯 Python） | 倍数 |
|------|------------------|---------------------|------|
| 第三方依赖体积 | **135 MB** | **0**（仅标准库） | — |
| 冷启动（子进程，含 import） | 1453 ms | **23 ms** | **63x** |
| 数据加载（进程内） | 1207 ms | **7 ms** | **173x** |
| 单次 `reverse` | 252 μs | 60 μs（冷）/ **12–17 μs**（热） | 4–20x |
| 1000 点（`reverse_batch`） | 870 ms | **17 ms** | **51x** |
| 1000 点（逐个循环） | 310 ms | 17 ms | 18x |
| 常驻内存 | 173 MB | **28 MB** | 6x |
| 数据文件 | 28 MB GeoJSON | **5.95 MB** `.gtc` | 4.7x |

> 加载之所以只要 7 ms：整型索引表以定宽数组存储，`array.frombytes` + `mmap` 近乎零成本；
> 多边形**按需解码并缓存**，命中实心格时完全不解码。

**顺带发现的现有实现缺陷**：`reverse_batch(1000)` 耗时 870 ms，比逐个调用 `reverse` 的
310 ms 还慢。原因是 `core.py` 中每个点都执行 `j[j["idx"] == i]` 全表扫描，复杂度 O(n²)。
即当前"批量优化"实际上是负优化，建议在 v2 分支单独修复。

### 11.2 正确性对拍（8,748 个点）

| 类别 | 样本 | 一致 | 一致率 |
|------|------|------|--------|
| 每个区县的代表点 | 2,874 | 2,873 | 99.97% |
| 代表点 ±0.3° 扰动（大量落在边界附近） | 2,874 | 2,873 | 99.97% |
| 全国 bbox 均匀随机 | 3,000 | 3,000 | 100.00% |
| **合计** | **8,748** | **8,746** | **99.977%** |

**2 处不一致经核查，均为现有实现的 bug，新方案是更正确的一方**：

```
(30.66457, 122.56396) 嵊泗县(330922)  geopandas → province=None   GTC → 浙江省
(28.04746, 121.13337) 玉环市(331083)  geopandas → province=None   GTC → 浙江省
```

原因：这两处是离岛（舟山群岛、玉环岛），**省级多边形不覆盖，但区县级多边形覆盖**。
现有实现逐层独立做点在多边形判定，于是返回了自相矛盾的结果——
`province=None` 却同时 `city=舟山市`。
新方案由区县 adcode 前缀推导上级（§2 事实 1），层级天然自洽，不可能出现这种矛盾。

> **量化到 1e-5（约 1 m）没有造成任何可测量的精度损失**——包括 2,874 个专门构造的边界扰动点。

### 11.3 意外发现：网格索引的体积 / 加载速度权衡

原型首次构建出的 `.gtc` 是 **10.59 MB**，远超预估的 3.7 MB。原因是网格索引按「逐格 int32」
朴素存储占了 6.76 MB。实测三种存储形态：

| 方案 | 索引体积 | 总 `.gtc` | 加载耗时 | 说明 |
|------|---------|----------|---------|------|
| A 朴素逐格 int32 | 6.76 MB | 10.52 MB | ~7 ms | 体积不可接受 |
| **B 定宽行程编码（推荐）** | **2.06 MB** | **5.82 MB** | **~7 ms** | 零解码，`mmap` 直接二分 |
| C RLE + varint 全压缩 | 0.65 MB | 4.41 MB | ~60 ms | 最小，但每次启动需解码 |

行程编码效果显著：区县层 298,517 个实心格 → 30,400 个行程（9.8x），
省级层 371,076 格 → 5,850 个行程（63.4x）。
方案 B 在行程数组上直接二分查找，实测 **0.39 μs/次**，与逐格查表抽查 8,069 格结果完全一致。

**选择 B**：npm / PyPI 的包分发本身就带压缩传输（5.95 MB → 约 2.6 MB 上线体积），
没必要为了文件小 1.4 MB 而牺牲 8 倍的启动速度。

### 11.4 实际改动范围比预想的小

关键事实：**`admin_tree.py` 和 `coords.py` 本来就是零依赖纯标准库**，无需任何改动。
真正依赖 geopandas 的只有 `core.py`（20 KB）。

即「去掉 geopandas」= 重写一个文件，而不是重构整个包。

### 11.5 结论与残留风险

**实验结论：去掉 geopandas 在各方面都是净收益，无可测量的负面影响。**

仍需在 P1 补齐的部分（原型未覆盖）：

| 项 | 说明 |
|----|------|
| `search()` / `list_regions()` / `get_region()` | 纯索引查询，无几何运算，风险低 |
| `reverse_batch()` API 兼容 | 直接循环即可，已比现有实现快 51x |
| `is_in_region()` | 复用 `_contains`，风险低 |
| on-edge 判定规则 | 原型用了朴素射线法，未按 §6.1 严格实现；需补边界专项用例 |
| `data_dir` 参数兼容 | 改为接受外部 `.gtc` 路径 |
| 台湾 / 港澳 | 原型未专项验证（台湾仅省级数据） |

---

## 12. 逐 API 审计：功能会缺失吗？结果会变吗？

§11 只对拍了 `reverse` 的 province / district，**没有覆盖 city，也没覆盖其余 API**。
本节补齐完整审计。

### 12.1 功能缺失：无

| 公开 API | 依赖 geopandas？ | 纯 Python 可实现？ |
|---------|-----------------|------------------|
| `get_administrative_tree()` | **否，本来就是纯标准库** | 无需改动 |
| `wgs84_to_gcj02` 等 6 个坐标转换 + `distance()` | **否，本来就是纯标准库** | 无需改动 |
| `reverse()` / `reverse_batch()` | 是 | ✅ 网格 + 射线法 |
| `search()` | 是 | ✅ 索引查询（但见 12.3） |
| `list_regions()` / `get_region()` / `lookup_adcode()` | 是 | ✅ 纯查表 |
| `is_in_china()` / `is_in_region()` | 是 | ✅ 复用 `_contains` |
| `Region` / `ReverseResult` | 否 | 无需改动 |

**结论：没有任何功能需要放弃。** 且实际改动面只有 `core.py` 一个文件——
`admin_tree.py` 与 `coords.py` 经核查零第三方 import。

### 12.2 ⚠️ 修正 §2 事实 1：city 不能用 adcode 前 4 位推导

原方案写的「city = adcode 前 4 位 + 00」是**错的**。实测：有 **30 个区县**用此规则会算出根本不存在的区划码：

```
adcode 段 4190 河南济源市      4290 湖北仙桃/潜江/天门/神农架
         4690 海南 13 个县市    6590 新疆 8 个县级市
→ 推导出 419000 / 429000 / 469000 / 659000，均非真实行政区划
```

这些是**省直辖县级行政区**，没有地级市这一层。

**正确做法**：构建期把每个 district 的 parent city 显式算好，存进 META 的 `parent` 字段，
运行时零推导、直接查表。修正后 city 一致率从 97.27% 升到 **99.87%**。

> 「city 层几何冗余」这个结论仍然成立——**丢弃的是 city 的多边形，不是 city 的元数据**。
> META 里的 363 条 city 记录（名称 / 代表点 / parent）必须保留。

### 12.3 结果变化的四种类型

对 8,748 个点做了 province / city / district 三层全量对拍，差异归为四类。

#### 类型 1 — 修复现有 bug（新实现更正确）

**(a) 离岛的 province 丢失**（§11.2 已述）：嵊泗县、玉环市、重庆潼南区、新疆博乐市等。
省级多边形不覆盖但区县级覆盖，现有实现返回 `province=None` 却同时返回 `city=舟山市`。

**(b) city 与 district 自相矛盾** —— 更严重。实测 5 例，**全部核实为数据源本身矛盾**：

```
(40.8753, 109.8924)
  city 层   包头市(150200)      contains = True
  district 层 乌拉特前旗(150823)  contains = True   ← 但它属于巴彦淖尔市
  city 层   巴彦淖尔市(150800)   contains = False
  ⇒ 同一个点被两个市同时认领

现有实现返回：city=包头市 + district=乌拉特前旗   ← 自相矛盾的结果
新实现返回：  city=巴彦淖尔市 + district=乌拉特前旗 ← 层级自洽
```

同类另 4 例：苏州/嘉兴（330411）、温州/丽水（331127）、阜阳/亳州（341623）、汕尾/揭阳（445224）。

**新方案由 district 反推上级，结构上不可能产生这类矛盾。**

#### 类型 2 — 真实的结果丢失（唯一的负面影响）

`district = None` 但 city 多边形覆盖该点的情况（沿海 / 边界空隙）：
**8,622 个点中 2 例，发生率 0.023%**。丢弃 city 几何后这些点的 city 会变成 `None`。

对策二选一：

| 方案 | 代价 |
|------|------|
| A. SPEC 规定 district 为 None 时 city 也为 None | 0.023% 的点丢 city；语义更自洽 |
| B. 保留 city 几何作为兜底 | `.gtc` 增大约 1.5 MB |

建议 A（并在 conformance 中固化这 2 类样本），B 留作 `full+` 档的可选项。

#### 类型 3 — 需要显式对齐，否则会变

| 项 | 实测 | 对策 |
|----|------|------|
| `Region.latitude/longitude` | 量化到 1e-5 后 `representative_point()` 最大偏移 **1.6 米**（清原满族自治县） | 构建期用**原始精度**几何预计算，存入 META。运行时直接读 → **值完全不变** |
| `list_regions("district")` 顺序 | 文件顺序几乎已是 adcode 升序，**仅 1 处逆序**（330114 排在 330113 前） | 若 SPEC 规定按 adcode 排序，只影响这一对 |
| `list_regions("province"/"city")` 顺序 | 已是 adcode 升序 | 无影响 |

#### 类型 4 — ⚠️ `search(fuzzy=True)` 实际是正则匹配

现有实现用 `gdf["name"].str.contains(query)`，pandas 默认 **`regex=True`**。实测：

```python
search("东.区")     → 18 条   # "." 被当作正则通配符
search("西城|东城")  → 2 条    # "|" 被当作正则或
search("北京(市)")   → 0 条    # "()" 被当作分组
search("[")         → 抛 re.error: unterminated character set
```

这是**未文档化的正则注入**，几乎肯定不是设计意图。但它是现存行为，改掉就是破坏性变更。

跨语言的关键约束：**正则方言不兼容**。Python `re`、Go `regexp`（RE2，不支持反向引用）、
JS `RegExp` 三者语义不同，把正则写进 SPEC 会让 conformance 无法跨语言收敛。

建议：**SPEC 规定 `fuzzy` 为纯子串匹配**；Python v3 保留 `search(..., regex=True)` 作为
兼容逃生舱并标记 deprecated。这是本次迁移中**唯一需要用户感知的行为变更**。

### 12.4 汇总

| 类别 | 数量 / 发生率 | 性质 |
|------|-------------|------|
| 功能缺失 | **0** | — |
| 修复现有 bug | 离岛 province 丢失 + 5 例 city/district 自相矛盾 | ✅ 净收益 |
| 真实结果丢失 | 0.023%（district 为 None 时的 city） | ⚠️ 可接受，或用方案 B 消除 |
| 需构建期对齐 | 代表点、返回顺序 | 对齐后 **0 变化** |
| 需用户感知的变更 | `search` 正则 → 子串 | ⚠️ 需决策 |
| API 破坏 | `data_dir` 语义 | ⚠️ 可做兼容 |

---

## 10. 待决策

1. 是否接受 Python v3 换实现（去 geopandas）？这是收益最大但也唯一有破坏性风险的动作。
2. P2 之后（Go / Rust / Java）是自己做还是开放给社区？影响 SPEC 与贡献指南的详细程度。
3. ~~`full` 档默认精度？~~ **§11.2 实验已回答：1e-5 零精度损失，用 1e-5。**
   ~~D3：`data_dir` 传目录时仍读 GeoJSON 以保持兼容。~~ **实现阶段作废** —— 该决策
   在架构定型前做出，事后不可行：v3 不依赖 geopandas，读不了 GeoJSON；保留这条路径
   等于把 135 MB 依赖装回来。实际语义见 `known-divergences.yaml` 的 DIV-102。
4. **§12.3 类型 2**：`district=None` 时 city 是否也置 None（省 1.5 MB），还是保留 city 几何兜底？
5. **§12.3 类型 4**：`search(fuzzy=True)` 从正则改为纯子串——接受这个破坏性变更吗？
