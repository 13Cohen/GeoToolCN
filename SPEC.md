# GeoToolCN 规范 v1

> 格式版本 `format_version = 1` · 状态：草案 · 最后更新：2026-09-09

本文件是 GeoToolCN 各语言实现的**唯一真源**。任何实现只要满足本规范，就能通过
`conformance/` 全套测试；反之，conformance 中出现的任何分歧都应回到本文件澄清，
而不是在某个语言实现里特殊处理。

阅读顺序建议：§1 数据模型 → §2 API 行为 → §3 歧义规则 → §4 GTC 二进制格式。
若只实现 `mini` 档（无几何），§4.6 网格索引与 §3.3 射线法可以跳过。

**术语**：本文所有坐标均为 WGS-84。`adcode` 指 6 位中华人民共和国行政区划代码。

---

## 1. 数据模型

### 1.1 Region

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 区划名称，如 `"北京市"` |
| `code` | string | 6 位 adcode，如 `"110000"`。**始终为字符串**，禁止用整数（会丢前导零语义并诱发跨语言差异） |
| `level` | enum | `"province"` \| `"city"` \| `"district"` |
| `latitude` | float | 代表点纬度 |
| `longitude` | float | 代表点经度 |

**代表点**必须在构建期以**原始精度**几何计算后写入 META，运行时直接读取。
不得在运行时用量化后的几何重新计算 —— 实测量化到 1e-5 后代表点最多偏移 1.6 米。

### 1.2 ReverseResult

三个可空字段：`province`、`city`、`district`，各为 `Region` 或空。

### 1.3 TreeNode

```
{ "value": "<adcode>", "label": "<name>", "children": [TreeNode, ...] }
```

`children` 键的有无必须**严格**按下表，否则 conformance 的树哈希对不上：

| 节点 | `children` |
|------|-----------|
| 省级 | **始终存在**，无下级时为 `[]`（台湾省即如此） |
| 市级 | **始终存在**，无下级时为 `[]` |
| 区县（叶子） | **不存在**，不是 `[]` 也不是 `null` |

⚠️ 这一条在移植时容易踩：Go 的 `json:"children,omitempty"` 会把空数组一并丢掉，
使省级节点缺少该键；需要自定义 `MarshalJSON` 区分「nil（叶子）」与「空但非 nil」。

树哈希的计算方式：对整棵树做规范化 JSON 序列化（**键名升序、无空格、不转义非 ASCII**），
取其 UTF-8 字节的 SHA-256。注意 Go 的 `encoding/json` 默认转义 `<`、`>`、`&`，
需 `SetEscapeHTML(false)`。

### 1.4 层级关系

- 省级 adcode 恒为 `<前2位> + "0000"`。
- **区县的父级市不得用 `adcode[:4] + "00"` 推导。** 该规则对 30 个省直辖县级行政区
  （adcode 段 `4190` 济源、`4290` 仙桃/潜江/天门/神农架、`4690` 海南、`6590` 新疆）会算出
  `419000` 这类不存在的编码。父级关系必须由构建期写入 META 的 `parent` 字段确定。
- 直辖市与特别行政区（adcode 前 2 位属 `{11, 12, 31, 50, 81, 82}`，下称 **MERGED 前缀**）
  没有独立的地级市层：其区县的 `parent` 为省级 adcode。

---

## 2. API 行为契约

各语言按自身命名惯例调整大小写（`reverse_batch` / `reverseBatch` / `ReverseBatch`），
语义必须完全一致。

### 2.1 `reverse(lat, lng) -> ReverseResult`

```
1. 若 (lat, lng) 命中某个区县：
     district = 该区县
     province = lookup(district.code[:2] + "0000")
     city:
       若 district.parent == province.code  → province 的副本，level 改为 "city"
       否则                                  → lookup(district.parent)
       若 district.parent 为空               → 空
2. 否则：
     province = 省级图层的点在多边形查询结果（可能为空）
     city     = 城市图层的点在多边形查询结果（可能为空）
     若 city 为空且 province 非空且 province 属 MERGED 前缀
                                            → city = province 的副本，level 改为 "city"
     district = 空
```

