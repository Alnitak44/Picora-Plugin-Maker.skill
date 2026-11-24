# 属性标签与 role

插件列表里的「需认证 / Token / 账号 / 自定义地址 / 云删除 / 测试版」不是手填的，
而是从配置字段、请求声明和版本号推导。登记文件不写标签。

## role 取值

`config[].role` 是可选字符串，格式 `^[a-z][a-z0-9-]{0,23}$`。客户端只识别三个值：

| role | 生成的标签 | 典型用途 |
| --- | --- | --- |
| `endpoint` | 自定义地址 | 自建图床站点地址、S3 Endpoint、反向代理地址 |
| `token` | Token | API Key、AccessKey、上传令牌、签名密钥 |
| `account` | 账号 | 用户名、邮箱；密码另设 `secret` 字段 |

未知 role 会被忽略，字段照常显示，也不会把「需认证」误判成「无需认证」；
但不要依赖拼写错误，否则标签就是缺的。

## 用法

```json
"config": [
  {
    "key": "baseUrl",
    "label": "图床地址",
    "type": "text",
    "role": "endpoint",
    "required": true,
    "hint": "例如 https://img.example.com，装在子目录时包含子目录"
  },
  {
    "key": "token",
    "label": "API Token",
    "type": "secret",
    "role": "token",
    "required": true
  }
]
```

判定规则：

- `endpoint` / `account` 一般配 `text`，`token` 一般配 `secret`。
- 普通参数（bucket、目录、是否压缩、文件名模板）不写 `role`。
- 不要为了显示「需认证」给普通字段加 `role`：认证状态来自 `required` 的
  `secret` 字段或 `token` / `account` 角色，伪造会让审核方误判凭证范围。
- `role` 不影响表单类型、请求内容或权限声明，也不影响 `network` 绑定。
  调整 `role` 不需要重新审核权限，但首次使用要把 `minAppVersion` 提到 `1.0.8`。

## 自动推导的其他标签

| 来源 | 标签 | 说明 |
| --- | --- | --- |
| 声明 `delete` 请求 | 云删除 | 与相册「删除云端图片」按钮同一依据 |
| 版本号带预发布后缀 | 测试版 | `1.2.0-beta.1`；`+build.5` 不算 |
| 存在 `required` 的 `secret` | 需认证 | 与下方 role 判定取或 |
| `role: token` / `role: account` | 需认证 | 即使字段非必填也显示 |

标签顺序固定：token、account、custom-url、cloud-delete、beta。

## 旧插件与 tags 兜底

没有 `role` 的旧插件，目录构建时会按字段推断：

| 条件 | 推断标签 |
| --- | --- |
| 必填 secret 字段，键名或标题含令牌类关键词 | token |
| 必填文本字段，键名是账号类常用写法或标题含账号/用户/邮箱 | account |
| 必填文本字段，键名含 url / endpoint / host / base | custom-url |

这是兼容兜底，新插件应直接写 `role`。

确实没有任何配置字段、但仍需要凭证的旧插件，可以在登记文件写
`"tags": ["token"]`（只能取 token、account、custom-url，且不能重复）；
插件包里出现 `role` 后，登记值会被忽略，应及时删掉。

## 版本门槛

| 用法 | 最低 Picora |
| --- | --- |
| 任何 `config[].role` | `1.0.8` |
| `http-v2` 基础能力 | `1.0.1` |
| `conditional-json-fields` | `1.0.4` |
| `authModes`（`auth-modes`） | `1.1.0` |
| `config[].input`（输入限制） | `1.1.0` |

多登录方式（`authModes`）会把所有方式的字段合并起来判断标签：
任一方式有 `token` / `account` 角色或有必填 `secret`，就显示「需认证」；
任一方式声明 `delete`，就显示「云删除」。
写低了会让旧客户端在安装阶段拒绝插件，`register` 命令会自动推导这个值。
