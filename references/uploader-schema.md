# uploader.json 速查

完整说明以 Picora 模块仓库 `picora-plugins` 的 `docs/PLUGINS.md` 为准；
这里只放写插件时最常查的约束。

## 顶层

```json
{
  "schemaVersion": 2,
  "requires": ["response-conditions", "scoped-delete"],
  "permissions": {"network": ["config.baseUrl"], "readSelectedFile": true},
  "config": [],
  "prepare": [],
  "authModes": [],
  "upload": {},
  "delete": {}
}
```

| 键 | 适用范围 | 要点 |
| --- | --- | --- |
| `schemaVersion` | 必填 | `1` 对应 `http-v1`，`2` 对应 `http-v2` |
| `permissions` | 必填 | 见下表 |
| `config` | 必填 | 最多 30 项，无配置写 `[]` |
| `upload` | 必填 | 图片必须能从响应里取出 `url` |
| `delete` | 可选 | 新插件用 v2；声明后自动获得「云删除」标签 |
| `prepare` | 可选，v2 | 最多 4 步，每步必须导出变量 |
| `requires` | 可选，v2 | 只能写客户端认识的能力名 |
| `authModes` | 可选，v2 | 1–8 种登录方式，与 `auth-modes` 能力同时声明 |

能力名：`prepare`、`credential-cache`、`response-conditions`、`credential-refresh`、
`safe-redirects`、`scoped-delete`、`conditional-json-fields`、`auth-modes`。
写未知能力会拒绝安装。

## plugin.json

| 键 | 约束 |
| --- | --- |
| `packageVersion` | 固定 `1` |
| `runtime` | `http-v1` / `http-v2`，必须与入口 `schemaVersion` 对应 |
| `entry` | 包内 JSON 路径，不能是 `plugin.json` 或 `assets/` 下 |
| `id` | 小写反向域名，`^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$`，≤ 80；投稿 ID 中的 GitHub 用户名必须保留连字符（`enddream-zm` 不能写成 `enddreamzm`） |
| `name` / `author` | 分别 ≤ 60 / 80 字 |
| `version` | SemVer，≤ 30；带 `-beta.1` 显示「测试版」 |
| `description` | ≤ 160 字 |
| `repository` / `homepage` | HTTP(S)，不能带账号密码 |
| `icon` | `assets/` 下的 png/jpg/jpeg/webp/gif/svg，≤ 1 MB |
| `mark` / `color` | 1–3 字符 / `#RRGGBB` |

## config[]

| 键 | 约束 |
| --- | --- |
| `key` | `^[A-Za-z][A-Za-z0-9_]{0,39}$`，插件内唯一，发布后不可改 |
| `label` | ≤ 50 字 |
| `type` | `text` / `secret` / `toggle` / `select`，默认 `text` |
| `required` | 布尔，默认 `false` |
| `options` | `select` 必填，非空字符串数组 |
| `role` | `endpoint` / `token` / `account`；最低 Picora 1.0.8，见 [roles-and-tags.md](roles-and-tags.md) |
| `input` | 可选对象，仅 `text` / `secret` 字段；见下方「输入限制」 |

标签由字段推导，不用手写：`endpoint` → 自定义地址，`token` → Token，`account` → 账号；
存在 `required` 的 `secret` 或 token/account 角色 → 需认证；声明 `delete` → 云删除。

## 输入限制 input

`config[].input` 用于限制用户输入字符并在保存时校验。不声明能力名；
使用后 `minAppVersion` 最低 `1.1.0`（`register` 会自动推导）。

```json
{
  "key": "path",
  "label": "目录",
  "type": "text",
  "input": {
    "allow": "[A-Za-z0-9._/-]",
    "message": "只能使用字母、数字、点、斜杠、下划线和连字符"
  }
}
```

| 参数 | 约束 |
| --- | --- |
| `allow` | 必填字符串，1–200 字符，必须是单个字符集 `[...]`，例如 `[a-z0-9-]`；不支持量词或锚点 |
| `message` | 可选，1–80 字，保存校验失败时的提示；省略用通用提示 |

行为：

- 输入时实时过滤，粘贴的多余字符同样剔除；空值不触发格式错误。
- 校验在必填之后执行，旧值或粘贴值不合规时保存被阻止并显示 `message`。
- 只影响表单，不改变请求模板取值。
- `authModes[].config` 的方式字段支持同一套 `input` 规则。

常用字符集：