**上级必须由区县 adcode 推导，不得对三个图层各做一次独立的点在多边形判定。**
数据源本身在多处自相矛盾：加格达奇区(232718) 行政属黑龙江但落在内蒙古的省级多边形内；
若干区县多边形越出本省轮廓延伸到离岛；城市多边形在地级市交界处互相重叠，
同一个点会被两个市同时认领。独立判定会产出 `province=None` 却同时 `city=舟山市`
这类自相矛盾的结果。

> `full` / `lite` 档若不含城市图层几何（见 §4.1），第 2 步中的 `city` 恒为空。
> 这是已登记的差异 `DIV-004`，实测发生率 0.023%。

### 2.2 `reverse_batch(coords) -> ReverseResult[]`

逐点等价于 `reverse`。输入为空时返回空列表。顺序与输入一致。

### 2.3 `search(query, level?, province?, city?, fuzzy=true, regex=false) -> Region[]`

```
1. 若 query 全为数字 → 按 adcode 精确查找
2. 否则 → 按名称精确匹配
3. 若精确匹配无结果且 fuzzy 为真 → 子串包含匹配
4. 依次施加 province / city 过滤（若提供）
```

- **`fuzzy` 为纯子串匹配**（区分大小写的字面包含），不是正则。
  正则方言跨语言不兼容（Python `re` / Go RE2 / JS `RegExp` 语义不同），
  写进规范会让 conformance 无法收敛。
- `regex` 参数为**可选**扩展，仅 Python 为兼容 2.0.x 提供；其他语言可不实现。
- `level` 限定搜索层级；未提供时按 `province` → `city` → `district` 顺序搜索。
- `province` / `city` 过滤接受**名称或 adcode**，按 §2.4 判定归属。

**结果排序**：先按 level（`province` < `city` < `district`），同 level 内按 adcode 升序。

### 2.4 父级过滤判定

**按 adcode 关系判定，不得用几何包含判定。**
区划的代表点可能落在其父级多边形之外 —— 离岛尤甚 ——
旧实现因此让 `search("嵊泗县", province="浙江省")` 返回空列表。

```
在省 P 之下：region.code[:2] == P.code[:2]
在市 C 之下：region.level == "district" → region.parent == C.code
             否则                        → region.code == C.code
```

### 2.5 `list_regions(level) -> Region[]`

返回该层级全部区划，**按 adcode 升序**。`level` 非法时抛出该语言惯用的参数错误。

### 2.6 `get_region(code) -> Region?`

按 adcode 查找，依次搜索 `province` → `city` → `district`，返回首个命中。

### 2.7 `lookup_adcode(adcode) -> ReverseResult?`

```
1. adcode 非 6 位数字 → 返回空
2. 由 adcode 判定层级：
     以 "0000" 结尾 → province
     以 "00" 结尾   → city
     否则           → district
3. province = lookup(adcode[:2] + "0000")
4. city:
     MERGED 前缀      → province 副本（level 改为 "city"）
     层级为 district   → lookup(该 adcode 的 parent)
     层级为 city       → lookup(adcode)
5. district = lookup(adcode)，在 district 图层中查找
     注意：层级判定为 city 时**也要**尝试，因为不设区的地级市
     （东莞 441900、中山 442000、儋州 460400、嘉峪关 620200）
     同时存在于城市与区县两层
6. 三者皆空 → 返回空；否则返回三元组
```

### 2.8 `is_in_china(lat, lng) -> bool`

等价于 `reverse(lat, lng).province != null`。

### 2.9 `is_in_region(lat, lng, adcode) -> bool`

```
1. adcode 非法或不存在 → 抛出该语言惯用的参数错误（不是返回 false）
2. 层级为 city 且属 MERGED 前缀 → 改判省级多边形
3. 否则 → 对该 adcode 对应的多边形做点在多边形判定（§3.3）
```

### 2.10 `get_administrative_tree() -> TreeNode[]`

省 → 市 → 区县三级。省级按 adcode 升序，各级 `children` 同样按 `value` 升序。
MERGED 前缀的省份下只有一个市节点，其 `value` 等于省级 adcode。
台湾省（710000）无下级，`children` 为空数组。

