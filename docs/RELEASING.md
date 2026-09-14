# 发布流程

四个生态各自从**自己的 tag 前缀**发布，互不牵连 —— 发一次 Python 不会把 Node 包一起带上去。
所有发布都由 `.github/workflows/release.yml` 完成，本地不需要 `npm publish` 或 `twine`。

| 生态 | tag | 发布到 | 凭据 |
|------|-----|--------|------|
| Python | `py-v3.0.0` | PyPI `geotool-cn` | `PYPI_API_TOKEN` |
| Node | `npm-v3.0.0` | npm `@geotoolcn/core` | `NPM_TOKEN` |
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

## 本地凭据

发布凭据放在仓库根的 `.env`（已 gitignore），由 Tenter 的 files-to-copy 机制从主 checkout
分发到每个新建的 worktree。CI 用 GitHub secrets，这份副本用于本地手动发布和 CI 失效时的应急。

之所以两处都留，是因为凭据一旦生成就再也读不回来：npm 只显示一次，GitHub secrets 是单向的。
只存在 secrets 里，就等于没人再握有它 —— 想在本地发一次包，只能重新签发。

```bash
set -a && . .env && set +a
rm -rf dist && python -m build && twine upload dist/*     # PyPI，twine 直接读 TWINE_*；先清 dist/，否则旧产物一起上传
cd packages/node && node scripts/sync-data.mjs \
  && npm publish --access public \
       --//registry.npmjs.org/:_authToken="$NPM_TOKEN"    # npm 本身不读 NODE_AUTH_TOKEN，那是 setup-node 写 .npmrc 用的
```

本地发布绕过了门禁与产物验证，只在 CI 不可用时使用；发之前至少跑一遍
`python scripts/verify_published.py --only <生态> --version <版本> --artifact <产物>`。

| 渠道 | 变量 | 说明 |
|------|------|------|
| PyPI | `TWINE_USERNAME` / `TWINE_PASSWORD` | `__token__` + `pypi-…` |
| npm | `NPM_TOKEN` | scope 限定 `@geotoolcn`，已勾 bypass 2FA |
| Go | — | 没有中心 registry，打 tag 即发布 |
| GHCR / Release | — | CI 用内置 `GITHUB_TOKEN`；本地用 `gh auth token` 临时取，不留长期副本 |

⚠️ **新建 worktree 后先 `chmod 600 .env`**。主 checkout 里是 600，但拷贝过程不保留权限位，
落到 worktree 里是 644 —— 同机其他用户可读。这不是一次性问题，每个新 worktree 都会重现。

## ⚠️ NPM_TOKEN 有两个死线

npm 的 Granular Access Token **只要带写权限，最长就是 90 天**（默认更短，只有 7 天）。
当前这个 token 于 **2026-12-09 过期**，过期后 `npm-v*` tag 会以 401 失败，
而其他三条发布路径不受影响 —— 也就是说故障会以「只有 npm 发不出去」的形式出现。

更硬的那条死线：**2027 年 1 月起，npm 将移除 granular token「直接发布新版本」的能力**
（签发页面上的原话）。届时续期也没用 —— token 还在有效期内，但发不了包。
剩下的选项只有 Trusted Publishing，或者改用 `--access stage-only` 再走一道人工提升。

所以迁移到 Trusted Publishing 不是「更好的做法」，是**有明确期限的必做项**。

续期：

1. https://www.npmjs.com/settings/<用户名>/tokens → Generate New Token → Granular Access Token
2. 名称 `geotoolcn-ci-release`；勾选 bypass 2FA；权限 Read and write；scope 选 `@geotoolcn`
3. `gh secret set NPM_TOKEN --repo 13Cohen/GeoToolCN`（从 stdin 读，别贴进 shell 历史）
4. 同步更新主 checkout 的 `.env`，然后在旧 token 页面把它删掉 —— 一个没人握有明文、
   却仍能发布的 token，留着只有风险没有用处

**更好的解法是彻底不要这个 token**：npm 已支持 Trusted Publishing（OIDC），
在 npm 包设置里绑定本仓库与 `release.yml` 后即可删除 `NPM_TOKEN`，也就没有过期这回事了。
之所以现在没这么做，是因为它要求包**已经存在**才能配置发布者 —— 首次发布必须靠 token。
第一次 `npm-v*` 成功之后就应该切过去。

PyPI 同理（`release.yml` 里已写明为什么现在显式传 token 而非用 OIDC）。

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

⚠️ 新增语言时，它的 conformance adapter 必须能指向**已安装的包**，而不是写死源码路径。
Node 适配器读 `GEOTOOLCN_MODULE` 环境变量；`conformance/adapters/python.py` 之所以存在，
就是因为 `run.py --adapter python` 会把仓库根插进 `sys.path`，永远测不到已安装的版本。
