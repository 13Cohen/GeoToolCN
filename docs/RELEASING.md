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

```bash
git tag py-v3.0.0 && git push origin py-v3.0.0
```

版本号从 tag 推导后写入 `pyproject.toml` / `package.json`，仓库里不再维护第二份版本号。

## 首次发布建议先发预发布版

四条发布路径都还没有被真实 tag 验证过。先发一个预发布版，失败了不占用正式版本号：

```bash
git tag py-v3.0.0rc1 && git push origin py-v3.0.0rc1
```

## 本地凭据

发布凭据放在仓库根的 `.env`（已 gitignore），由 Tenter 的 files-to-copy 机制从主 checkout
分发到每个新建的 worktree。CI 用 GitHub secrets，这份副本用于本地手动发布和 CI 失效时的应急。

之所以两处都留，是因为凭据一旦生成就再也读不回来：npm 只显示一次，GitHub secrets 是单向的。
只存在 secrets 里，就等于没人再握有它 —— 想在本地发一次包，只能重新签发。

```bash
set -a && . .env && set +a
python -m build && twine upload dist/*                    # PyPI，twine 直接读 TWINE_*
cd packages/node && npm publish --access public           # npm，需 NODE_AUTH_TOKEN=$NPM_TOKEN
```

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

`test.yml` 里的 12 项检查全部作用于工作副本。发布不是拷贝 —— 它从 tag 重写版本号、套用
`files` 白名单、并且只能取到 git 里有的东西。所以包可能以任何一种在发布前不可见的方式损坏：

- `3.0.0rc1` 通过了全部 12 项检查，装下来却报告自己是 `2.1.0`
- `packages/node/data` 是 gitignored 的，它能否到达用户，取决于发布步骤和 `files` 白名单是否
  达成一致 —— 一个全新 clone 可以通过 CI，而 tarball 里的包加载不了自己的数据集
- `go get` 只取 git 里有的东西，`go:embed` 又够不到 module 目录之外，这正是
  `packages/go/data` 必须提交的全部原因

```bash
python scripts/verify_published.py                          # 全部生态，registry 上的 latest
python scripts/verify_published.py --only node
python scripts/verify_published.py --only python --version 3.0.0rc1
```

它从各自的包仓库安装，然后对**装下来的东西**跑那 35,086 条 conformance。每一项检查都会先断言
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
