# GeoToolCN v3.0.0 升级指南

## 概述

v3.0.0 移除了 **geopandas 与 shapely 依赖**。空间索引改为在构建期预计算进一个二进制数据文件，运行时只需查表加少量射线法判定。

| 指标 | v2.1.0 | v3.0.0 |
|------|--------|--------|
| 第三方依赖 | geopandas + shapely（安装约 135 MB） | **无** |
| 冷启动（含 import） | ~1450 ms | **~25 ms** |
| 数据加载 | ~1200 ms | **~9 ms** |
| 单次 `reverse` | ~250 μs | **~5 μs** |
| 常驻内存 | ~170 MB | **~30 MB** |
| 安装体积 | ~163 MB | **~6 MB** |

**公开 API 没有增删。** 大多数项目升级后无需改动任何代码。

---

## 自查清单

### 1. 依赖声明

若你的 `requirements.txt` / `pyproject.toml` 因为 GeoToolCN 而显式列了 geopandas 或 shapely，现在可以去掉：

```bash
grep -rn "geopandas\|shapely" requirements*.txt pyproject.toml setup.py 2>/dev/null
```

若你的代码本身直接用到它们，请保留 —— GeoToolCN 不再引入它们，但也不会阻止你使用。

### 2. `data_dir` 参数

**变更**：`GeoTool(data_dir=...)` 现在接受 `.gtc` 文件路径，或包含 `china.full.gtc` 的目录。不再接受装有 GeoJSON 的目录。

```python
# v2.x：自定义 GeoJSON 目录
geo = GeoTool(data_dir="/path/to/geojson/")

# v3.0：先构建 .gtc，再指向它
#   python pipeline/build_gtc.py --out /path/to/custom.gtc
geo = GeoTool(data_dir="/path/to/custom.gtc")
```

**自查方法**：

```bash
grep -rn "GeoTool(" --include="*.py" your_project/ | grep data_dir
```

绝大多数用户使用内置数据，不传该参数，不受影响。

### 3. 访问过内部属性的代码

**变更**：`GeoTool._levels`、`_LevelData`、`.gdf` 等私有属性已随 geopandas 一起移除。

```bash
grep -rn "_levels\|\.gdf\|_LevelData" --include="*.py" your_project/
```

这些从未是公开 API。若你依赖它们取原始几何，请改用 `pipeline/` 里的构建脚本，或直接读取仓库中的 GeoJSON。

### 4. 边界坐标的归属

**变更**：坐标在数据文件中量化到 **1e-5 度（约 1.11 米）**。距行政边界不足一个量化步长的点，归属可能与 v2.1 不同。

实测 16,509 个反查用例中 **10 条（0.061%）** 发生变化，全部距争议边界 **0.019 ~ 0.460 米**。这些点本就落在数据自身精度之下 —— DataV 边界的名义精度远粗于半米。

若你的业务对亚米级边界敏感，请用实际坐标做一次回归比对。

### 5. 落在区县空隙中的坐标

**变更**：当某坐标不在任何区县多边形内（沿海空隙、边界缝隙）时，`city` 字段现在恒为 `None`。

v3 的数据文件保留了全部 363 条地级市**元数据**（名称、代表点、层级关系），但不再保留其**多边形** —— 市级归属由区县的 adcode 推导，不需要独立几何。

实测发生率约 **0.023%**。此时 `province` 仍会正确返回（v3 保留了省级几何）。

```python
# 建议的防御式写法（v2 v3 均适用）
result = geo.reverse(lat, lng)
city_name = result.city.name if result.city else None
```

---

## 反而变得更正确的地方

以下几类结果在 v3 中发生变化，是因为 v2 的答案自相矛盾：

| 场景 | v2.1 | v3.0 |
|------|------|------|
| 离岛的 `is_in_china` | `False`，但同一坐标 `reverse().province` 却是浙江省 | 两者一致为真 |
| 区县空隙处的 `city` | 可能返回另一个省的市（如重庆市境内返回恩施州） | 只从省级几何取 `province`，不可能跨省 |

若你的代码依赖 `is_in_china()` 与 `reverse()` 不一致的行为（不太可能），请重新测试。

---

## 不受影响的功能

| 用法 | 说明 |
|------|------|
| `reverse()` / `reverse_batch()` | 返回结构不变 |
| `search()` | 含 `regex=` 参数在内，行为不变 |
| `list_regions()` / `get_region()` / `lookup_adcode()` | 不变 |
| `is_in_region()` | 不变 |
| `get_administrative_tree()` | 不变（纯标准库，v2.1 起就未依赖 geopandas） |
| 坐标转换与 `distance()` | 不变（纯数学） |
| `Region` / `ReverseResult` 数据类 | 字段与类型不变 |

---

## 升级步骤

1. `pip install -U geotool-cn`
2. 按上方清单全局搜索受影响的写法
3. 运行你自己的测试
4. 若存储过历史反查结果，对边界坐标做一次抽样比对（预期差异率 < 0.1%）

## 出了问题怎么办

v2.1.0 仍可安装，会维护 6 个月：

```bash
pip install "geotool-cn==2.1.0"
```

并请提交 issue：https://github.com/13Cohen/GeoToolCN/issues

---

## 给移植者

v3 的实现是 `SPEC.md` 所描述契约的参考实现。若你要把 GeoToolCN 移植到其他语言：

- `SPEC.md` — 完整契约：API 语义、歧义规则（取整、射线法、定序）、`.gtc` 二进制格式
- `conformance/` — 约 3.5 万条语言中立用例，任何实现都必须通过
- `GeoToolCN/_gtc.py` — 约 350 行的读取器，可作为移植底本
