# 开源投稿：从本地插件到已合并的登记

只在用户明确要开源、上架或提 PR 时执行。自用交付止于 ZIP。

下文命令中的 `scripts/picora_plugin.py` 指本 Skill 目录下的脚本，
执行时按实际安装位置替换路径。

## 首选：`publish` 命令

```bash
python scripts/picora_plugin.py publish <插件目录> \
  --repo <owner>/<repo>                          # 预演
python scripts/picora_plugin.py publish <插件目录> \
  --repo <owner>/<repo> --execute                # 执行
```

`--catalog` 默认是官方模块仓库，只有迁移或自建目录时才覆盖。

脚本自己检测 `git`、`gh` 与登录态，再决定自动执行还是输出指导步骤。
下面的内容是它背后的等价手工流程，用于脚本不可用、需要定制或排查时参考。

开始前确认三项，缺一项就改为指导模式，不要硬做：

| 条件 | 检查 |
| --- | --- |
| GitHub 登录态 | `gh auth status` |
| 用户同意公开源码 | 明确答复 |
| 网络可达 github.com | 能 clone / push |

## 能力矩阵

| 步骤 | 有 gh 且已登录 | 有 git 无 gh | 无环境 |
| --- | --- | --- | --- |
| 建插件仓库并推送 | 自动 | 给命令 | 给命令 |
| 发布 Release 上传 ZIP | `gh release create` | 网页步骤 | 网页步骤 |
| Fork 模块仓库 | `gh repo fork` | 网页 Fork | 网页 Fork |
| 生成 registration.json | 自动 | 自动 | 给文件全文 |
| 提交 PR | `gh pr create` | 网页 Compare | 网页步骤 |

创建公开仓库、Fork、开 PR 是对外可见动作：执行前说明将做什么，完成后报告链接。
失败时不要静默重试，把命令和报错交给用户。

`gh` 不是必需依赖。没有 `gh` 时用 `git` + GitHub 网页即可完成全部步骤；
只有仓库和 PR 数量多、需要反复更新时才值得装。安装方式遵循用户自己或项目
已有的工具约定，不要擅自装到系统目录。

需要脚本化但不想装 `gh` 时，可用 GitHub REST API：

```bash
# 建仓库（需 repo 权限的 PAT）
curl -sS -X POST https://api.github.com/user/repos \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -d '{"name":"picora-plugin-<name>","private":false}'

# 发布 Release（先建 tag 并 push）
curl -sS -X POST https://api.github.com/repos/<owner>/<repo>/releases \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -d '{"tag_name":"v1.0.0","name":"v1.0.0"}'

# 上传附件
curl -sS -X POST \
  "https://uploads.github.com/repos/<owner>/<repo>/releases/<id>/assets?name=<name>-1.0.0.picora-plugin.zip" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Content-Type: application/zip" \
  --data-binary @releases/<name>-1.0.0.picora-plugin.zip
```

Token 只放在环境变量或命令参数里，不要写进仓库、脚本或 Release。

## 1. 准备插件仓库

插件独立成仓，不要把源码或 ZIP 放进 `picora-plugins`。

```bash
cd <插件目录>
git init
git add .
git commit -m "feat: <name> <version>"
git branch -M main
gh repo create <owner>/<repo> --public --source=. --remote=origin --push
```

没有 `gh` 时，先让用户建空仓库，再执行：

```bash
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

推送前检查：

- `plugin.json` 的 `repository` 是 `https://github.com/<owner>/<repo>`，与登记的 `releaseRepository` 一致。
- `.gitignore` 含 `releases/`、`__pycache__/`、`*.zip`。
- 仓库里没有真实 Token、Cookie 或用户图片。

## 2. 发布 Release

```bash
python scripts/picora_plugin.py pack <插件目录>
gh release create v<version> \
  releases/<name>-<version>.picora-plugin.zip \
  --title "<name> <version>" --notes "见 readme.md"
```

要求：正式 Release（不能 draft 或 prerelease）；附件名以 `.picora-plugin.zip` 结尾；
不要用 GitHub 自动生成的 Source code；同版本不能覆盖，改内容就递增 `version`。

