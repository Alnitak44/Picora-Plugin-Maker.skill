# 打包、发布与投稿

模块仓库只收录登记信息，源码和 ZIP 由作者维护在自己的公开仓库。
具体执行命令见 [contribution.md](contribution.md)；本文只说明规则与校验。

## 打包

```bash
python scripts/picora_plugin.py pack <插件目录>
```

产物：`releases/<name>-<version>.picora-plugin.zip`，同时打印 SHA256。

ZIP 根目录直接是 `plugin.json`、入口 JSON、`readme.md`、`assets/`，不要套一层
文件夹。以下内容不进 ZIP：

```text
tools/  docs/  releases/  tests/  .git/  .github/  registration.json  *.zip
```

约束：≤ 10 MB、≤ 128 条目、解压 ≤ 20 MB、单文件 ≤ 2 MB、
`readme.md` ≤ 512 KB、图标 ≤ 1 MB。

## 发布 Release

1. 插件的源码放在**独立的公开 GitHub 仓库**，不能放在模块仓库里。
2. 打正式 Release（不能是草稿或预发布），附件上传 `.picora-plugin.zip`。
3. 附件名建议 `<name>-<version>.picora-plugin.zip`，例如
   `easyimages-1.1.0.picora-plugin.zip`。注意版本号后是**点号**。
4. 不要用 GitHub 自动生成的 Source code ZIP。
5. 同一版本不能覆盖附件；改内容必须递增 `version` 再发新 Release。

## 登记文件

首次投稿向 `picora-plugins` 提交 `registrations/<完整插件 ID>.json`：

```json
{
  "id": "io.github.alice.picora.easyimages",
  "releaseRepository": "alice/picora-plugin-easyimages",
  "minAppVersion": "1.0.8",
  "approvedPermissions": {
    "network": ["config.baseUrl"],
    "readSelectedFile": true,
    "allowInsecureHttp": false,
    "deleteUploadedFile": false
  }
}
```

| 字段 | 规则 |
| --- | --- |
| `id` | 与 `plugin.json` 完全一致（用户名保留连字符，`enddream-zm` 不能写成 `enddreamzm`）；文件名必须也是 `<id>.json` |
| `releaseRepository` | `owner/repo`，不是 URL |
| `minAppVersion` | 覆盖插件用到的全部能力，见下表 |
| `approvedPermissions` | 与 `uploader.json` 的 `permissions` 完全一致 |
| `allowedLinks` | 可选；教程需要外链时的已审核主机名数组 |
| `assetPrefix` | 可选；附件名前缀，用于同一 Release 有多个 ZIP 时区分 |
| `tags` | 仅旧插件兜底；有新版本后应改用 `role` |

`approvedPermissions` 必须写全四个布尔值，`network` 顺序无关；
插件里写的是主机名，不是 `https://host/`。

`plugin.json` 的 `repository` 必须是 `https://github.com/<owner>/<repo>`，
与 `releaseRepository` 指向同一仓库根地址，不能带 `/tree/main/…`。

## minAppVersion

| 用到的能力 | 最低版本 |
| --- | --- |
| 基础 `http-v1` | `1.0.0` |
| `schemaVersion: 2`、`prepare`、`delete` | `1.0.1` |
| `conditional-json-fields` | `1.0.4` |
| `config[].role` | `1.0.8` |
| `authModes`（`auth-modes`） | `1.1.0` |
| `config[].input`（输入限制） | `1.1.0` |

取最高要求。`register` 命令会自动推导。

## 首次投稿步骤

1. 本地 ZIP 在 Picora 里安装、上传、删除全部走通。
2. 在自己的公开仓库发布 Release 并上传 ZIP。
3. Fork `picora-plugins`，新增 `registrations/<id>.json`。
4. 向 `main` 提交 PR，说明插件用途与凭证范围。
5. 等 CI 校验与维护者审核，合并后目录自动生成。

不需要填写下载地址、大小或 SHA256，也不要把 ZIP 复制进模块仓库。

## 更新已收录的插件

| 改动 | 做法 |
| --- | --- |
| 只改文案、图标、请求逻辑 | 递增 `version`，发新 Release，目录自动同步 |
| 改网络目标、`allowInsecureHttp`、云端删除权限 | 先提 PR 改登记文件并说明，审核通过后再发 ZIP |
| 开始使用 v2、条件 JSON 字段、`role`、`authModes` | PR 抬高 `minAppVersion`，否则旧客户端安装失败 |
| 改名、换作者、改简介 | 随新版本发布即可，不用改登记文件 |

目录只读 Release 附件，只改源码仓库不会生效。覆盖安装会保留用户配置，
但云端删除授权默认关闭，需要用户重新开启。

## 文案与链接审核

以下内容会被构建检查，命中即失败：

- 名称、简介、作者、`readme.md` 含引流或诈骗用语（加联系方式、领红包、破解、代充、刷单等）。
- `readme.md` 或 `homepage` 指向 GitHub、插件自身请求主机、`allowedLinks` 之外的域名。
- 教程截图请放 `assets/` 并用相对路径引用，避免外链被拒。
- `network` 含 `*` 的插件会告警，首次收录和权限变更需人工确认。

`mark` 需要 1–3 个字符，超长会构建失败。

## CI 报错对照

| 报错 | 处理 |
| --- | --- |
| `no matching published ZIP release` | 发布正式 Release 并上传 `.picora-plugin.zip` 附件 |
| `filename must match plugin id` | 登记文件命名为 `<完整 id>.json` |
| `id must use the GitHub owner's io.github namespace` | id 改为 `io.github.<owner 小写保留连字符>.<插件名>`；`io.github.enddreamzm.picora.beeimg` 这类漏连字符写法会被拒 |
| `发布的 ZIP 中 plugin.json 的 id 为 …` | 重新 `pack` 并上传新附件，确保 ZIP 内 id 与登记文件一致；不能只改登记文件不重发 ZIP |
| `permissions changed; update registration through review` | 登记文件 `approvedPermissions` 与插件对齐，并走审核 |
| `package repository differs from releaseRepository` | `repository` 改为 `https://github.com/<owner>/<repo>` |
| `ZIP is missing required root files` | ZIP 根目录直接放 `plugin.json`、入口、`readme.md`、`assets/` |
| `published ZIP changed without a new version` | 递增 `version` 后重新发布 |
| `readme.md 里的链接指向 …` | 删除外链或加 `allowedLinks` |
| `含违规内容` | 修改文案后递增版本重新发布 |

失败详情：模块仓库 Actions → Build plugin catalog → 展开失败步骤，
找 `catalog build failed:` 之后的原因。不要手改 `index.json` 绕过。

## 退出收录

删除 `registrations/<id>.json` 并提交 PR，注明「退出收录」和插件 ID；
不便提 PR 可发 Issue。退出不会卸载用户已安装的插件，也不删除用户数据。
恢复收录按首次投稿流程重新提交并接受审核。

## 发布前检查单

- [ ] `validate` 无 error，`--zip` 与 `--registration` 都通过
- [ ] 真机上传成功，图片 URL 可直接打开
- [ ] 错误凭证、超限图片能显示中文提示
- [ ] 删除（若声明）在客户端实测成功
- [ ] `readme.md` 字段说明与 `uploader.json` 一致，无违规外链
- [ ] Release 附件名以 `.picora-plugin.zip` 结尾
- [ ] 登记文件 id、仓库、权限、`minAppVersion` 与插件一致
