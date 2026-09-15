# 发布流程

四个生态各自从**自己的 tag 前缀**发布，互不牵连 —— 发一次 Python 不会把 Node 包一起带上去。
所有发布都由 `.github/workflows/release.yml` 完成，本地不需要 `npm publish` 或 `twine`。

| 生态 | tag | 发布到 | 凭据 |
|------|-----|--------|------|
| Python | `py-v3.0.0` | PyPI `geotool-cn` | 无 —— Trusted Publishing（OIDC） |
| Node | `npm-v3.0.0` | npm `@geotoolcn/core` | 无 —— Trusted Publishing（OIDC） |
| Go | `packages/go/v3.0.0` | 无（`go get` 直接解析 git tag） | 无 |
| CLI | `cli-v3.0.0` | GitHub Release 二进制 + `ghcr.io/13cohen/geotoolcn` | `GITHUB_TOKEN`（自带） |

Go 的 tag 形状不是审美选择：module 位于子目录时，Go 要求 tag 必须是 `<子目录>/vX.Y.Z`。

## 发布一个版本

**版本号以仓库为准，tag 必须与之一致**。发布流程不再从 tag 反写 manifest —— 那样做的结果是
同一个提交能以两个不同的号发出去，而 git 里那份永远不是真的（`pip install git+…@py-v3.0.0rc1`
装出来是 3.0.0）。

```bash
bash scripts/set_release_version.sh python 3.0.1      # 改 pyproject.toml
bash scripts/set_release_version.sh node   3.0.1      # 改 packages/node/package.json
# 提交、合并到 master，然后在 master 上打 tag：
git tag py-v3.0.1 && git push origin py-v3.0.1
```

⚠️ **四个 tag 要分四次 push。** GitHub 对一次 push 超过三个 tag 的操作**不产生任何事件**，
workflow 静默不跑，Actions 页面什么也看不到。3.1.0rc1 第一次就是这样丢的。

```bash
for t in py-v3.1.0 npm-v3.1.0 cli-v3.1.0 packages/go/v3.1.0; do
  git tag -a "$t" master -m "$t" && git push origin "$t"
done
```

发布 workflow 一旦 `startup_failure`（没有任何日志），先查可复用 workflow 的权限：
`release.yml` 的 `verify` job 调用 `post-release.yml`，后者每个 job 声明的权限都必须
不超过调用方授予的，GitHub 在任何 job 运行前就校验这一点，`actionlint` 查不出来。

`release.yml` 的第一个 job 跑 `scripts/release_gate.sh`，以下任一情况直接拒绝、什么都不发：

- tag 所指的提交不在 `master` 上（从功能分支打的 tag，CI 从没批准过那个提交）
- `py-v*` / `npm-v*` 的版本与 `pyproject.toml` / `package.json` 不一致
- `packages/go/vN.x.y` 的主版本与 `go.mod` 路径的 `/vN` 后缀不一致（proxy 会拒绝，
  `packages/go/v3.0.0` 曾因此被移动过一次）

CLI 的版本不在树里：`main.go` 的默认值是 `dev`，发布时由 tag 注入进二进制与镜像。

门禁之后、上传之前，每个 job 都**测即将上传的那个产物**而不是源码树：Python 装 wheel 进干净
venv、Node 装 `npm pack` 出来的 tarball、CLI 跑刚编出来的二进制 —— 全部走
`scripts/verify_published.py --artifact`，与发布后的验证是同一套检查（含 38k 条 conformance）。
PyPI 同号不可覆盖、npm 72 小时后不可 unpublish，所以坏包必须在这里拦住，而不是发出去之后
才发现号已经烧掉了。

## 预发布版

版本号带后缀（`3.1.0rc1`、`3.1.0-rc.1`、`v3.1.0-rc.1`）即视为预发布，门禁输出 `prerelease=true`：

- npm 发到 `next` dist-tag，`npm install @geotoolcn/core` 仍解析到上一个正式版
- GitHub Release 标记为 pre-release，`releases/latest/download/…` 不会指向它
- 镜像只打 tag 名与 commit sha，不动 `latest`、`3.1`、`3`
- PyPI 本身区分预发布，`pip install geotool-cn` 默认不装

```bash
git tag py-v3.1.0rc1 && git push origin py-v3.1.0rc1
```

⚠️ PyPI 上的 `3.0.0rc1` 自报 2.1.0（就是「从 tag 反写」那次事故的产物），应 yank：
`https://pypi.org/manage/project/geotool-cn/release/3.0.0rc1/`。

## 镜像 tag

| tag | 含义 |
|-----|------|
| `cli-v3.0.1` | 与 git tag 同名，不可变 |
| `3.0.1` / `3.0` / `3` | semver，后两个随正式版移动 |
| `latest` | 最近一个正式版；预发布不动它 |
| `sha-<commit>` | 构建它的提交 |