| 场景 | `allow` |
| --- | --- |
| 数字 | `[0-9]` |
| 字母、数字、下划线、连字符 | `[A-Za-z0-9_-]` |
| 目录 / 对象前缀 | `[A-Za-z0-9._/-]` |
| 十六进制色值 | `[0-9a-fA-F#]` |

## 多登录方式 authModes

同一图床支持游客、Token、账号密码等多种鉴权方式时，用 `authModes` 合并成一个插件，
不要拆成多个插件。`requires` 必须同时声明 `auth-modes`，`minAppVersion` 最低 `1.1.0`。

```json
{
  "schemaVersion": 2,
  "requires": ["auth-modes"],
  "permissions": {"network": ["config.baseUrl"], "readSelectedFile": true},
  "config": [{"key": "baseUrl", "label": "服务地址", "role": "endpoint", "required": true}],
  "authModes": [
    {"id": "guest", "label": "游客", "config": [], "upload": {}},
    {"id": "token", "label": "API Token",
     "config": [{"key": "token", "label": "Token", "type": "secret", "role": "token", "required": true}],
     "upload": {}}
  ]
}
```

| 键 | 约束 |
| --- | --- |
| `id` | `^[a-z][a-z0-9-]{0,31}$`，插件内唯一，发布后稳定 |
| `label` | 1–40 字，显示在下拉菜单 |
| `config` | 该方式独有字段，最多 20 项，规则同根级 `config` |
| `prepare` | 可选，最多 4 步；可读取根级前置请求的导出 |
| `upload` | 必填，规则同根级上传请求 |
| `delete` | 可选，删除能力按方式独立生效 |

规则：

- 根级 `config` 与 `prepare` 对所有方式生效；声明 `authModes` 后根级 `upload` / `delete` 不生效。
- 方式字段键不能与根级字段或其它方式的字段重名，也不能使用 `authMode`（客户端保留）。
- 只能读取当前方式的字段和前置导出；引用其它方式的数据会在安装阶段被拒绝。
- `network` 的 `config.<key>` 可以指向根级或任一方式的非 `secret` 字段。
- 标签合并全部方式字段判断「需认证」；任一方式声明 `delete` 即显示「云删除」。
- 方式字段支持 `role` 与 `input`，规则与根级字段一致。

## permissions

```json
{
  "network": ["config.baseUrl"],
  "readSelectedFile": true,
  "allowInsecureHttp": true,
  "deleteUploadedFile": true
}
```

- `network` 必填，1–16 项。v2 只接受明确主机名或 `config.<key>`，不接受 `*` / `*.x`。
- `config.<key>` 必须指向本插件已声明的非 `secret` 字段，运行时绑定其协议、主机和端口。
- `readSelectedFile` 必须为 `true`。
- `allowInsecureHttp` 默认 `false`，适合内网 HTTP 自建站点。
- `deleteUploadedFile` 仅 v2，声明 `delete` 时必须为 `true`。

## 请求对象

| 键 | 说明 |
| --- | --- |
| `method` | 上传 `POST/PUT/PATCH`；前置 `GET/HEAD/POST`；删除 `GET/POST/DELETE` |
| `url` | 必须 HTTP(S)，支持模板，不能带账号密码或锚点 |
| `headers` / `query` | 各最多 64 项 |
| `body` | 上传必填；`multipart` / `json` / `form` / `binary` / `none` |
| `response` | 上传必填，其余可选 |
| `timeoutSeconds` | 5–300，默认 60 |
| `followRedirects` / `maxRedirects` | 默认关闭 / 最多 5 跳 |
| `errors` | `{"401": "提示文案"}` |
| `refreshCredentials` | 仅 v2 上传，凭证失效时刷新并重试一次 |

`multipart` 用 `fileField` 指定文件字段，`fields` 放附加参数，两者不能重名。
`json` 的 `conditionalFields` 只在 v2 前置请求可用，需声明 `conditional-json-fields`。

`conditionalFields` 每项形如：

```json
{"key": "bucket", "value": "img", "when": {"config": "region", "contains": "cn"}}
```

| 约束 | 说明 |
| --- | --- |
| 键 | 只能是 `key` / `value` / `when` |
| `key` | 1–128 字，不含控制字符，不能与 `fields` 或其它条件字段重名 |
| `value` | 必填，任意 JSON 值 |
| `when.config` | 必须指向本插件的 `text` 字段，不能是 secret / toggle / select |
| `when` 条件 | `contains` 与 `notContains` 二选一，值 1–256 字 |

