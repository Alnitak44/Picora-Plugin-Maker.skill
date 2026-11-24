# 摸清图床接口

## 抓包步骤

1. 用无痕窗口打开图床，退出再登录，避免旧 Cookie 干扰。
2. F12 → Network → 勾选 `Preserve log`，筛 `Fetch/XHR`。
3. 上传一张 100 KB 以内的 PNG/JPG，找到真正发送图片的请求。
4. 右键 → Copy as cURL，先原样重放一次，确认能复现成功。
5. 记录：最终 URL（含子目录）、方法、Content-Type、文件字段名、其他字段、
   鉴权位置（Header / Cookie / 表单字段）、成功响应全文、失败响应全文。

注意：

- 页面可能先请求 `/api/token` 再上传，两个请求都要记。
- 上传接口可能不是页面路径，例如 `/api/index.php`、`/api/1/upload`、`/upload`。
- 站点可能用 200 表示业务失败，必须看响应体。
- 反向代理或 CDN 可能改写字段名，以浏览器实际发出的为准。

## 常见图床形态

| 类型 | 典型接口 | 鉴权 | 成功判定 |
| --- | --- | --- | --- |
| EasyImages 2.0 | `POST /api/index.php`，字段 `image` | 表单 `token` | `result == "success"` |
| Chevereto | `POST /api/1/upload`，字段 `source` 或 `image` | Header `X-API-Key` | `status_code == 200` |
| Lsky Pro | `POST /api/v1/upload`，字段 `file` | `Authorization: Bearer` | `status == true` |
| Telegraph-Image | `POST /upload`，字段 `file` | 可选 Basic Auth | 返回 `[{src}]` |
| imgbb | `POST https://api.imgbb.com/1/upload` | query `key` | `success == true` |
| superbed | 先 `POST /api/v1/auth/login` 取 token | JSON 账号密码 | 返回 token 后上传 |
| S3 / 兼容存储 | `PUT {endpoint}/{bucket}/{key}`，body 为二进制 | SigV4 签名 | 2xx |

加密类模板函数只有单次 `sha256` / `hmacSha256` / `base64`，没有多级派生密钥链。
SigV4 的 `AWS4-HMAC-SHA256` 派生（日期键 → 区域键 → 服务键 → 签名键）
无法在一次 `hmacSha256` 内完成，因此 S3 / OSS 原生签名不做；
只有站点提供 presigned URL 或固定 AccessKey 上传接口时才适配。

## 能力对照

| 需求 | 能否声明式实现 |
| --- | --- |
| 固定 multipart 字段 | 可以 |
| 字段值来自配置、文件名、时间戳、UUID | 可以 |
| 登录后取 token，再上传 | 可以，`prepare` |
| HMAC-SHA256 签名 | 可以，`hmacSha256` |
| Basic Auth | 可以，`basicAuth` |
| 需要读取站点返回的多个变量 | 可以，`exports` |
| 上传后轮询异步任务 | 不可以 |
| 需要执行页面 JS、WASM、验证码 | 不可以 |
| 需要浏览器指纹或 TLS 指纹 | 不可以 |
| 需要多文件批量打包上传 | 一次一张，客户端负责循环 |
| 需要多级 HMAC 派生签名（S3 SigV4、OSS） | 不可以，除非站点提供 presigned URL |

## 失败样本要一起抓

至少准备两条失败响应：

- 鉴权错误（错误 token、过期 Cookie）
- 文件超限或格式不支持

据此写 `errors` 状态码映射，并把 `errorMessage` / `errorCode` 指到真实字段。
错误文案要能指导用户改配置，不要只写「上传失败」。

## 删除能力

只有站点明确提供单张删除接口时才声明 `delete`：

- 删除凭证在上传响应里 → `deleteKey`
- 删除是固定接口加文件 id → `deleteKey` 拼到 `url`
- 删除链接在上传响应里且一定存在 → 可用 `deleteUrl`

删除请求同样要写 `success` 条件；很多站点删除成功也返回 HTTP 200。

## 抓包时顺手确认的字段

| 字段 | 用途 |
| --- | --- |
| 上传成功后图片的真实 URL | `response.url` 路径；注意是相对还是绝对 |
| 是否有缩略图 | `response.thumbnail` |
| 删除接口与删除凭证 | `deleteKey` 或 `deleteUrl` |
| 是否需要先登录/取 token | `prepare` |
| 成功标志字段 | `success` |
| 错误码与错误文案字段 | `errorMessage` / `errorCode` |
| 站点是否在子目录 | `baseUrl` 要含子目录 |
| 是否仅 HTTP（内网） | `allowInsecureHttp` |