### 2.11 坐标转换

六个转换函数：`wgs84_to_gcj02` / `gcj02_to_wgs84` / `gcj02_to_bd09` /
`bd09_to_gcj02` / `wgs84_to_bd09` / `bd09_to_wgs84`，以及 `distance`（单位：公里）。

⚠️ **参数顺序在本包内并不统一**，移植时务必逐个核对：

| 函数 | 签名 | 返回 |
|------|------|------|
| 六个转换函数 | `(lng, lat)` — **经度在前** | `(lng, lat)` |
| `distance` | `(lat1, lng1, lat2, lng2)` — 纬度在前 | 公里 |
| 所有 `GeoTool` 方法 | `(lat, lng)` — 纬度在前 | — |

这是一个**静默失败**的陷阱：把 `(lat, lng)` 传给转换函数不会报错，
因为交换后的经度值（原纬度，绝对值 < 90）通常落在中国 bbox 之外，
函数按"境外坐标原样返回"的规则把输入原封不动地返回。本仓库的
`test_invariants.py` INV-08 与 conformance 生成器都曾因此空转。

境外坐标原样返回，判定条件为：

```
out_of_china = !(72.004 < lng < 137.8347 && 0.8293 < lat < 55.8271)
```

常量必须逐位一致：

```
A  = 6378245.0
EE = 0.00669342162296594
X_PI = π × 3000 / 180
EARTH_RADIUS_KM = 6371.0
```

> ⚠️ **conformance 抓不到常量抄错。** 实测把 `A` 改成 `6378245.5`（差 0.5 米），
> 全数据集上输出最大只变化 7.6e-10 度 ≈ **0.084 毫米**，低于 1e-9 度的判定容差；
> 把 `EE` 截断到 13 位有效数字，影响更是只有 1e-10 毫米。
> 这类错误物理上确实无意义，但它意味着**常量的正确性只能靠代码评审保证**，
> 不能指望测试。移植时请逐字符比对上表。
> （`EARTH_RADIUS_KM` 是例外：它直接线性影响 `distance`，conformance 能抓到。）

`gcj02_to_wgs84` 为**一次减法近似**（非迭代求逆），往返因此有固有损失。
实测 2 万个境内随机点：

| 转换对 | 中位 | p99 | 最大 |
|--------|------|-----|------|
| `wgs84 ↔ gcj02` | 0.64 m | 3.20 m | 4.75 m |
| `gcj02 ↔ bd09` | 0.05 m | 0.17 m | 0.22 m |
| `wgs84 ↔ bd09` | 0.64 m | 3.22 m | 4.72 m |

实现的往返误差应落在同一量级。若某个实现显著更准，说明它用了迭代求逆
——那是**不同的算法**，会与本规范的其他实现产生分歧，须先修订本规范。

---

## 3. 歧义规则

跨语言实现最容易在此处悄悄漂移。以下每条都必须逐字遵守。

### 3.1 取整

**一律使用 round-half-away-from-zero**（`0.5 → 1`，`-0.5 → -1`）。

⚠️ 语言默认行为不同：Python 的 `round()` 是 banker's rounding（`round(0.5) == 0`），
JavaScript 的 `Math.round` 是 half-up（`Math.round(-0.5) == -0`）。
两者都**不**符合本规范，必须显式实现：

```
round_half_away(x) = sign(x) * floor(abs(x) + 0.5)
```

### 3.2 量化

```
quantize(v)   = round_half_away(v * 10^precision)      → 整数
dequantize(q) = q / 10^precision                        → 浮点
```

`precision` 取自文件头（`full` 档为 5，`lite` 档为 4）。

查询坐标在做几何判定前，按同一 `precision` 缩放为浮点数（**不取整**），
以避免查询点被吸附到量化格点上：

```
qx = lng * 10^precision      （保持浮点）
qy = lat * 10^precision
```

### 3.3 点在多边形

使用**射线法（even-odd / crossing number）**，逐条边判定：

```
inside = false
for i in 0..n-1:
    j = (i - 1 + n) mod n
    if (ys[i] > y) != (ys[j] > y):
        xint = xs[i] + (y - ys[i]) * (xs[j] - xs[i]) / (ys[j] - ys[i])
        if x < xint:
            inside = !inside
```