禁止请求头：`Host`、`Content-Length`、`Proxy-Authorization`、`Proxy-Connection`、
`Connection`、`Transfer-Encoding`、`Upgrade`。

## response

| 键 | 适用 | 说明 |
| --- | --- | --- |
| `url` | 上传必填 | 图片地址路径 |
| `thumbnail` | 上传 | 缩略图路径 |
| `deleteKey` | 上传 | 删除凭证，必须是标量，不能是数组/对象 |
| `deleteUrl` | 上传，v2 | 完整删除 URL；上传阶段就会校验 |
| `successStatuses` | 全部 | 仅 2xx，上传默认 `[200, 201]` |
| `success` | v2 | `path` + 一个 `equals` / `exists` / `containsAny` |
| `errorMessage` / `errorCode` | v2 | 从响应体提取错误文案与错误码 |
| `exports` | 前置，v2 | 导出给后续请求使用的变量 |

路径写法：`data.url`、`items[0].url`、`[0].src`、`$`。没有通配、过滤或表达式。
相对图片链接按最终请求 URL 解析。

## 模板

`${config.key}`、`${upload.url}`、`${upload.deleteKey}`、`${upload.deleteUrl}`、
`${steps.<id>.<变量>}`、`${file.name}`、`${file.bytes}`、`${file.base64}`、
`${file.mime}`、`${uuid}`、`${time.millis}`、`${time.unix}`、`${assets/<file>}`。

`${file.path}` 仅 v1 可用。v2 删除请求只能读 `upload.url` / `upload.deleteKey` /
`upload.deleteUrl`，不提供配置、步骤、文件或资源；v1 删除额外允许 `config.*`。
前置请求可读配置、资源和更早步骤的导出，不能读图片。

变量必须以 `}` 闭合：`"${config.a"` 会触发「模板变量没有闭合」。v2 删除还需要
在请求中出现 `${upload.deleteKey}` 或 `${upload.deleteUrl}`。

函数：`normalizeBaseUrl()`、`urlEncode()`、`base64()`、`sha256()`、
`hmacSha256(key, data)`、`basicAuth(user, password)`、`assetText(path)`。

规则：

- 整串 `${x}` 保留原始类型；嵌在字符串里会被转成文本，字节会转成 base64。
- `upload.*` 只在删除请求里可用；`steps.*` 可在后续前置步骤与上传请求里使用，删除请求不可用。
- `file.*` 只在上传里可用。
- 配置值为 `null`、`"None"`、`"undetermined"` 时渲染为空串。

## 导出、缓存与刷新

`response.exports` 每项参数：

| 参数 | 说明 |
| --- | --- |
| `path` | JSON 路径或响应头名称，必填 |
| `type` | `string` / `number` / `boolean`，默认 `string`；字符串最长 4096 |
| `source` | `json` / `header`，默认 `json` |
| `required` | 默认 `true`；缺失即停止上传 |
| `secret` | 默认 `true`；按凭证脱敏 |

`cache` 只能 `scope: configuration`，`ttlFrom` 与 `ttlSeconds` 二选一
（1–86400 秒），`refreshBeforeSeconds` 0–300，`maxTtlSeconds` 1–86400。
`refreshCredentials.steps` 必须引用声明了 `cache` 的步骤，`statuses` 只允许
200/201/400/401/403/409/410/422，且最多重试一次。

## 资源上限

| 对象 | 上限 |
| --- | --- |
| 程序结构 | 5000 节点、16 层嵌套、单字符串 16384 字符 |
| ZIP | 10 MB；解压合计 20 MB；最多 128 条目 |
| 包内文件 | 单文件 2 MB；元信息与程序各 1 MB；readme 512 KB |
| 上传图片 | 100 MB |
| HTTP 响应 | 1 MB |

## prepare / 凭证

每步至少声明一个 `exports` 字段，后续用 `${steps.<id>.<变量>}` 引用；最多 4 步。

```json
{
  "prepare": [
    {
      "id": "login",
      "method": "POST",
      "url": "https://host/api/login",
      "body": {"type": "json", "fields": {"user": "${config.account}", "pass": "${config.password}"}},
      "response": {
        "successStatuses": [200],
        "success": {"path": "ok", "equals": true},
        "exports": {"token": {"path": "data.token", "required": true, "secret": true}}
      },
      "cache": {"ttlSeconds": 3600}
    }
  ]
}
```

需要缓存时在 `requires` 里声明 `credential-cache`；需要在凭证失效后刷新时声明
`credential-refresh`，并在上传请求里写 `refreshCredentials`。