## 供应链

三个 workflow 里的每个 action 都锁到 commit SHA（注释里是对应的版本号），`.github/dependabot.yml`
每周开 PR 更新。顶层 `permissions: contents: read`，只有 `cli` job 提升到 `contents: write`
（传 Release 资产）和 `packages: write`（推镜像）。Release 二进制附 `SHA256SUMS` 与
GitHub 构建证明（`gh attestation verify geotoolcn-linux-amd64 --owner 13Cohen`）；
npm 包带 `--provenance`。

⚠️ **不要移动 `packages/go/v*` tag。** proxy.golang.org 与 sum.golang.org 一旦记录就不可变，
移动 tag 会让用户永久拿到旧内容或报 checksum mismatch。发错了就发下一个号。

## 凭据：没有

PyPI 与 npm 都通过 **Trusted Publishing（OIDC）** 发布：两个 registry 的项目设置里各登记了
`13Cohen/GeoToolCN` 的 `release.yml` 作为发布者，发布 job 用 GitHub 签发的短期 OIDC token
换取一次性上传凭据。仓库里没有 `PYPI_API_TOKEN` / `NPM_TOKEN` secret，也没有会过期的东西。

| 渠道 | 凭据 | 在哪里登记 |
|------|------|-----------|
| PyPI | OIDC | https://pypi.org/manage/project/geotool-cn/settings/publishing/ — GitHub `13Cohen/GeoToolCN`，workflow `release.yml`，environment 留空 |
| npm | OIDC | https://www.npmjs.com/package/@geotoolcn/core/access — Trusted Publisher，GitHub Actions，同上 |
| Go | — | 没有中心 registry，打 tag 即发布 |
| GHCR / Release | 内置 `GITHUB_TOKEN` | — |

两处登记都绑定 **workflow 文件名**：把 `release.yml` 改名就得同步改登记，否则发布 job 会
以 "invalid publisher" 失败。npm 的 OIDC 需要 npm ≥ 11.5.1，`release.yml` 先 `npm install -g npm@latest`。

### 本地发布

不再有本地发布路径：没有 token，`twine upload` / `npm publish` 在本机无法认证。
CI 不可用时的选择是修好 CI，或在 PyPI / npm 网页临时签发一个 token、发完立刻删除。
以前分发在 `.env` 里的 token 已在两个 registry 上撤销。

## 发布后验证

`test.yml` 里的检查全部作用于工作副本。发布不是拷贝 —— 它套用 `files` 白名单、并且只能取到
git 里有的东西。所以包可能以在发布前的树上不可见的方式损坏：

- `3.0.0rc1` 通过了 CI 的全部检查，装下来却报告自己是 `2.1.0`（那时版本还从 tag 反写）
- `packages/node/data` 是 gitignored 的，它能否到达用户，取决于发布步骤和 `files` 白名单是否
  达成一致 —— 一个全新 clone 可以通过 CI，而 tarball 里的包加载不了自己的数据集
- `go get` 只取 git 里有的东西，`go:embed` 又够不到 module 目录之外，这正是
  `packages/go/data` 必须提交的全部原因

```bash
python scripts/verify_published.py                          # 全部生态，registry 上的 latest
python scripts/verify_published.py --only node
python scripts/verify_published.py --only python --version 3.0.0rc1
```

它从各自的包仓库安装，然后对**装下来的东西**跑那 38,000+ 条 conformance。每一项检查都会先断言
被测产物解析到仓库目录之外 —— 否则它不过是换个方式再测一遍源码。

自动运行的三个时机（`.github/workflows/post-release.yml`）：

| 时机 | 作用 |
|------|------|
| `release.yml` 发布后自动调用 | 验证刚发出去的那个版本，`wait: 300` 覆盖 registry 索引延迟 |
| 每日定时 | 包可以在没有任何提交的情况下坏掉：版本被 yank、token 静默失效、tarball 被截断 |
| workflow_dispatch | 手动指定生态与版本 |

每日运行失败时会**开一个带 `post-release-failure` 标签的 issue**（持续失败则在同一 issue 下追加评论，
恢复后自动关闭）——Actions 页面里一条红色记录不会有人看见，issue 会。README 上有对应徽章。

同一次每日运行还调用 API 重新启用自己（`watchdog` job）：GitHub 会在仓库 **60 天没有提交**后
自动禁用定时 workflow，而那正是这个守护存在的意义所在的安静期。

⚠️ 新增语言时，它的 conformance adapter 必须能指向**已安装的包**，而不是写死源码路径。
Node 适配器读 `GEOTOOLCN_MODULE` 环境变量；`conformance/adapters/python.py` 之所以存在，
就是因为 `run.py --adapter python` 会把仓库根插进 `sys.path`，永远测不到已安装的版本。
