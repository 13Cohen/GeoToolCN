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

## ⚠️ NPM_TOKEN 会过期

npm 的 Granular Access Token **只要带写权限，最长就是 90 天**（默认更短，只有 7 天）。
当前这个 token 于 **2026-12-09 过期**，过期后 `npm-v*` tag 会以 401 失败，
而其他三条发布路径不受影响 —— 也就是说故障会以「只有 npm 发不出去」的形式出现。

续期：

1. https://www.npmjs.com/settings/<用户名>/tokens → Generate New Token → Granular Access Token
2. 名称 `geotoolcn-ci-release`；勾选 bypass 2FA；权限 Read and write；scope 选 `@geotoolcn`
3. `gh secret set NPM_TOKEN --repo 13Cohen/GeoToolCN`（从 stdin 读，别贴进 shell 历史）

**更好的解法是彻底不要这个 token**：npm 已支持 Trusted Publishing（OIDC），
在 npm 包设置里绑定本仓库与 `release.yml` 后即可删除 `NPM_TOKEN`，也就没有过期这回事了。
之所以现在没这么做，是因为它要求包**已经存在**才能配置发布者 —— 首次发布必须靠 token。
第一次 `npm-v*` 成功之后就应该切过去。

PyPI 同理（`release.yml` 里已写明为什么现在显式传 token 而非用 OIDC）。
