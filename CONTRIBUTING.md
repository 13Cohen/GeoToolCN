# 参与贡献

> [English](CONTRIBUTING_EN.md)

这个仓库里有三种语言的实现读同一份数据、守同一份契约。这决定了贡献流程和普通单语言
项目不同：**改行为要先改契约，改契约要改所有实现，改实现要重新生成测试**。
下面按你想做的事分类。

## 环境

```bash
git clone https://github.com/13Cohen/GeoToolCN && cd GeoToolCN
pip install -e ".[dev]"                     # Python + 测试 + 构建数据用的 geopandas
node packages/node/scripts/sync-data.mjs    # Node 的数据副本（gitignored）
bash packages/go/scripts/sync-data.sh       # Go 的数据副本（已提交，此命令确认它是最新的）
```

只改 Python 不需要 Node 或 Go；但**任何改变行为的提交都会让另外两个实现的一致性测试失败**，
所以 CI 三个都跑。本地全部跑一遍：

```bash
pytest                                                                   # 123 项
python conformance/run.py                                                # Python，38k 条
python conformance/run.py --adapter cmd --cmd "node conformance/adapters/node.mjs"
cd packages/go && CGO_ENABLED=0 go build -o /tmp/gtc-adapter ./cmd/conformance-adapter && cd ../..
python conformance/run.py --adapter cmd --cmd /tmp/gtc-adapter
cd packages/node && node --test && cd ../..
cd packages/go && CGO_ENABLED=0 go test ./... && cd ../..
```

## 我想修一个 bug

先判断它是哪一类：

**结果错了，但 SPEC 是对的** —— 某个实现没按契约做。改那个实现，加一条能复现的用例
（该语言自己的单元测试里），跑一致性套件确认通过。不需要动 SPEC 和套件。

**结果错了，SPEC 也错了（或没说）** —— 这是行为变更，走下一节。

**三个实现一致，但都和 geopandas 参考实现不一致** —— 跑差分对拍看范围：

```bash
python conformance/differential.py -n 200000
```

小于千分之一且集中在边界，多半是量化精度（1e-5 度 ≈ 1.1 米），属预期；否则是 bug。

## 我想改一个行为

顺序不能乱，每一步都有 CI 门禁：

1. **改 `SPEC.md`**。行为的唯一定义在这里，先把新行为写清楚。然后更新 `SPEC_EN.md`，
   运行 `python scripts/check_translations.py --update` 刷新哈希 —— 不刷新 CI 会拦。

2. **改 Python 实现**（`GeoToolCN/`）。它是套件的生成源，先改它。

3. **重新生成一致性套件**：

   ```bash
   python conformance/generate.py
   git diff --stat conformance/
   ```

   审阅 diff：变化的用例数应该和你预期的影响范围一致。如果你改的是搜索排序，
   `reverse.jsonl` 不应该有变化；如果有，说明你改到了别的东西。

4. **改 Node 和 Go 实现**，跑一致性套件直到三者都通过。

5. **如果旧版本的行为是"合法但不同"**（比如排序规则变了，两种都说得过去），在
   `conformance/known-divergences.yaml` 登记一条 `DIV-xxx`，说明旧行为、新行为、原因。
   旧版本的实现可以用 `--allow DIV-xxx` 跑套件。

6. **在 `CHANGELOG.md` 里记录**。会改变已有坐标返回值的变更，写进「结果变化」。

## 我想更新数据

```bash
python scripts/fetch_datav_geojson.py       # 下载，GCJ-02 → WGS-84，生成 DATA_UPDATE_REPORT.md
python pipeline/build_gtc.py                # 构建 GeoToolCN/data/china.full.gtc
python scripts/validate_gtc.py --round-trip # 校验产物
bash packages/go/scripts/sync-data.sh       # Go 的副本必须提交
python conformance/generate.py              # 重新生成套件
pytest                                      # 不变量测试不依赖黄金值，数据更新后仍应全过
```

审阅 `DATA_UPDATE_REPORT.md` 里的增删区划。`tests/test_invariants.py` 的失败意味着新数据
本身有问题（比如某个区县找不到父级），不是测试要改。

## 我想加一种语言

见 [PORTING.md](PORTING.md)：约 600 行，一个适配器，通过 38,000+ 条用例即可合并。
那里有完整的验收清单。

## 我想加一个测试

先问它属于哪一层：

| 层 | 位置 | 什么时候加 |
|----|------|-----------|
| L0 产物 | `scripts/validate_gtc.py` | `.gtc` 文件本身的结构性质 |
| L1 不变量 | `tests/test_invariants.py` | 对**每个**区划都成立的性质，不写死具体值 |
| L2 一致性 | `conformance/generate.py` | 跨语言必须一致的输入输出对 |
| L3 差分 | `conformance/differential.py` | 对照 geopandas 参考实现 |
| L4 单元 | `tests/`、`packages/*/…_test` | 单个实现的内部逻辑、错误路径 |
| L5 发布后 | `scripts/verify_published.py` | 只有装了发布产物才能观察到的性质 |

**加完做变异测试**：故意在实现里注入一个错误，确认新测试变红。测试的失败数应该和错误的
影响范围对得上（比如改了 34 个双层 adcode 的处理，就应该恰好失败 34 条）。
`PORTING.md` 里有已测过的变异及其数字。

## 提交与 PR

- 一个 PR 做一件事。行为变更和顺手修的格式分开提。
- 提交信息说**为什么**，不复述 diff。写明是什么让你发现了这个问题、你排除了哪些其他做法。
- `README.md` 是 CRLF 行尾（历史原因），`scripts/check_line_endings.py` 守着它。
  用脚本改它时注意保留。
- master 通过 squash 合并；**从已合并的分支上再开新分支会冲突**，请从最新的 `master` 开。

## 发布

维护者操作，见 [docs/RELEASING.md](docs/RELEASING.md)。