- 环的首尾点重复（闭合），实现须保证不重复计入。
- 带洞多边形：点在外环内 **且** 不在任何内环内。
- 多部分多边形（MultiPolygon）：任一部分命中即为命中。
- **落在边界上的点视为在内部。** 上述算法对边界点的判定依赖浮点，因此
  conformance 不会在数值边界上设断言；实现无需为此额外处理。
- 判定前应先用 bbox 快速拒绝。

### 3.4 候选区划的遍历顺序

网格混合格中有多个候选时，**按 adcode 升序**遍历，返回首个包含该点的区划。
这保证了同一个点在所有实现中得到相同答案，即使源数据存在多边形重叠。

### 3.5 搜索匹配

- 精确匹配优先，无结果才做子串匹配（`fuzzy` 为真时）。
- 子串匹配为字面包含，不做正则、不做大小写折叠、不做 Unicode 规范化。
- 结果排序见 §2.3。

---

## 4. GTC 二进制格式

小端序，8 字节对齐，可 `mmap`。整型索引表一律定宽存储，使实现能零解码直接查表。

### 4.1 数据档位

| `dataset` | 名称 | 内容 | 实测体积 |
|-----------|------|------|---------|
| 0 | `mini` | META + NAMES，无几何 | **0.13 MB** |
| 1 | `lite` | + 1e-4 几何 + 0.1° 网格 | **3.58 MB** |
| 2 | `full` | + 1e-5 几何 + 0.05° 网格 | **5.95 MB** |

`mini` 档支持除 `reverse` / `reverse_batch` / `is_in_china` / `is_in_region` 外的全部 API。
调用需要几何的 API 时应抛出明确错误，而不是返回空结果。

### 4.2 文件头（32 字节）

| 偏移 | 大小 | 字段 | 说明 |
|------|------|------|------|
| 0 | 4 | `magic` | ASCII `"GTCN"` |
| 4 | 2 | `format_version` | u16，本规范为 `1`。实现遇到不认识的主版本必须拒绝加载 |
| 6 | 1 | `dataset` | u8，见 §4.1 |
| 7 | 1 | `precision` | u8，量化指数 |
| 8 | 4 | `data_version` | u32，形如 `20260307` |
| 12 | 2 | `section_count` | u16 |
| 14 | 2 | — | 保留，置 0 |
| 16 | 4 | `grid_origin_lng` | i32，按 1e6 量化 |
| 20 | 4 | `grid_origin_lat` | i32，按 1e6 量化 |
| 24 | 4 | `grid_step` | u32，按 1e6 量化（0.05° → `50000`） |
| 28 | 2 | `grid_width` | u16，列数 |
| 30 | 2 | `grid_height` | u16，行数 |

### 4.3 节表

紧随文件头，`section_count` 项，每项 24 字节：

| 偏移 | 大小 | 字段 |
|------|------|------|
| 0 | 2 | `type`（见下） |
| 2 | 2 | 保留，置 0 |
| 4 | 4 | `crc32`，该节内容的 CRC-32（IEEE） |
| 8 | 8 | `offset`，自文件起始的字节偏移 |
| 16 | 8 | `length`，字节长度 |

| `type` | 节 |
|--------|-----|
| 1 | `META` |
| 2 | `NAMES` |
| 3 | `GEOM` |
| 4 | `GEOM_INDEX` |
| 5 | `GRID_SOLID` |
| 6 | `GRID_MIXED_CELLS` |
| 7 | `GRID_MIXED_PTRS` |
| 8 | `GRID_MIXED_LISTS` |

节按 `type` 升序排列，`offset` 8 字节对齐，允许填充。

### 4.4 META 节

```
u32  record_count
然后 record_count 条记录，每条 28 字节：
  u32  adcode
  u8   level          0=province 1=city 2=district
  u8   reserved[3]
  u32  parent         父级 adcode；无父级时为 0
  u32  name_offset    NAMES 节内的字节偏移
  u16  name_length    UTF-8 字节数
  u16  reserved
  i32  lat            代表点，按 1e6 量化
  i32  lng
```

