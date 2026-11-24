---
name: picora-plugin-dev
description: 把图床的上传与删除接口适配成 Picora 原生插件（plugin.json + uploader.json），涵盖可行性判定、抓包摸接口、配置字段与属性标签（role）、权限约束、预检回放、打包 ZIP，以及在用户愿意开源时创建插件仓库、发布 Release、Fork 模块仓库并提交 registration.json 的 PR。用于新增或修改 Picora 图床插件；不用于 Picora 客户端的 Flutter 功能开发，也不适用于必须执行站点 JS、验证码或浏览器指纹才能上传的目标。
---

# Picora 插件开发

自用交付一份可安装的 `.picora-plugin.zip`；开源投稿再加一条模块仓库登记。
两件事都不是爬虫脚本。

## 权威资料

官方文档在 Picora 模块仓库 `picora-plugins` 的 `docs/` 目录：

| 文档 | 内容 |
| --- | --- |
| [docs/PLUGINS.md](https://github.com/Alnitak44/picora-plugins/blob/main/docs/PLUGINS.md) | 插件协议全文：包结构、权限、请求、响应、前置请求、删除、资源上限 |
| [docs/插件提交流程.md](https://github.com/Alnitak44/picora-plugins/blob/main/docs/%E6%8F%92%E4%BB%B6%E6%8F%90%E4%BA%A4%E6%B5%81%E7%A8%8B.md) | 投稿、审核、更新、退出收录、常见报错 |
| [CONTRIBUTING.md](https://github.com/Alnitak44/picora-plugins/blob/main/CONTRIBUTING.md) | 首次收录的摘要与检查失败处理 |
| [docs/插件开放说明.md](https://github.com/Alnitak44/picora-plugins/blob/main/docs/%E6%8F%92%E4%BB%B6%E5%BC%80%E6%94%BE%E8%AF%B4%E6%98%8E.md) | 协议版本与能力概览 |
| [examples/io.github.example.picora.demo.json](https://github.com/Alnitak44/picora-plugins/blob/main/examples/io.github.example.picora.demo.json) | 登记文件示例 |
| [scripts/build_catalog.py](https://github.com/Alnitak44/picora-plugins/blob/main/scripts/build_catalog.py) | 目录构建与 CI 校验的实际规则 |

模块仓库：https://github.com/Alnitak44/picora-plugins
（也可从 Picora 客户端「插件 → 模块仓库」打开）。

空白模板在客户端源码仓库的 `plugins/template`；客户端解析逻辑在
`lib/app/plugins/` 下的 `plugin_manifest.dart`、`plugin_package.dart`、
`uploader_registry.dart`。能拿到客户端源码时以它为准，拿不到时以官方文档和
`validate` 结果为准。

本 Skill 的 `references/` 是离线速查，覆盖日常需要的字段与规则；协议变更时以官方文档为准。

## 输入

一个图床**地址**只能确定主机名，不足以写出正确的成功判定。开始前确认：

| 输入 | 是否必需 | 用途 |
| --- | --- | --- |
| 图床地址（含子目录） | 必需 | 请求主机与 `baseUrl` |
| 可用凭证（Token / 账号 / Cookie）或公开 API 文档 | 必需 | 抓一次真实上传，确认鉴权与响应 |
| 上传成功与失败的原始响应 | 必需 | 映射 `url`、`success`、错误字段 |
| 一张测试图片（100 KB 内） | 必需 | 真传与删除验证 |
| 公开 GitHub 仓库 | 发布时需要 | 存放 Release 与 ZIP |

拿不到凭证也没有文档时，先向用户索取；不要猜接口，也不要为了「能装上」编造响应路径。

## 交付物

自用只需 1、2、4、5；投稿再加 3。

1. 插件目录：`plugin.json`、`uploader.json`、`readme.md`、`LICENSE`、`assets/icon.svg`
2. `releases/<name>-<version>.picora-plugin.zip` 与 SHA256
3. `registrations/<id>.json` 登记文件（投稿时）
4. `readme.md` 用户教程：申请凭证步骤、字段说明、错误对照表
5. 实测记录：成功上传、失败提示（错误凭证或超限图片）、删除（若声明）

## 流程

### 0. 先确认交付范围

只在用户明确表达「开源 / 投稿 / 上架 / 让别人也能装 / 提 PR」时走投稿链路。
用户说「自己用」「本地装」「先试试」时，只交付插件目录和 ZIP，不要主动建仓库、
不要提 PR、不要索取 GitHub 授权；可以最后用一句话说明投稿需要什么，让用户自己决定。

判定含糊时按自用处理，不必追问；用户后续要投稿，再从第 8 步接上。

两条路径共用第 1–7 步，只在第 8 步分开：

| 用户意图 | 第 8 步 |
| --- | --- |
| 自用 | 交付 ZIP 与安装说明，结束 |
| 开源投稿 | 建仓库、发 Release、写登记、提 PR，见 [references/contribution.md](references/contribution.md) |

### 1. 判定可行性

先用 [references/host-discovery.md](references/host-discovery.md) 摸清接口，再决定做不做：

| 目标情况 | 结论 |
| --- | --- |
| multipart / JSON / binary 单次上传 | 直接适配，`http-v2` |
| 先登录或先取 token | `prepare` + `credential-cache` + `exports` |
| 需要时间戳、HMAC 或 Basic 鉴权 | `hmacSha256` / `sha256` / `basicAuth` |
| 同一图床有多种登录方式 | `authModes` + `auth-modes`（v2，最低 1.1.0） |
| 上传后要轮询任务状态 | 做不到，停止并说明 |
| 依赖 JS 加密、验证码、浏览器指纹 | 不做原生插件，说明原因 |
| 只有 PicGo / Node 插件 | 不能直接安装，需重写 |

判定不通过时给出具体依据（哪个字段无法生成、哪一步需要执行脚本）。

### 2. 生成骨架

```bash
python scripts/picora_plugin.py new --slug easyimages \
  --id io.github.<你的用户名>.picora.easyimages \
  --name "简单图床" --author "<你的用户名>" \
  --repo <你的用户名>/picora-plugin-easyimages \
  --host img.example.com --path /api/index.php --endpoint --auth token
```

生成插件目录与初始 `registration.json`。随后按抓包结果改 `uploader.json`，
不要直接套用别人的配置。

### 3. 写 uploader.json

- 自建地址用 `${normalizeBaseUrl(config.baseUrl)}`，不要写死域名。
- `network` 用明确主机或 `config.<非 secret 字段>`。v2 声明 `delete` 时
  `deleteUploadedFile` 必须为 `true`；`requires` 建议写 `scoped-delete`，
  客户端不强制，但官方文档要求声明使用的能力。
- HTTP 200 不代表成功：站点返回 200 + `result: failed` 时必须写
  `success: {path: "result", equals: "success"}`。
- 响应路径只支持 `data.url`、`items[0].url`、`[0].src` 这类写法。
- 删除链接在响应里时优先 `deleteKey`；`deleteUrl` 在上传阶段就会校验，
  站点关闭删除功能时会导致上传整体失败。
- 同一图床有多种登录方式（游客 / Token / 账号密码）时用 `authModes` 合并为一个插件：
  根级写公共 `config` 与 `prepare`，每种方式各自写 `config` / `prepare` / `upload` / `delete`。
  字段键在公共与各方式之间不能重名，`requires` 必须含 `auth-modes`。

字段级约束见 [references/uploader-schema.md](references/uploader-schema.md)。

### 4. 配置字段与 role

`config[].role` 决定插件列表标签，只影响展示，不影响表单、请求或权限：

| 场景 | `role` | 标签 |
| --- | --- | --- |
| 自建图床地址、S3 Endpoint | `endpoint` | 自定义地址 |
| API Key、AccessKey、上传令牌 | `token` | Token |
| 用户名 / 邮箱（配合 secret 密码） | `account` | 账号 |
| bucket、路径、开关等普通参数 | 不写 | — |

规则：

- 存在 `required` 的 `secret` 字段，或存在 `token` / `account` 角色 → 显示「需认证」。
- 有 `authModes` 时把所有方式的字段合并起来判断「需认证」与「云删除」。
- 声明 `delete` → 自动「云删除」；版本号带预发布后缀 → 自动「测试版」。
- 首次使用 `role` 要把 `minAppVersion` 抬到 `1.0.8`；调整 `role` 不需要重新审核权限。
- 首次使用 `authModes` 要把 `minAppVersion` 抬到 `1.1.0`。
- 字段需要限制输入字符时用 `config[].input`（仅 text/secret）：`allow` 必须是
  单个字符集 `[...]`，`message` ≤ 80 字；不声明能力，但要把 `minAppVersion`
  抬到 `1.1.0`，`register` 会自动推导。细节见 [references/uploader-schema.md](references/uploader-schema.md)。
- 新插件显式写 `role`。旧插件未写时目录按 key/label 兜底推断，不要依赖这个兜底。
- 没有配置字段却需要凭证的旧插件，可在登记文件用 `tags`（`token` / `account` / `custom-url`）过渡，补上 `role` 后删除。

细节见 [references/roles-and-tags.md](references/roles-and-tags.md)。

### 5. 预检与回放

```bash
python scripts/picora_plugin.py validate <插件目录>
python scripts/picora_plugin.py validate <插件目录> --registration <插件目录>/registration.json

# 默认只渲染请求，不联网
python scripts/picora_plugin.py replay <插件目录> -c config.json -i test.jpg
python scripts/picora_plugin.py replay <插件目录> -c config.json -i test.jpg --send
```

预检覆盖元信息、未知字段、能力与版本匹配、配置字段、权限、模板变量、
响应条件与 ZIP 约束。它是预检不是证明；新规则要回客户端源码
`lib/app/plugins/plugin_manifest.dart` 核对，拿不到源码时以官方文档为准。

带 `--registration` 时额外按模块仓库 CI 的口径检查违规用语与外链（`readme.md`、
`homepage` 只能指向 GitHub、插件请求主机或 `allowedLinks`），并把文件名、
权限一致性、`minAppVersion` 一起核对。不带时这些只作为提醒，方便自用交付。

回放只支持 `upload`，且不执行 `prepare`。含 `prepare` 的插件加 `--send` 也只渲染
请求，必须在客户端实测；`steps.*` 会原样保留成占位符。
插件含 `authModes` 时默认回放第一种方式，可用 `--auth-mode <id>` 指定。

### 6. 打包

```bash
python scripts/picora_plugin.py pack <插件目录>
```

输出 `releases/<name>-<version>.picora-plugin.zip` 并打印 SHA256。
ZIP 根目录直接放文件，`tools/`、`docs/`、`releases/`、`registration.json` 不进包。
投稿时必须用 `validate --zip <包> --registration <登记>` 交叉核对 ZIP 内
`plugin.json` 的 `id` 与登记文件一致；只改登记文件不重发包，CI 会拒绝。

### 7. 客户端验收

发布前必须先在客户端跑通，避免把坏包发成 Release。

1. 本地 ZIP 安装，确认元信息、图标、标签正确。
2. 新建两组配置，分别上传，确认互不串用。
3. 用错误 Token / 超限图片触发失败，确认提示可读。
4. 若声明删除：在图片详情删一张，确认云端文件消失。
5. 覆盖安装新版本，确认配置保留、版本递增。

### 8. 投稿（仅当用户要开源）

先用 `publish` 预演，确认步骤与仓库地址无误后再执行：

```bash
# 预演：只打印将要执行的步骤，不产生任何外部动作
python scripts/picora_plugin.py publish <插件目录> \
  --repo <owner>/<repo>

# 执行；创建公开仓库、Fork、开 PR 会对外可见
python scripts/picora_plugin.py publish <插件目录> \
  --repo <owner>/<repo> --execute

# 某步失败后只补剩余步骤
python scripts/picora_plugin.py publish <插件目录> --only release,register,pr --execute
```

`--catalog` 默认指向官方模块仓库，只有模块仓库迁移或自建时才需要覆盖。

脚本会先检测 `git` / `gh` 与登录状态：

| 环境 | 行为 |
| --- | --- |
| `gh` 已登录、网络可用 | 依次执行 init、commit、建公开仓库、push、Release、生成登记、Fork、提 PR |
| 有 `git` 无 `gh` 或未登录 | 自动切到指导模式，输出可复制命令、网页入口与登记文件全文，不擅自安装工具 |
| 无 git 或无网络 | 同样输出指导模式清单 |

能自动化时仍保留人工确认点：`--execute` 之前必须先说明将创建公开仓库、Fork 和开 PR。
失败时脚本会列出已完成步骤，按提示用 `--only` 继续，不要整体重跑。

手动操作的完整命令与 REST API 备选见 [references/contribution.md](references/contribution.md)。

要点：

- `releaseRepository` 写 `owner/repo`，不是 URL；`plugin.json` 的 `repository` 必须是 `https://github.com/<owner>/<repo>`。
- 新插件 ID 用 `io.github.<GitHub 用户名小写>.<插件名>`，用户名里的连字符必须保留
  （`enddream-zm` 不能写成 `enddreamzm`），发布后不可改。
- `approvedPermissions` 与 `uploader.json` 的 `permissions` 完全一致（四个布尔值都要写，`network` 顺序无关）。
- `minAppVersion` 覆盖插件用到的能力：`role` ≥ 1.0.8，`conditional-json-fields` ≥ 1.0.4，
`authModes` / `config[].input` ≥ 1.1.0；`register` 会自动推导。
- 教程和主页只能链接 GitHub、插件自身请求主机或登记文件 `allowedLinks` 里的域名。
- 改网络目标、不安全 HTTP 或云端删除权限时，先改登记文件提 PR，审核通过后再发新 ZIP。
- 草稿和预发布 Release 不收录；不要用 GitHub 自动生成的源码 ZIP。
- `index.json` 由模块仓库生成，不要手改。

CI 报错对照与退出收录见 [references/publishing.md](references/publishing.md)。

## 硬规则

- 未知字段、未知能力、`runtime` 与 `schemaVersion` 不匹配都会在安装阶段失败。
- `config` ≤ 30 项；键名 `^[A-Za-z][A-Za-z0-9_]{0,39}$`；`select` 必须有非空 `options`。
- `network` 1–16 项；v2 不支持通配；`config.<key>` 只能引用非 `secret` 字段。
- 上传 `POST/PUT/PATCH`，前置 `GET/HEAD/POST`，删除 `GET/POST/DELETE`；`GET/HEAD` 不能带 body。
- `timeoutSeconds` 5–300；`successStatuses` 只能 2xx。
- 请求头不能设置 `Host`、`Content-Length`、`Connection`、`Transfer-Encoding`、`Upgrade`、`Proxy-*`。
- 删除模板只能读 `${upload.url}`、`${upload.deleteKey}`、`${upload.deleteUrl}`；
  v2 删除不能再读配置、步骤、文件或资源（v1 旧格式允许读 `config.*`）。
- v2 删除必须在请求某处出现 `${upload.deleteKey}` 或 `${upload.deleteUrl}`，
  否则客户端报「删除必须使用单张图片的删除凭证或链接」。
- `${file.path}` 仅 v1 可用；v2 用 `file.name` / `bytes` / `base64` / `mime`。
- 前置请求不能读图片，只能读配置、包内资源和更早步骤的导出。
- `authModes` 仅 v2：1–8 项，`id` 匹配 `^[a-z][a-z0-9-]{0,31}$` 且唯一，
  每项必须有 `config` 与 `upload`；字段键在公共与各方式之间不能重名，
  也不能叫 `authMode`（客户端保留）。声明后根级 `upload` / `delete` 不生效。
- ZIP ≤ 10 MB、≤ 128 条目、解压 ≤ 20 MB、单文件 ≤ 2 MB；`readme.md` ≤ 512 KB；图标 ≤ 1 MB。
- `plugin.json` 与入口 JSON 各 ≤ 1 MB；ZIP 里必须有 `assets/` 目录（可以为空），
  否则安装阶段直接失败。
- `description` ≤ 160 字，`name` ≤ 60，`author` ≤ 80，`version` 为 SemVer。

## 常见踩坑

- `baseUrl` 要含子目录，但不能带 `/api/index.php` 之类入口路径。
- `deleteKey` 必须是标量；返回数组或对象会失败。
- 站点关闭「用户删除链接」时该字段可能是固定文案，删除前要判空。
- 只改源码不发新 Release，目录不会更新；同名版本不能覆盖已发布附件。
- `readme.md` 里的外链会被 CI 校验，截图尽量放 `assets/`。
- 名称、简介、作者、教程不得出现引流或诈骗用语，命中直接构建失败。

## 脚本

`scripts/picora_plugin.py`，仅标准库，Python 3.8+。命令在 Skill 目录下执行，
或把脚本路径换成绝对路径：

```text
new       按图床信息生成插件骨架与初始登记文件
validate  预检插件目录，可加 --zip 与 --registration
register  生成登记文件，自动推导版本与权限，可加 --allowed-links / --asset-prefix
publish   检测环境后建仓、发 Release、Fork、提 PR；默认只预演
pack      校验并生成 .picora-plugin.zip
replay    按 uploader.json 渲染并可选发送一次真实上传
```