没有 `gh` 时：仓库页 → Releases → Draft a new release → 选 tag → 上传 ZIP →
确认不是 pre-release → Publish。

## 3. 生成登记文件

```bash
python scripts/picora_plugin.py register <插件目录> --repo <owner>/<repo>
```

输出 `registration.json`，形如：

```json
{
  "id": "io.github.<owner>.picora.<name>",
  "releaseRepository": "<owner>/<repo>",
  "minAppVersion": "1.0.8",
  "approvedPermissions": {
    "network": ["config.baseUrl"],
    "readSelectedFile": true,
    "allowInsecureHttp": false,
    "deleteUploadedFile": false
  }
}
```

自检：

- `id` 与 `plugin.json` 一致，落地文件名必须是 `<id>.json`。
  投稿 ID 里的 GitHub 用户名必须保留连字符：`ENDDREAM-ZM` → `enddream-zm`，
  不能写成 `enddreamzm`。
- `releaseRepository` 是 `owner/repo`，不带协议和域名。
- Release ZIP 内 `plugin.json` 的 `id` 必须与登记文件一致；只改登记文件不改包
  会导致 CI 报「发布的 ZIP 中 plugin.json 的 id 为 …」。
- 四个权限布尔值齐全，`network` 与插件一致，顺序无关。
- `minAppVersion` 取 `role` 1.0.8、`http-v2` 1.0.1、条件 JSON 字段 1.0.4、
  多登录方式 `authModes` 1.1.0、输入限制 `config[].input` 1.1.0 的最高项。
- 教程需要外链时补 `allowedLinks`，只写主机名。

先本地校验：

```bash
python scripts/picora_plugin.py validate <插件目录> --registration registration.json
```

## 4. Fork 与提 PR

```bash
gh repo fork Alnitak44/picora-plugins --clone --remote
cd picora-plugins
git checkout -b add-<name>
mkdir -p registrations
cp ../registration.json registrations/<id>.json
git add registrations/<id>.json
git commit -m "feat: add <name> plugin"
git push -u origin add-<name>
gh pr create --repo Alnitak44/picora-plugins --base main \
  --title "Add <name> plugin" \
  --body "<name> 图床插件，支持 <能力>。凭证仅用于 <范围>。"
```

只新增 `registrations/` 下的文件，不动 `index.json`、`plugins/` 或他人的登记。

没有 `gh` 时：

1. 网页 Fork https://github.com/Alnitak44/picora-plugins 。
2. 在自己的 Fork 建分支，添加 `registrations/<id>.json` 并提交。
3. Pull requests → New pull request → base 选上游 `main`。
4. 填写标题与说明后提交。

PR 说明写清：插件用途、请求域名、凭证类型、是否支持云端删除。

## 5. 等 CI 与审核

PR 会跑 `Validate proposed catalog`。失败时：

1. Actions → 失败运行 → build 步骤。
2. 找 `catalog build failed:` 之后的原因。
3. 按 [publishing.md](publishing.md) 的报错对照修正。
4. 若要改插件内容，递增版本、重发 Release，再更新 PR。

合并后目录自动生成；客户端缓存 12 小时，可手动刷新。

## 常见阻塞

| 情况 | 处理 |
| --- | --- |
| `gh` 未登录 | `gh auth login`，或改指导模式 |
| 无权限建公开仓库 | 用户先建空仓库，再 `git remote add` 推送 |
| 网络不可达 | 不重试，输出命令让用户本地执行 |
| Fork 已存在 | `git remote add upstream` 后同步 main |
| 分支落后上游 | `git fetch upstream && git rebase upstream/main` |
| 同插件已有 PR | 在原 PR 上更新，不要重复投稿 |

## 不要做

- 不要把 Token、Cookie 或测试图片提交进仓库或 Release。
- 不要 force push 到上游 `main` 或他人的分支。
- 不要在用户只说「自己用」时创建公开仓库或提 PR。
- 不要改已合并的登记文件绕过审核；权限变化走新 PR。
