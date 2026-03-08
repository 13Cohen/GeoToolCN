# GeoToolCN v2.0.0 升级指南

## 概述

v2.0.0 将底层数据源从腾讯/天地图混合源统一为 [DataV.GeoAtlas](https://datav.aliyun.com/tools/atlas)，同时将行政区划编码从 **9 位国标码（GB code）** 切换为 **6 位行政区划码（adcode）**。

这是一个 **不兼容更新**，请在升级前对照以下清单自查。

---

## 自查清单

### 1. Region.code 编码格式

**变更**：`Region.code` 从 9 位国标码改为 6 位行政区划码。

```
旧版: "156110000"  (前缀 156 + 6 位行政区划码)
新版: "110000"
```

**自查方法**：在代码中搜索以下关键词：

```bash
# 搜索所有使用 .code 的地方
grep -rn '\.code' --include="*.py" your_project/
```

**需要修改的典型写法**：

```python
# 硬编码了 9 位编码的判断
if region.code == "156110000":       # 改为 "110000"
if region.code.startswith("156"):    # 删除，不再需要

# 用 Region.code 存入数据库
db.insert(gb_code=region.code)       # 字段值格式变了，注意历史数据兼容

# 对编码做字符串截取
adcode = region.code[3:]             # 改为直接使用 region.code
province_prefix = region.code[:5]    # 改为 region.code[:2]
```

**快速转换**：如果你的系统仍需要 9 位国标码，可以手动拼接：

```python
gb_code = "156" + region.code  # "156" + "110000" = "156110000"
```

---

### 2. search() 和 get_region() 的编码参数

**变更**：这两个方法按编码查询时，接受的编码格式从 9 位改为 6 位。

```python
# 旧版
geo.search("156440300")         # 找到深圳
geo.get_region("156110000")     # 找到北京

# 新版
geo.search("440300")            # 找到深圳
geo.get_region("110000")        # 找到北京
```

**自查方法**：

```bash
grep -rn 'search("156\|get_region("156' --include="*.py" your_project/
```

> **注意**：传入旧编码不会报错，只会返回空列表或 None，属于静默失败。

---

### 3. search() 的 province / city 过滤参数

**变更**：`province` 和 `city` 参数传入编码时，也需要改为 6 位。

```python
# 旧版
geo.search("朝阳区", province="156110000")

# 新版
geo.search("朝阳区", province="110000")
```

按名称过滤不受影响：

```python
# 两个版本均正常
geo.search("朝阳区", province="北京市")
```

---

### 4. 直辖市 `city` 字段行为变更

**变更**：直辖市（北京、上海、天津、重庆）和特别行政区（香港、澳门）在 `reverse()`、`reverse_batch()`、`lookup_adcode()` 返回结果中，`city` 字段从 `None` 变为一个与省同名的 Region（level 为 `"city"`）。

```python
r = geo.reverse(39.9, 116.4)  # 北京

# 旧版
r.city  # None

# 新版
r.city  # Region(name='北京市', code='110000', level='city', ...)
```

**自查方法**：

```bash
grep -rn 'city is None\|city == None\|\.city\.' --include="*.py" your_project/
```

**需要修改的典型写法**：

```python
# 用 city is None 判断直辖市 —— v2.0 中不再为 None，逻辑失效
if result.city is None:
    print("这是直辖市")

# 替代方案：比较省市编码
if result.province and result.city and result.province.code == result.city.code:
    print("这是直辖市")
```

---

### 5. 边界坐标归属

**变更**：底层 GeoJSON 数据源更换，省/市/区边界多边形有细微差异。

**影响范围**：仅影响恰好位于行政区边界线上的坐标点。绝大多数坐标不受影响。

**受影响的方法**：`reverse()`、`reverse_batch()`、`is_in_region()`、`is_in_china()`

如果你的业务对边界精度敏感，建议用实际坐标做一次回归测试。

---

## 不受影响的功能

以下用法在 v1.x → v2.0.0 中行为不变，无需修改：

| 用法 | 说明 |
|------|------|
| `reverse(lat, lng)` | 返回结构不变，仅 code 格式变化 |
| `search("深圳市")` | 按名称搜索不受影响 |
| `lookup_adcode("440305")` | 入参一直是 6 位 adcode，不变 |
| `is_in_china(lat, lng)` | 不涉及编码 |
| `is_in_region(lat, lng, "440300")` | 入参一直是 6 位 adcode，不变 |
| `get_administrative_tree()` | 结构和内容不变 |
| `wgs84_to_gcj02()` 等坐标转换 | 纯数学函数，不变 |
| `distance()` | 纯数学函数，不变 |

---

## 编码对照速查

| 地区 | v1.x (GB code) | v2.0.0 (adcode) |
|------|----------------|-----------------|
| 北京市 | 156110000 | 110000 |
| 上海市 | 156310000 | 310000 |
| 广东省 | 156440000 | 440000 |
| 深圳市 | 156440300 | 440300 |
| 南山区 | 156440305 | 440305 |

**规律**：新编码 = 旧编码去掉前 3 位 `"156"`。

---

## 升级步骤

1. 对照上方清单，全局搜索受影响的代码模式
2. 将所有 9 位国标码替换为 6 位行政区划码
3. 检查用 `city is None` 判断直辖市的逻辑（v2.0 中 `city` 不再为 None）
4. 运行测试，关注边界坐标的归属变化
5. 如有历史数据存储了 `Region.code`，制定数据迁移方案（去掉 `"156"` 前缀）