记录按 `(level, adcode)` 升序排列。**记录下标即 region_index**，网格索引与 `GEOM_INDEX`
均引用该下标。

`NAMES` 节为 UTF-8 字符串池，不含分隔符，靠 `(name_offset, name_length)` 切分。

### 4.5 GEOM 与 GEOM_INDEX 节

`GEOM_INDEX` 为 `u32[record_count + 1]`，第 `i` 项是第 `i` 个区划在 `GEOM` 节内的起始偏移；
末项等于 `GEOM` 节长度。无几何的区划其起止偏移相等。

`GEOM` 节中每个区划的编码：

```
i32  bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y    （量化坐标）
uvarint  polygon_count
每个 polygon：
  uvarint  ring_count                （首环为外环，其余为内环/洞）
  每个 ring：
    uvarint  point_count
    point_count 组 (dx, dy)，均为 zigzag varint，
    相对前一点的差分；首点相对 (0, 0)
```

> ⚠️ **计数用纯无符号 varint，坐标用 zigzag varint。**
> 这两者不可混用。原型阶段曾对全部整数施加 zigzag，导致解码时环数翻倍、读越界。

varint 为 LEB128：每字节低 7 位为数据，最高位为继续标志。
zigzag 编码 `(n << 1) ^ (n >> 63)`，解码 `(u >> 1) ^ -(u & 1)`。

### 4.6 网格索引

```
col = floor((lng - grid_origin_lng / 1e6) / (grid_step / 1e6))
row = floor((lat - grid_origin_lat / 1e6) / (grid_step / 1e6))
若 col 或 row 越界 → 该点在覆盖范围外，直接返回空
cell_id = row * grid_width + col
```

网格分省级与区县级两套，各自独立的 `GRID_*` 节（通过 `type` 区分的
实现细节由构建端与运行端约定；本版本 `GRID_*` 仅描述区县级，省级网格为可选优化）。

**`GRID_SOLID`** —— 完全落在单个区划内的格子，行程编码：

```
u32  run_count
然后 run_count 条，每条 12 字节：
  u32  start_cell
  u32  length          连续格数
  u32  region_index
```

行程按 `start_cell` 升序、互不重叠，且**不得跨行**（即 `start_cell` 与
`start_cell + length - 1` 必须同 `row`）。查找用二分。

**`GRID_MIXED_*`** —— 需要几何判定的格子：

```
GRID_MIXED_CELLS  u32 count, 然后 u32[count]，cell_id 升序
GRID_MIXED_PTRS   u32[count + 1]，切分 LISTS
GRID_MIXED_LISTS  u32[]，region_index；每格的候选按 adcode 升序
```

空格子（既不在 SOLID 也不在 MIXED）表示该处无区划覆盖。

> 定宽存储是**体积与加载速度的折中**。实测：朴素逐格 `int32` 索引 6.76 MB；
> 定宽行程 2.06 MB，加载约 7 ms；全 varint 压缩 0.65 MB，但加载需约 60 ms。
> 选定宽是因为 npm / PyPI 分发本身带压缩传输，不值得为省 1.4 MB 牺牲 8 倍启动速度。

### 4.7 查询算法

```
lookup(lat, lng):
    计算 cell_id；越界返回空
    在 GRID_SOLID 中二分：命中则直接返回 region_index      ← 约 77% 的查询走到这里
    在 GRID_MIXED_CELLS 中二分：未命中返回空
    取该格候选列表（已按 adcode 升序）
    依次做 bbox 快速拒绝 + 点在多边形判定，返回首个命中
    全部未命中则返回空
```

---

## 5. 一致性要求

- 实现必须通过 `conformance/` 全部用例，且不得对个别用例做特例处理。
- 与参考实现的任何差异，必须在 `conformance/known-divergences.yaml` 中登记；
  **未登记的差异一律视为回归。**
- 新增语言实现的准入门槛见 `docs/RFC-002-testing-and-acceptance.md` §7。

## 6. 变更流程

本规范的任何修改都必须同时更新 `format_version`（涉及二进制布局时）
或 conformance 数据集（涉及行为时），并在 `CHANGELOG.md` 中说明。
