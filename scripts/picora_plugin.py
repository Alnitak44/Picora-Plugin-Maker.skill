#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Picora 图床插件预检、打包与上传回放。

只使用标准库，Python 3.8+。

  python picora_plugin.py validate <插件目录> [--zip 包]
  python picora_plugin.py pack <插件目录> [--name 前缀] [--out 目录]
  python picora_plugin.py replay <插件目录> -c config.json -i 图片 [--send]
"""

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlparse

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

RUNTIMES = {"http-v1": 1, "http-v2": 2}
CATALOG_REPO = "Alnitak44/picora-plugins"
CAPABILITIES = {
    "prepare",
    "credential-cache",
    "response-conditions",
    "credential-refresh",
    "safe-redirects",
    "scoped-delete",
    "conditional-json-fields",
    "auth-modes",
}
CONFIG_TYPES = {"text", "secret", "toggle", "select"}
KNOWN_ROLES = {"endpoint", "token", "account"}
BANNED_HEADERS = {
    "host",
    "content-length",
    "proxy-authorization",
    "proxy-connection",
    "connection",
    "transfer-encoding",
    "upgrade",
}
PROGRAM_KEYS = {"schemaVersion", "permissions", "config", "upload", "delete"}
METADATA_KEYS = {
    "packageVersion", "runtime", "entry", "id", "name", "version", "description",
    "author", "repository", "homepage", "icon", "mark", "color",
}
PROGRAM_METADATA_KEYS = {
    "id", "name", "version", "description", "author", "homepage", "mark", "color",
}
CONFIG_KEYS = {
    "key", "label", "type", "hint", "required", "default", "options", "role", "input",
}
REQUEST_KEYS = {
    "method",
    "url",
    "headers",
    "query",
    "errors",
    "body",
    "response",
    "followRedirects",
    "timeoutSeconds",
}
REQUEST_KEYS_V2 = {"maxRedirects", "refreshCredentials"}
BODY_KEYS = {"type", "fileField", "fields", "conditionalFields"}
RESPONSE_KEYS = {"successStatuses"}
RESPONSE_KEYS_V2 = {"success", "errorMessage", "errorCode", "exports"}
EXPORT_KEYS = {"path", "type", "source", "required", "secret"}
CACHE_KEYS = {"scope", "ttlFrom", "ttlSeconds", "refreshBeforeSeconds", "maxTtlSeconds"}
REFRESH_KEYS = {"steps", "statuses", "condition", "maxAttempts"}

ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
HOST_RE = re.compile(r"^(\*\.)?[a-z0-9.-]+$")
ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
PATH_RE = re.compile(
    r"^(?:\$\.)?(?:[A-Za-z_][A-Za-z0-9_-]*|\[\d+\])(?:\.[A-Za-z_][A-Za-z0-9_-]*|\[\d+\])*$"
)
EXPR_RE = re.compile(r"\$\{([^}]+)\}")
FUNC_RE = re.compile(r"^(base64|sha256|hmacSha256|basicAuth|normalizeBaseUrl|assetText|urlEncode)\((.*)\)$")
FILE_VARS = {"file.path", "file.name", "file.bytes", "file.base64", "file.mime"}

BANNED_WORDS = (
    "官方认证", "官方授权", "官网认证", "加微信", "加qq", "加群", "客服qq",
    "扫码进群", "领取红包", "返利", "刷单", "日赚", "兼职赚钱", "破解版",
    "激活码", "代充", "出售账号", "购买账号", "博彩", "赌博", "私彩",
)
TRUSTED_LINK_HOSTS = {
    "github.com", "www.github.com", "raw.githubusercontent.com",
    "objects.githubusercontent.com", "user-images.githubusercontent.com",
    "camo.githubusercontent.com",
}
PLACEHOLDER_SUFFIXES = (".example.com", ".example.org", ".example.net")
LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?")
BARE_URL_RE = re.compile(r"https?://[^\s<>)\]}`'\"，。；！？、]+", re.I)


class Report:
    def __init__(self):
        self.items = []

    def error(self, message, where=""):
        self.items.append(("error", where, message))

    def warn(self, message, where=""):
        self.items.append(("warn", where, message))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "error"]

    def print(self, verbose=False):
        shown_warnings = 0
        hidden = 0
        for level, where, message in self.items:
            if level == "warn" and not verbose:
                if shown_warnings >= 10:
                    hidden += 1
                    continue
                shown_warnings += 1
            print(f"[{level}] {where}: {message}" if where else f"[{level}] {message}")
        if hidden:
            print(f"…另有 {hidden} 条警告，加 --all 查看")
        if not self.items:
            print("OK：未发现问题")


def read_json(path, report, where):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (FileNotFoundError, IsADirectoryError):
        report.error(f"文件不存在：{path}", where)
        return None
    except OSError as exc:
        report.error(f"无法读取 {path}：{exc}", where)
        return None
    except json.JSONDecodeError as exc:
        report.error(f"JSON 无效（第 {exc.lineno} 行）：{exc.msg}", where)
        return None
    if not isinstance(value, dict):
        report.error("顶层必须是 JSON 对象", where)
        return None
    return value


def version_tuple(value):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value))
    return tuple(int(part) for part in match.groups()) if match else (0, 0, 0)


def required_min_version(program):
    minimum = "1.0.0"
    if program.get("schemaVersion") == 2 or program.get("delete"):
        minimum = "1.0.1"
    if any(isinstance(f, dict) and f.get("role") for f in program.get("config", []) or []):
        if version_tuple(minimum) < version_tuple("1.0.8"):
            minimum = "1.0.8"
    requires = program.get("requires") or []
    if "conditional-json-fields" in requires and version_tuple(minimum) < version_tuple("1.0.4"):
        minimum = "1.0.4"
    if program.get("authModes") and version_tuple(minimum) < version_tuple("1.1.0"):
        minimum = "1.1.0"
    all_fields = list(program.get("config") or [])
    for mode in program.get("authModes") or []:
        if isinstance(mode, dict):
            all_fields.extend(mode.get("config") or [])
    if any(
        isinstance(f, dict) and isinstance(f.get("input"), dict)
        for f in all_fields
    ) and version_tuple(minimum) < version_tuple("1.1.0"):
        minimum = "1.1.0"
    return minimum


def normalized_permissions(program):
    permissions = program.get("permissions") or {}
    return {
        "network": sorted(permissions.get("network") or []),
        "readSelectedFile": permissions.get("readSelectedFile") is True,
        "allowInsecureHttp": permissions.get("allowInsecureHttp") is True,
        "deleteUploadedFile": permissions.get("deleteUploadedFile") is True,
    }


def registration_from_plugin(meta, program, repository=None):
    repo = repository
    if repo is None:
        repo = urlparse(meta.get("repository", "")).path.strip("/")
    return {
        "id": meta.get("id"),
        "releaseRepository": repo,
        "minAppVersion": required_min_version(program),
        "approvedPermissions": normalized_permissions(program),
    }


def check_registration(registration, meta, program, report):
    where = "registration"
    if registration.get("id") != meta.get("id"):
        report.error("登记文件 id 与 plugin.json 不一致", where)
    filename = registration.get("_filename")
    expected_name = f"{registration.get('id')}.json"
    if filename and filename != expected_name:
        if registration.get("_in_register_dir"):
            report.error(f"登记文件名应为 {expected_name}，当前是 {filename}", where)
        else:
            report.warn(
                f"投稿时需改名为 {expected_name} 并放入 registrations/；"
                f"当前本地文件是 {filename}",
                where,
            )
    repo = registration.get("releaseRepository")
    if not isinstance(repo, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$", repo):
        report.error("releaseRepository 必须是 owner/repo，不能写完整 URL", where)
    else:
        expected = urlparse(meta.get("repository", "")).path.strip("/").lower()
        if expected and expected != repo.lower():
            report.error(
                f"plugin.json 的 repository 应指向 https://github.com/{repo}，当前为 {meta.get('repository')}",
                where,
            )
        owner = repo.split("/")[0].lower()
        if not str(meta.get("id", "")).startswith(f"io.github.{owner}."):
            guessed = re.sub(r"[^a-z0-9]", "", owner)
            if owner and str(meta.get("id", "")).startswith(f"io.github.{guessed}."):
                report.error(
                    f"新插件 id 应使用 io.github.{owner}.<插件名>；"
                    f"用户名 {owner} 里的连字符不能删，不能写成 io.github.{guessed}",
                    where,
                )
            else:
                report.error(f"新插件 id 应使用 io.github.{owner}.<插件名>", where)
    minimum = registration.get("minAppVersion")
    if not isinstance(minimum, str) or not SEMVER_RE.match(minimum):
        report.error("minAppVersion 必须是 SemVer", where)
    else:
        needed = required_min_version(program)
        if version_tuple(minimum) < version_tuple(needed):
            report.error(f"minAppVersion={minimum} 低于插件实际需要 {needed}", where)
    approved = registration.get("approvedPermissions")
    if not isinstance(approved, dict):
        report.error("缺少 approvedPermissions", where)
        return
    expected = normalized_permissions(program)
    actual = {
        "network": sorted(approved.get("network") or []),
        "readSelectedFile": approved.get("readSelectedFile") is True,
        "allowInsecureHttp": approved.get("allowInsecureHttp") is True,
        "deleteUploadedFile": approved.get("deleteUploadedFile") is True,
    }
    if actual != expected:
        report.error(
            "approvedPermissions 与 uploader.json 的 permissions 不一致："
            f"登记={json.dumps(actual, ensure_ascii=False)}，"
            f"插件={json.dumps(expected, ensure_ascii=False)}",
            where,
        )
    allowed_links = registration.get("allowedLinks", [])
    if not isinstance(allowed_links, list) or any(
        not isinstance(h, str) or not h.strip() or "/" in h or ":" in h for h in allowed_links
    ):
        report.error("allowedLinks 必须是主机名数组，例如 [\"docs.example.com\"]", where)
    prefix = registration.get("assetPrefix", "")
    if not isinstance(prefix, str) or "/" in prefix or "\\" in prefix:
        report.error("assetPrefix 不能包含路径分隔符", where)
    tags = registration.get("tags")
    if tags is not None:
        if (
            not isinstance(tags, list)
            or any(t not in {"token", "account", "custom-url"} for t in tags)
            or len(set(tags)) != len(tags)
        ):
            report.error(
                "tags 只能取 token / account / custom-url，且不能重复", where,
            )
        elif any(isinstance(f, dict) and f.get("role") for f in program.get("config", []) or []):
            report.warn("插件已写 role，登记文件的 tags 会被忽略，应删除", where)
    if "example" in registration and not isinstance(registration["example"], bool):
        report.error("example 必须是布尔值", where)


def check_keys(value, allowed, where, report):
    if not isinstance(value, dict):
        return
    for key in value:
        if key not in allowed:
            report.error(f"未知字段 {key!r}，安装时会拒绝", where)


def check_structure(program, report, where):
    nodes = 0

    def visit(value, depth):
        nonlocal nodes
        nodes += 1
        if nodes > 5000:
            return False
        if depth > 16:
            report.error("程序嵌套超过 16 层", where)
            return False
        if isinstance(value, str):
            if len(value) > 16384:
                report.error("程序中存在超过 16384 字符的字符串", where)
                return False
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and len(key) > 16384:
                    report.error("程序中出现过长的键名", where)
                    return False
                if not visit(item, depth + 1):
                    return False
        elif isinstance(value, list):
            for item in value:
                if not visit(item, depth + 1):
                    return False
        return True

    if not visit(program, 0):
        if nodes > 5000:
            report.error("程序结构超过 5000 个节点", where)


def valid_path(value):
    return (
        isinstance(value, str)
        and len(value) <= 120
        and (value == "$" or bool(PATH_RE.match(value)))
    )


def check_response_path(value, where, report):
    if not valid_path(value):
        report.error(f"响应路径无效：{value!r}（支持 data.url、items[0].url、[0].src）", where)
        return False
    return True


def check_condition(value, where, report):
    if not isinstance(value, dict):
        report.error("success 必须是对象", where)
        return
    check_keys(value, {"path", "equals", "exists", "containsAny"}, where, report)
    if not valid_path(value.get("path")):
        report.error("success.path 无效", where)
    ops = [k for k in ("equals", "exists", "containsAny") if k in value]
    if len(ops) != 1:
        report.error("success 需要且只能有一个 equals / exists / containsAny", where)
        return
    op = ops[0]
    if op == "equals" and not isinstance(value[op], (str, int, float, bool)) and value[op] is not None:
        report.error("success.equals 必须是字符串、数字、布尔或 null", where)
    if op == "exists" and not isinstance(value[op], bool):
        report.error("success.exists 必须是布尔值", where)
    if op == "containsAny":
        items = value[op]
        if (
            not isinstance(items, list)
            or not 1 <= len(items) <= 8
            or any(not isinstance(s, str) or not 2 <= len(s) <= 80 for s in items)
        ):
            report.error("success.containsAny 需要 1–8 个 2–80 字的字符串", where)


def iter_expressions(value):
    if isinstance(value, str):
        for match in EXPR_RE.finditer(value):
            yield match.group(1).strip()
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_expressions(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_expressions(item)


def check_expression(expr, ctx, version, root, config_keys, exports, report, where):
    match = FUNC_RE.match(expr)
    if match:
        name, raw_args = match.group(1), match.group(2)
        args = [item.strip() for item in raw_args.split(",")] if raw_args.strip() else []
        expected = {"hmacSha256": 2, "basicAuth": 2}.get(name, 1) if name != "assetText" else 1
        if len(args) != expected:
            report.error(f"模板函数 {name} 需要 {expected} 个参数", where)
        for arg in args:
            if arg:
                check_expression(arg, ctx, version, root, config_keys, exports, report, where)
        return
    phase = ctx["phase"]
    if phase == "delete":
        if expr in {"upload.url", "upload.deleteKey", "upload.deleteUrl"}:
            return
        if expr in {"uuid", "time.millis", "time.unix"}:
            return
        if version == 1 and (expr.startswith("config.") or expr.startswith("assets/")):
            pass  # v1 删除允许读配置与包内资源，交给后面的通用校验
        else:
            report.error(
                "删除请求只能读取 upload.url / upload.deleteKey / upload.deleteUrl，"
                f"不能使用 {expr}",
                where,
            )
            return
    if expr.startswith("assets/"):
        if not (root / expr).is_file():
            report.error(f"资源不存在：{expr}", where)
        return
    if expr in FILE_VARS:
        if phase != "upload":
            report.error(f"{expr} 只在上传请求里可用", where)
        elif expr == "file.path" and version == 2:
            report.error("${file.path} 仅 v1 可用；v2 使用 file.name / bytes / base64 / mime", where)
        return
    if expr in {"uuid", "time.millis", "time.unix"}:
        return
    if expr.startswith("config."):
        key = expr[7:]
        if key not in config_keys:
            report.error(f"模板引用了未声明的配置字段：{expr}", where)
        return
    if expr.startswith("upload."):
        report.error(f"{expr} 只能在删除请求里使用", where)
        return
    if expr.startswith("steps."):
        parts = expr.split(".")
        if len(parts) != 3:
            report.error(f"前置变量写法应为 steps.<id>.<name>：{expr}", where)
            return
        step, name = parts[1], parts[2]
        if step not in exports:
            report.error(f"模板引用了不存在的前置步骤：{step}", where)
        elif ctx.get("steps") is not None and step not in ctx["steps"]:
            report.error(f"前置步骤 {step} 尚未执行，只能引用更早的步骤", where)
        elif name not in exports[step]:
            report.error(f"前置步骤 {step} 没有导出 {name}", where)
        return
    report.error(f"未知模板变量：{expr}", where)


def check_templates(value, ctx, version, root, config_keys, exports, report, where):
    for text in iter_strings(value):
        if "${" in EXPR_RE.sub("", text):
            report.error("模板变量没有闭合：${ 后缺少 }", where)
    for expr in iter_expressions(value):
        check_expression(expr, ctx, version, root, config_keys, exports, report, where)


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def validate_config(config, report, where="config", maximum=30, used=None, reserved=None):
    keys = set()
    if not isinstance(config, list):
        report.error(f"{where} 必须是数组", where)
        return keys
    if len(config) > maximum:
        report.error(f"{where} 最多 {maximum} 项", where)
    for index, field in enumerate(config):
        item_where = f"{where}[{index}]"
        if not isinstance(field, dict):
            report.error("字段必须是对象", item_where)
            continue
        check_keys(field, CONFIG_KEYS, item_where, report)
        key = field.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            report.error(f"字段键无效：{key!r}", item_where)
        elif key in keys:
            report.error(f"字段键重复：{key}", item_where)
        elif reserved and key in reserved:
            report.error(f"{key} 是客户端保留字段，不能用作配置键", item_where)
        elif used and key in used:
            report.error(f"字段键 {key} 与其它位置的字段重名", item_where)
        else:
            keys.add(key)
        label = field.get("label")
        if not isinstance(label, str) or not label or len(label) > 50:
            report.error("label 必须是 1–50 字的字符串", item_where)
        kind = field.get("type", "text")
        if kind not in CONFIG_TYPES:
            report.error(f"type 必须是 {sorted(CONFIG_TYPES)}", item_where)
        if kind == "select":
            options = field.get("options")
            if not isinstance(options, list) or not options:
                report.error("select 字段需要非空 options", item_where)
            elif any(not isinstance(o, (str, int, float)) or o == "" for o in options):
                report.error("select 字段的 options 只能是字符串或数字", item_where)
        if "required" in field and not isinstance(field["required"], bool):
            report.error("required 必须是布尔值", item_where)
        role = field.get("role")
        if role is not None:
            if not isinstance(role, str) or not ROLE_RE.match(role):
                report.error(f"role 无效：{role!r}", item_where)
            elif role not in KNOWN_ROLES:
                report.warn(f"未知 role {role!r}，客户端会忽略", item_where)
        raw_input = field.get("input")
        if raw_input is not None:
            validate_field_input(raw_input, kind, item_where, report)
    return keys


def validate_field_input(value, kind, where, report):
    if not isinstance(value, dict):
        report.error("input 必须是对象", where)
        return
    check_keys(value, {"allow", "message"}, where, report)
    if kind not in {"text", "secret"}:
        report.error("input 仅支持 text / secret 字段", where)
    allow = value.get("allow")
    if not isinstance(allow, str) or not allow.strip() or len(allow) > 200:
        report.error("input.allow 必须是 1–200 字符的正则", where)
        return
    try:
        re.compile(allow)
    except re.error:
        report.error("input.allow 不是有效正则", where)
        return
    if not re.match(r"^\[[^\[\]]+\]$", allow):
        report.error("input.allow 必须是字符集写法，例如 [A-Za-z0-9._-]；不支持量词或锚点", where)
    message = value.get("message")
    if message is not None and (
        not isinstance(message, str) or not message.strip() or len(message) > 80
    ):
        report.error("input.message 必须是 1–80 字的字符串", where)


def validate_permissions(permissions, version, has_delete, config_fields, report):
    where = "permissions"
    if not isinstance(permissions, dict):
        report.error("缺少 permissions 对象", where)
        return
    allowed = {"network", "readSelectedFile", "allowInsecureHttp"}
    if version == 2:
        allowed.add("deleteUploadedFile")
    check_keys(permissions, allowed, where, report)
    network = permissions.get("network")
    if not isinstance(network, list) or not 1 <= len(network) <= 16:
        report.error("network 需要 1–16 项", where)
        network = []
    for host in network:
        if not isinstance(host, str):
            report.error("network 项必须是字符串", where)
            continue
        configured = version == 2 and bool(re.match(r"^config\.[A-Za-z][A-Za-z0-9_]{0,39}$", host))
        if configured:
            key = host[7:]
            field = config_fields.get(key)
            if field is None:
                report.error(f"{host} 指向未声明的配置字段", where)
            elif field.get("type") == "secret":
                report.error(f"{host} 不能引用 secret 字段", where)
            continue
        lowered = host.lower()
        if lowered == "*" or lowered.startswith("*."):
            if version != 2:
                continue
            report.error("v2 不支持通配主机", where)
        elif not HOST_RE.match(lowered):
            report.error(f"主机名无效：{host!r}（不要带协议或路径）", where)
    for flag in ("readSelectedFile", "allowInsecureHttp", "deleteUploadedFile"):
        if flag in permissions and not isinstance(permissions[flag], bool):
            report.error(f"{flag} 必须是布尔值", where)
    if permissions.get("readSelectedFile") is not True:
        report.error("readSelectedFile 必须为 true", where)
    if has_delete and version == 2 and permissions.get("deleteUploadedFile") is not True:
        report.error("声明 delete 时 deleteUploadedFile 必须为 true", where)


def validate_body(
    body, ctx, version, root, config_keys, exports, report, where, config_fields=None,
):
    if not isinstance(body, dict):
        report.error("body 必须是对象", where)
        return
    check_keys(body, BODY_KEYS, where, report)
    kind = body.get("type", "multipart")
    if kind not in {"multipart", "json", "form", "binary", "none"}:
        report.error(f"body.type 无效：{kind}", where)
    fields = body.get("fields", {})
    if not isinstance(fields, dict):
        report.error("body.fields 必须是对象", where)
        fields = {}
    if len(fields) > 64:
        report.error("body.fields 最多 64 项", where)
    if kind == "multipart":
        file_field = body.get("fileField", "file")
        if not isinstance(file_field, str) or not file_field:
            report.error("fileField 必须是非空字符串", where)
        elif file_field in fields:
            report.error("fileField 不能与 fields 重名", where)
    if "conditionalFields" in body:
        _validate_conditional_fields(
            body["conditionalFields"], fields, kind, ctx, version, config_keys,
            config_fields, report, where,
        )
    check_templates(fields, ctx, version, root, config_keys, exports, report, where)


def _validate_conditional_fields(
    items, body_fields, kind, ctx, version, config_keys, config_fields, report, where,
):
    where = f"{where}.conditionalFields"
    if version != 2 or ctx["phase"] != "prepare":
        report.error("conditionalFields 仅用于 http-v2 前置请求", where)
    if kind != "json":
        report.error("conditionalFields 只能用于 JSON 请求体", where)
    if not isinstance(items, list) or not 1 <= len(items) <= 32:
        report.error("conditionalFields 需要 1–32 项", where)
        return
    seen = set(body_fields) if isinstance(body_fields, dict) else set()
    for index, item in enumerate(items):
        item_where = f"{where}[{index}]"
        if not isinstance(item, dict):
            report.error("conditionalFields 项必须是对象", item_where)
            continue
        check_keys(item, {"key", "value", "when"}, item_where, report)
        key = item.get("key")
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 128
            or re.search(r"[\x00-\x1f\x7f]", key)
        ):
            report.error("conditionalFields.key 必须是 1–128 字且不含控制字符", item_where)
        elif key in seen:
            report.error(f"conditionalFields 键重复：{key}", item_where)
        else:
            seen.add(key)
        if "value" not in item:
            report.error("conditionalFields.value 缺失", item_where)
        when = item.get("when")
        if not isinstance(when, dict):
            report.error("conditionalFields.when 必须是对象", item_where)
            continue
        check_keys(when, {"config", "contains", "notContains"}, item_where, report)
        target = when.get("config")
        has_contains, has_not = "contains" in when, "notContains" in when
        if not isinstance(target, str) or not KEY_RE.match(target) or has_contains == has_not:
            report.error(
                "conditionalFields.when 需要 config 与 contains / notContains 二选一",
                item_where,
            )
            continue
        text = when["contains"] if has_contains else when["notContains"]
        if not isinstance(text, str) or not text or len(text) > 256:
            report.error("conditionalFields.when 匹配文本必须是 1–256 字", item_where)
        if target not in config_keys:
            report.error(f"conditionalFields.when.config 引用未声明的配置字段：{target}", item_where)
            continue
        field = (config_fields or {}).get(target) or {}
        if field.get("type", "text") != "text":
            report.error(
                f"conditionalFields.when.config 只能引用 text 字段，{target} 是 "
                f"{field.get('type')}",
                item_where,
            )


def validate_response(response, upload, version, ctx, root, config_keys, exports, report, where):
    if not isinstance(response, dict):
        report.error("response 必须是对象", where)
        return
    allowed = set(RESPONSE_KEYS)
    if upload:
        allowed |= {"url", "thumbnail", "deleteKey"}
        if version == 2:
            allowed.add("deleteUrl")
    if version == 2:
        allowed |= RESPONSE_KEYS_V2
    check_keys(response, allowed, where, report)
    statuses = response.get("successStatuses", [200, 201] if upload else None)
    if statuses is not None:
        if (
            not isinstance(statuses, list)
            or not 1 <= len(statuses) <= 100
            or any(not isinstance(s, int) or not 200 <= s <= 299 for s in statuses)
        ):
            report.error("successStatuses 只能包含 2xx 整数", where)
    if upload:
        if "url" not in response:
            report.error("上传 response 必须声明 url", where)
        else:
            check_response_path(response["url"], where, report)
        for key in ("thumbnail", "deleteKey", "deleteUrl"):
            if key in response:
                check_response_path(response[key], where, report)
    if version == 2:
        if "success" in response:
            check_condition(response["success"], where, report)
        for key in ("errorMessage", "errorCode"):
            if key in response:
                check_response_path(response[key], where, report)
        definitions = response.get("exports")
        if definitions is not None and ctx["phase"] != "prepare":
            report.error("导出字段仅用于前置请求", where)
        elif isinstance(definitions, dict):
            if len(definitions) > 16:
                report.error("最多导出 16 个字段", where)
            for name, spec in definitions.items():
                if not KEY_RE.match(name or ""):
                    report.error(f"导出变量名无效：{name!r}", where)
                if not isinstance(spec, dict):
                    report.error(f"导出 {name} 必须是对象", where)
                    continue
                check_keys(spec, EXPORT_KEYS, where, report)
                source = spec.get("source", "json")
                if source == "header":
                    header = spec.get("path")
                    if (
                        not isinstance(header, str)
                        or len(header) > 120
                        or not re.match(r"^[A-Za-z0-9-]+$", header)
                    ):
                        report.error(f"导出 {name} 的响应头名称无效", where)
                else:
                    check_response_path(spec.get("path"), where, report)
                if spec.get("type", "string") not in {"string", "number", "boolean"}:
                    report.error(f"导出 {name} 的 type 无效", where)
                if source not in {"json", "header"}:
                    report.error(f"导出 {name} 的 source 无效", where)
                for flag in ("required", "secret"):
                    if flag in spec and not isinstance(spec[flag], bool):
                        report.error(f"导出 {name} 的 {flag} 必须是布尔值", where)


def validate_request(
    request, phase, version, root, config_keys, exports, report, where,
    steps_scope=None, cached=None, config_fields=None,
):
    if not isinstance(request, dict):
        report.error("请求必须是对象", where)
        return
    allowed = set(REQUEST_KEYS)
    if version == 2:
        allowed |= REQUEST_KEYS_V2
    check_keys(request, allowed, where, report)
    default_method = "GET" if phase == "prepare" else "POST"
    method = str(request.get("method", default_method)).upper()
    allowed_methods = {
        "prepare": {"GET", "HEAD", "POST"},
        "upload": {"POST", "PUT", "PATCH"},
        "delete": {"GET", "POST", "DELETE"},
    }[phase]
    if method not in allowed_methods:
        report.error(f"{phase} 不支持方法 {method}", where)
    url = request.get("url")
    if not isinstance(url, str) or not url or len(url) > 16384:
        report.error("url 无效", where)
    elif "${" not in url and not re.match(r"^https?://", url, re.I):
        report.error("url 必须以 http:// 或 https:// 开头", where)
    headers = request.get("headers", {})
    if not isinstance(headers, dict) or len(headers) > 64:
        report.error("headers 必须是对象且最多 64 项", where)
        headers = {}
    for name in headers:
        if not HEADER_RE.match(name or "") or name.lower() in BANNED_HEADERS:
            report.error(f"不能设置请求头 {name!r}", where)
    query = request.get("query", {})
    if not isinstance(query, dict) or len(query) > 64:
        report.error("query 必须是对象且最多 64 项", where)
    timeout = request.get("timeoutSeconds", 60)
    if not isinstance(timeout, int) or not 5 <= timeout <= 300:
        report.error("timeoutSeconds 必须是 5–300 的整数", where)
    if not isinstance(request.get("followRedirects", False), bool):
        report.error("followRedirects 必须是布尔值", where)
    if "maxRedirects" in request:
        maximum = request["maxRedirects"]
        if not isinstance(maximum, int) or not 0 <= maximum <= 5:
            report.error("maxRedirects 必须是 0–5 的整数", where)
    errors = request.get("errors", {})
    if not isinstance(errors, dict):
        report.error("errors 必须是对象", where)
        errors = {}
    elif len(errors) > 64:
        report.error("errors 最多 64 项", where)
    for code, message in errors.items():
        text = str(code)
        if (
            not re.fullmatch(r"\d{3}", text)
            or not 100 <= int(text) <= 599
            or not isinstance(message, str)
            or not message
        ):
            report.error(f"errors 项无效：{code}（需要 100–599 的状态码与非空文案）", where)
    ctx = {
        "phase": phase,
        "steps": None if phase == "delete" else (set(exports) if steps_scope is None else steps_scope),
    }
    check_templates(url, ctx, version, root, config_keys, exports, report, where)
    check_templates(query, ctx, version, root, config_keys, exports, report, where)
    check_templates(headers, ctx, version, root, config_keys, exports, report, where)
    body = request.get("body")
    if phase == "upload":
        if body is None:
            report.error("上传必须提供 body", where)
        else:
            validate_body(
                body, ctx, version, root, config_keys, exports, report, where,
                config_fields=config_fields,
            )
    elif body is not None:
        if not isinstance(body, dict):
            report.error("body 必须是对象", where)
        else:
            kind = body.get("type", "multipart")
            if kind in {"multipart", "binary"}:
                report.error(f"{phase} 不能发送文件", where)
            validate_body(
                body, ctx, version, root, config_keys, exports, report, where,
                config_fields=config_fields,
            )
    if method in {"GET", "HEAD"} and isinstance(body, dict) and body.get("type", "multipart") != "none":
        report.error(f"{method} 不能带请求体；需要空体时写 body.type = none", where)
    response = request.get("response")
    if phase == "upload":
        if response is None:
            report.error("上传必须提供 response", where)
        else:
            validate_response(
                response, True, version, ctx, root, config_keys, exports, report, where
            )
    elif response is not None:
        validate_response(response, False, version, ctx, root, config_keys, exports, report, where)
    if "refreshCredentials" in request:
        if phase != "upload":
            report.error("refreshCredentials 仅用于上传", where)
        else:
            validate_refresh(request["refreshCredentials"], exports, cached or set(), report, where)


def validate_refresh(spec, exports, cached, report, where):
    if not isinstance(spec, dict):
        report.error("refreshCredentials 必须是对象", where)
        return
    check_keys(spec, REFRESH_KEYS, where, report)
    steps = spec.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 4 or any(not isinstance(s, str) for s in steps):
        report.error("refreshCredentials.steps 需要 1–4 个步骤 id", where)
    elif any(step not in exports for step in steps):
        report.error("refreshCredentials.steps 引用了不存在的前置步骤", where)
    elif any(step not in cached for step in steps):
        report.error("refreshCredentials 引用的步骤必须声明 cache", where)
    statuses = spec.get("statuses", [401])
    if (
        not isinstance(statuses, list)
        or not 1 <= len(statuses) <= 8
        or any(s not in {200, 201, 400, 401, 403, 409, 410, 422} for s in statuses)
    ):
        report.error("refreshCredentials.statuses 无效", where)
    if spec.get("maxAttempts", 1) != 1:
        report.error("凭证刷新最多重试一次", where)
    if "condition" in spec:
        check_condition(spec["condition"], where, report)
        condition = spec["condition"] if isinstance(spec["condition"], dict) else {}
        if "containsAny" not in condition:
            value = condition.get("equals")
            if value is None or isinstance(value, bool) or (isinstance(value, str) and not value):
                report.error("凭证刷新条件必须是明确错误码或非空关键词", where)
    elif isinstance(statuses, list) and any(s != 401 for s in statuses):
        report.error("401 以外的状态码需要额外的凭证失效 condition", where)


def validate_prepare(
    steps, version, root, config_keys, report, config_fields=None,
    prior_exports=None, prior_cached=None, where="prepare",
):
    if not isinstance(steps, list):
        report.error("prepare 必须是数组", where)
        return {}, set()
    if version != 2:
        report.error("schemaVersion 1 不支持 prepare", where)
        return {}, set()
    if len(steps) > 4:
        report.error("prepare 最多 4 步", where)
    exports = dict(prior_exports or {})
    cached = set(prior_cached or ())
    seen = set(prior_exports or ())
    for index, step in enumerate(steps):
        where_item = f"{where}[{index}]"
        if not isinstance(step, dict):
            report.error("步骤必须是对象", where_item)
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not KEY_RE.match(step_id):
            report.error(f"步骤 id 无效：{step_id!r}", where_item)
            continue
        if step_id in seen:
            report.error(f"步骤 id 重复：{step_id}", where_item)
        seen.add(step_id)
        response = step.get("response") or {}
        definitions = response.get("exports") if isinstance(response, dict) else None
        if not isinstance(definitions, dict) or not definitions:
            report.error("前置请求必须声明 exports", where_item)
            definitions = {}
        exports[step_id] = set(definitions)
        if "cache" in step:
            validate_cache(step["cache"], report, where_item)
            cached.add(step_id)
    earlier = set(prior_exports or ())
    for index, step in enumerate(steps):
        where_item = f"{where}[{index}]"
        if not isinstance(step, dict):
            continue
        request = {k: v for k, v in step.items() if k not in {"id", "cache"}}
        if "refreshCredentials" in request:
            report.error("前置请求不能触发上传重试", where_item)
        validate_request(
            request, "prepare", version, root, config_keys, exports, report, where_item,
            steps_scope=set(earlier), config_fields=config_fields,
        )
        step_id = step.get("id")
        if isinstance(step_id, str):
            earlier.add(step_id)
    return exports, cached


def validate_cache(cache, report, where):
    if not isinstance(cache, dict):
        report.error("cache 必须是对象", where)
        return
    check_keys(cache, CACHE_KEYS, where, report)
    if cache.get("scope", "configuration") != "configuration":
        report.error("缓存只能按配置组隔离", where)
    has_from, has_seconds = "ttlFrom" in cache, "ttlSeconds" in cache
    if has_from == has_seconds:
        report.error("cache 需要 ttlFrom 或 ttlSeconds 二选一", where)
    if has_from and not valid_path(cache["ttlFrom"]):
        report.error("cache.ttlFrom 路径无效", where)
    if has_seconds and (not isinstance(cache["ttlSeconds"], int) or not 1 <= cache["ttlSeconds"] <= 86400):
        report.error("cache.ttlSeconds 必须是 1–86400", where)
    early = cache.get("refreshBeforeSeconds", 30)
    maximum = cache.get("maxTtlSeconds", 3600)
    if not isinstance(early, int) or not 0 <= early <= 300:
        report.error("refreshBeforeSeconds 必须是 0–300", where)
    if not isinstance(maximum, int) or not 1 <= maximum <= 86400:
        report.error("maxTtlSeconds 必须是 1–86400", where)


def validate_auth_modes(program, version, report, where, config_keys, config_fields):
    """校验 authModes 外壳；请求本身交给 validate_prepare / validate_request。"""
    modes = program.get("authModes")
    if modes is None:
        return []
    if version != 2:
        report.error("authModes 仅支持 http-v2", where)
        return []
    if not isinstance(modes, list) or not 1 <= len(modes) <= 8:
        report.error("authModes 需要 1–8 个鉴权方式", where)
        return []
    seen_ids = set()
    used_keys = set(config_keys)
    result = []
    for index, mode in enumerate(modes):
        item_where = f"authModes[{index}]"
        if not isinstance(mode, dict):
            report.error("鉴权方式必须是对象", item_where)
            continue
        check_keys(
            mode, {"id", "label", "config", "prepare", "upload", "delete"},
            item_where, report,
        )
        mode_id = mode.get("id")
        if not isinstance(mode_id, str) or not re.match(r"^[a-z][a-z0-9-]{0,31}$", mode_id):
            report.error(f"authModes.id 无效：{mode_id!r}", item_where)
        elif mode_id in seen_ids:
            report.error(f"authModes.id 重复：{mode_id}", item_where)
        else:
            seen_ids.add(mode_id)
        label = mode.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 40:
            report.error("authModes.label 必须是 1–40 字的字符串", item_where)
        raw_fields = mode.get("config")
        if not isinstance(raw_fields, list):
            report.error("authModes.config 必须是字段数组", item_where)
            raw_fields = []
        keys = validate_config(
            raw_fields, report, f"{item_where}.config", maximum=20,
            used=used_keys, reserved={"authMode"},
        )
        used_keys |= keys
        fields = {
            f["key"]: f for f in raw_fields
            if isinstance(f, dict) and isinstance(f.get("key"), str)
        }
        result.append(
            {
                "id": mode_id,
                "where": item_where,
                "config_keys": keys,
                "fields": fields,
                "prepare": mode.get("prepare"),
                "upload": mode.get("upload"),
                "delete": mode.get("delete"),
            }
        )
    if "authMode" in config_keys:
        report.error("authMode 是客户端保留字段，不能用作配置键", "config")
    return result


def validate_plugin(root, allowed_links=None, submitting=False):
    report = Report()
    meta = read_json(root / "plugin.json", report, "plugin.json")
    if meta is None:
        return report
    if (root / "plugin.json").stat().st_size > 1024 * 1024:
        report.error("plugin.json 不能超过 1 MB", "plugin.json")
    unknown_meta = sorted(set(meta) - METADATA_KEYS)
    if unknown_meta:
        report.warn(
            "plugin.json 含客户端不识别的字段 " + "、".join(unknown_meta) + "（会被忽略）",
            "plugin.json",
        )

    runtime = meta.get("runtime")
    version = RUNTIMES.get(runtime)
    if meta.get("packageVersion") != 1:
        report.error("packageVersion 必须为 1", "plugin.json")
    if version is None:
        report.error("runtime 必须是 http-v1 / http-v2", "plugin.json")
        return report
    entry = meta.get("entry")
    if (
        not isinstance(entry, str)
        or not entry.endswith(".json")
        or entry == "plugin.json"
        or entry.startswith("assets/")
        or entry.startswith("/")
        or ".." in Path(entry).parts
        or "\\" in entry
        or ":" in entry
    ):
        report.error("entry 必须指向包内 JSON 程序文件", "plugin.json")
        return report
    program = read_json(root / entry, report, entry)
    if program is None:
        return report
    if (root / entry).stat().st_size > 1024 * 1024:
        report.error(f"{entry} 不能超过 1 MB", entry)
    check_structure(program, report, entry)

    if program.get("schemaVersion") != version:
        report.error(
            f"runtime {runtime} 需要 schemaVersion {version}", entry
        )
    allowed = set(PROGRAM_KEYS) | PROGRAM_METADATA_KEYS
    if version == 2:
        allowed |= {"prepare", "requires", "authModes"}
    check_keys(program, allowed, entry, report)
    duplicated = sorted(set(program) & PROGRAM_METADATA_KEYS)
    if duplicated:
        report.warn(
            "入口程序里重复写了元信息 "
            + "、".join(duplicated)
            + "；这些字段以 plugin.json 为准，建议删除",
            entry,
        )

    for key, maximum in (("name", 60), ("author", 80), ("version", 30), ("description", 160)):
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            report.error(f"{key} 必须是 1–{maximum} 字的字符串", "plugin.json")
    plugin_id = meta.get("id")
    if not isinstance(plugin_id, str) or not ID_RE.match(plugin_id) or len(plugin_id) > 80:
        report.error("id 必须是小写反向域名，例如 io.github.user.host", "plugin.json")
    version_value = meta.get("version")
    if isinstance(version_value, str) and not SEMVER_RE.match(version_value):
        report.error(f"version 不是 SemVer：{version_value}", "plugin.json")
    for key in ("homepage", "repository"):
        value = meta.get(key)
        if value is None:
            continue
        parsed = urlparse(value) if isinstance(value, str) else None
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
        ):
            report.error(f"{key} 必须是 HTTP/HTTPS 地址且不能带账号密码", "plugin.json")
    icon = meta.get("icon")
    if icon is not None:
        if (
            not isinstance(icon, str)
            or not icon.startswith("assets/")
            or not re.search(r"\.(png|jpg|jpeg|webp|gif|svg)$", icon, re.I)
        ):
            report.error("icon 必须是 assets/ 下的 png/jpg/jpeg/webp/gif/svg", "plugin.json")
        elif not (root / icon).is_file():
            report.error(f"icon 文件不存在：{icon}", "plugin.json")
        elif (root / icon).stat().st_size > 1024 * 1024:
            report.error("icon 不能超过 1 MB", "plugin.json")
    mark = meta.get("mark")
    if mark is not None and (not isinstance(mark, str) or not 1 <= len(mark) <= 3):
        report.error("mark 必须是 1–3 个字符", "plugin.json")
    color = meta.get("color")
    if color is not None and (not isinstance(color, str) or not re.match(r"^#[0-9A-Fa-f]{6}$", color)):
        report.error("color 必须是 #RRGGBB", "plugin.json")

    readme = root / "readme.md"
    if not readme.is_file():
        report.error("缺少 readme.md", "package")
    else:
        raw = readme.read_bytes()
        if not raw.strip():
            report.error("readme.md 不能为空", "package")
        elif len(raw) > 512 * 1024:
            report.error("readme.md 不能超过 512 KB", "package")
        else:
            try:
                check_catalog_text(
                    meta,
                    raw.decode("utf-8"),
                    (program.get("permissions") or {}).get("network") or [],
                    allowed_links,
                    report,
                    submitting=submitting,
                )
            except UnicodeDecodeError:
                report.error("readme.md 必须是 UTF-8", "package")
    assets = root / "assets"
    if not assets.is_dir():
        report.error("缺少 assets/ 目录，客户端要求该目录存在（可以为空）", "package")
    elif not any(path.is_file() for path in assets.rglob("*")):
        report.warn("assets/ 目录为空；客户端允许，但通常至少放一个图标", "package")

    config = program.get("config")
    config_keys = validate_config(config, report)
    config_fields = {
        f["key"]: f for f in (config or []) if isinstance(f, dict) and isinstance(f.get("key"), str)
    }
    modes = validate_auth_modes(program, version, report, entry, config_keys, config_fields)
    mode_fields = {}
    for mode in modes:
        mode_fields.update(mode["fields"])
    all_fields = {**config_fields, **mode_fields}
    root_delete = isinstance(program.get("delete"), dict)
    has_delete = (root_delete and not modes) or any(mode["delete"] is not None for mode in modes)
    if modes and root_delete:
        report.warn(
            "声明 authModes 时根级 delete 不生效，删除要在各鉴权方式里声明", entry,
        )
    if has_delete and version == 1:
        report.warn(
            "v1 程序声明 delete 属于旧格式；官方文档只在 http-v2 描述单张删除，新插件建议升级到 v2",
            entry,
        )
    validate_permissions(program.get("permissions"), version, has_delete, all_fields, report)

    requires = program.get("requires", [])
    if version == 1 and "requires" in program:
        report.error("schemaVersion 1 不支持 requires", entry)
    if requires is not None and (
        not isinstance(requires, list)
        or any(not isinstance(r, str) or r not in CAPABILITIES for r in requires)
    ):
        report.error("requires 包含未知能力", entry)
        requires = []
    requires = requires or []
    if modes and "auth-modes" not in requires:
        report.error("声明 authModes 必须在 requires 里补上 auth-modes", entry)
    prepare = program.get("prepare")
    if prepare is not None:
        exports, cached = validate_prepare(
            prepare, version, root, config_keys, report, config_fields
        )
    else:
        exports, cached = {}, set()
    if prepare and "prepare" not in requires:
        report.warn("声明了 prepare 但 requires 缺少 prepare；客户端不校验，建议补齐", entry)
    if prepare and "credential-cache" not in requires and any(
        isinstance(s, dict) and "cache" in s for s in prepare
    ):
        report.warn("使用了 cache 但 requires 缺少 credential-cache；建议补齐", entry)
    if has_delete and version == 2 and "scoped-delete" not in requires:
        report.warn("声明 delete 但 requires 缺少 scoped-delete；建议补齐", entry)
    for mode in modes:
        mode_where = mode["where"]
        mode_keys = config_keys | mode["config_keys"]
        current_fields = {**config_fields, **mode["fields"]}
        if mode["prepare"] is not None:
            mode_exports, mode_cached = validate_prepare(
                mode["prepare"], version, root, mode_keys, report,
                current_fields, prior_exports=exports, prior_cached=cached,
                where=f"{mode_where}.prepare",
            )
        else:
            mode_exports, mode_cached = {}, set()
        mode_all = {**exports, **mode_exports}
        mode_cached_all = cached | mode_cached
        mode_upload = mode["upload"]
        if mode_upload is None:
            report.error("每种鉴权方式都必须声明 upload", mode_where)
        else:
            validate_request(
                mode_upload, "upload", version, root, mode_keys, mode_all, report,
                f"{mode_where}.upload", cached=mode_cached_all,
                config_fields=current_fields,
            )
            mode_body = mode_upload.get("body") if isinstance(mode_upload, dict) else None
            if (
                isinstance(mode_body, dict)
                and "conditionalFields" in mode_body
                and "conditional-json-fields" not in requires
            ):
                report.error(
                    "使用了 conditionalFields 但 requires 缺少 conditional-json-fields",
                    f"{mode_where}.upload",
                )
        mode_delete = mode["delete"]
        if mode_delete is not None:
            validate_request(
                mode_delete, "delete", version, root, mode_keys, mode_all, report,
                f"{mode_where}.delete", config_fields=current_fields,
            )
            if not has_delete_reference(mode_delete):
                report.error(
                    "v2 删除请求必须引用 ${upload.deleteKey} 或 ${upload.deleteUrl}",
                    f"{mode_where}.delete",
                )
    upload = program.get("upload")
    if modes:
        if upload is not None:
            report.warn(
                "声明 authModes 时根级 upload 会被忽略，上传请求写在各鉴权方式里", entry,
            )
    elif upload is None:
        report.error("缺少 upload", entry)
    else:
        validate_request(
            upload, "upload", version, root, config_keys, exports, report, "upload",
            cached=cached, config_fields=config_fields,
        )
        body = upload.get("body") if isinstance(upload, dict) else None
        if isinstance(body, dict) and "conditionalFields" in body and "conditional-json-fields" not in requires:
            report.error("使用了 conditionalFields 但 requires 缺少 conditional-json-fields", "upload")
    if root_delete and not modes:
        validate_request(
            program["delete"], "delete", version, root, config_keys, exports, report,
            "delete", config_fields=config_fields,
        )
        if version == 2 and not has_delete_reference(program["delete"]):
            report.error(
                "v2 删除请求必须引用 ${upload.deleteKey} 或 ${upload.deleteUrl}",
                "delete",
            )
    for flag in ("response-conditions", "credential-refresh", "safe-redirects", "auth-modes"):
        if flag in requires and version != 2:
            report.error(f"{flag} 需要 http-v2", entry)
    return report


def has_delete_reference(value):
    if isinstance(value, dict):
        return any(has_delete_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(has_delete_reference(item) for item in value)
    if not isinstance(value, str):
        return False
    for match in EXPR_RE.finditer(value):
        if re.search(r"\bupload\.(deleteKey|deleteUrl)\b", match.group(1)):
            return True
    return False


def check_catalog_text(meta, readme_text, network, allowed_links, report, submitting=False):
    """预演模块仓库 CI 的文案与链接检查，避免提交后才发现失败。

    只交付 ZIP 自用时把外链问题降级为提醒；确定要投稿（提供了登记文件）才按
    CI 规则报错。
    """
    def fail_or_warn(message):
        if submitting:
            report.error(message, "package")
        else:
            report.warn(message + "（自用安装不受影响）", "package")

    for field in ("name", "description", "author"):
        text = unicodedata.normalize("NFKC", str(meta.get(field) or "")).casefold()
        for word in BANNED_WORDS:
            if word in text:
                if submitting:
                    report.error(
                        f"{field} 含违规内容 {word!r}，模块仓库构建会失败", "plugin.json",
                    )
                else:
                    report.warn(f"{field} 含违规内容 {word!r}，投稿会被拒", "plugin.json")
    folded = unicodedata.normalize("NFKC", readme_text).casefold()
    for word in BANNED_WORDS:
        if word in folded:
            if submitting:
                report.error(f"readme.md 含违规内容 {word!r}，模块仓库构建会失败", "readme.md")
            else:
                report.warn(f"readme.md 含违规内容 {word!r}，投稿会被拒", "readme.md")
    hosts = set(TRUSTED_LINK_HOSTS)
    extra = [host for host in network if isinstance(host, str) and host != "*"]
    extra += [host for host in (allowed_links or []) if isinstance(host, str)]
    for host in extra:
        lowered = host.lower()
        hosts.add(lowered)
        hosts.add(base_domain(lowered))
    for field, text in (("readme.md", readme_text), ("homepage", meta.get("homepage") or "")):
        if not text:
            continue
        seen = set()
        for link in LINK_RE.findall(text) + BARE_URL_RE.findall(text):
            link = link.rstrip("`'\".,;:!?，。；：！？、")
            if link in seen:
                continue
            seen.add(link)
            parsed = urlparse(link)
            if parsed.scheme in ("", "mailto"):
                continue
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                fail_or_warn(f"{field} 含不支持的链接 {link}")
                continue
            host = parsed.hostname.lower()
            if (
                not host.isascii()
                or not re.fullmatch(r"[a-z0-9.-]+", host)
                or host in {"example.com", "example.org", "example.net"}
                or host.endswith(PLACEHOLDER_SUFFIXES)
            ):
                continue
            if host not in hosts and base_domain(host) not in hosts:
                fail_or_warn(
                    f"{field} 里的链接 {link} 指向 {host}，模块仓库只放行 GitHub、"
                    "插件请求主机与 allowedLinks 中的域名；投稿时需加 allowedLinks 或删除"
                )


def base_domain(host):
    labels = host.lower().strip(".").split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host.lower()


def validate_zip(path, report):
    where = f"zip:{path.name}"
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 128:
                report.error("ZIP 最多 128 个条目", where)
            if path.stat().st_size > 10 * 1024 * 1024:
                report.error("ZIP 不能超过 10 MB", where)
            names = [info.filename for info in infos]
            if len(set(names)) != len(names):
                report.error("ZIP 含重复条目", where)
            elif len({name.lower() for name in names}) != len(names):
                report.error("ZIP 含仅大小写不同的重复条目", where)
            if sum(info.file_size for info in infos) > 20 * 1024 * 1024:
                report.error("解压后总大小不能超过 20 MB", where)
            for info in infos:
                if info.file_size > 2 * 1024 * 1024:
                    report.error(f"单文件超过 2 MB：{info.filename}", where)
                name = info.filename
                if (
                    name.startswith("/")
                    or "\\" in name
                    or ":" in name
                    or "\x00" in name
                    or ".." in Path(name).parts
                ):
                    report.error(f"ZIP 含非法路径：{info.filename}", where)
            for required in ("plugin.json", "readme.md"):
                if required not in names:
                    report.error(f"ZIP 根目录缺少 {required}", where)
            if not any(name == "assets/" or name.startswith("assets/") for name in names):
                report.error("ZIP 缺少 assets/ 目录，客户端会拒绝安装", where)
            if "plugin.json" in names:
                try:
                    packed = json.loads(archive.read("plugin.json").decode("utf-8-sig"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    report.error("ZIP 内 plugin.json 不是合法 UTF-8 JSON", where)
                else:
                    packed_entry = packed.get("entry") if isinstance(packed, dict) else None
                    if not isinstance(packed_entry, str) or packed_entry not in names:
                        report.error(
                            f"ZIP 内缺少 plugin.json 声明的入口文件：{packed_entry!r}", where,
                        )
                    packed_icon = packed.get("icon") if isinstance(packed, dict) else None
                    if isinstance(packed_icon, str) and packed_icon not in names:
                        report.error(f"ZIP 内缺少 icon 文件：{packed_icon}", where)
            roots = {name.split("/")[0] for name in names if "/" in name}
            if roots and all("/" in name for name in names) and len(roots) == 1:
                only = roots.pop()
                if only != "assets":
                    report.error("ZIP 根目录不能套一层插件文件夹", where)
    except FileNotFoundError:
        report.error(f"ZIP 文件不存在：{path}", where)
    except zipfile.BadZipFile:
        report.error("不是有效的 ZIP", where)
    except OSError as error:
        report.error(f"无法读取 ZIP：{error}", where)


def validate_zip_plugin_id(path, report):
    """返回 ZIP 内 plugin.json 的 id，供 --registration 交叉核对。"""
    try:
        with zipfile.ZipFile(path) as archive:
            if "plugin.json" not in archive.namelist():
                return None
            packed = json.loads(archive.read("plugin.json").decode("utf-8-sig"))
            return packed.get("id") if isinstance(packed, dict) else None
    except (FileNotFoundError, zipfile.BadZipFile, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def cmd_validate(args):
    root = Path(args.plugin).resolve()
    registration = None
    zip_registration_id = None
    if args.registration:
        meta = read_json(root / "plugin.json", Report(), "plugin.json") or {}
        target = Path(args.registration).resolve()
        if target.is_dir():
            target = target / f"{meta.get('id')}.json"
        registration = read_json(target, Report(), "registration")
    report = validate_plugin(
        root,
        allowed_links=(registration or {}).get("allowedLinks"),
        submitting=registration is not None,
    )
    if args.zip:
        zip_path = Path(args.zip).resolve()
        zip_report = Report()
        validate_zip(zip_path, zip_report)
        zip_registration_id = validate_zip_plugin_id(zip_path, zip_report)
        for level, where, message in zip_report.items:
            report.items.append((level, where, message))
    meta = {}
    program = {}
    if args.registration:
        meta = read_json(root / "plugin.json", Report(), "plugin.json") or {}
        entry = meta.get("entry")
        program = (
            read_json(root / entry, Report(), entry)
            if isinstance(entry, str) and entry
            else {}
        )
        if registration is None:
            report.error(f"登记文件不存在：{args.registration}", "registration")
        if registration and program:
            registration["_filename"] = target.name
            registration["_in_register_dir"] = target.parent.name.lower() == "registrations"
            check_registration(registration, meta, program, report)
            if zip_registration_id and zip_registration_id != registration.get("id"):
                report.error(
                    f"ZIP 内 plugin.json 的 id 是 {zip_registration_id!r}，"
                    f"与登记文件 id={registration.get('id')!r} 不一致；"
                    "模块仓库 CI 会直接拒绝，请重新打包并更新 Release 附件",
                    "zip",
                )
    report.print(verbose=args.all)
    if report.errors:
        print(f"\n{len(report.errors)} 个 error")
        return 1
    print("\n预检通过。客户端解析仍是最终标准。")
    return 0


ICON_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
  <rect width="96" height="96" rx="24" fill="{color}"/>
  <text x="48" y="48" fill="#fff" font-family="sans-serif" font-size="40"
        font-weight="600" text-anchor="middle" dominant-baseline="central">{mark}</text>
</svg>
"""

README_TEMPLATE = """# {name}

{description}

## 配置

{config}

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 上传失败 | 核对地址与凭证，见上方字段说明 |
"""

LICENSE_TEMPLATE = """MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

PLUGIN_TEMPLATE = {
    "packageVersion": 1,
    "runtime": "http-v2",
    "entry": "uploader.json",
    "id": "",
    "name": "",
    "version": "1.0.0",
    "description": "",
    "author": "",
    "homepage": "",
    "repository": "",
    "icon": "assets/icon.svg",
    "mark": "",
    "color": "#6377E8",
}

PROGRAM_TEMPLATE = {
    "schemaVersion": 2,
    "requires": [],
    "permissions": {
        "network": [],
        "readSelectedFile": True,
        "allowInsecureHttp": False,
    },
    "config": [],
    "upload": {
        "method": "POST",
        "url": "",
        "headers": {"Accept": "application/json"},
        "body": {"type": "multipart", "fileField": "file"},
        "response": {"url": "", "successStatuses": [200]},
        "followRedirects": False,
        "timeoutSeconds": 60,
        "errors": {},
    },
}


def cmd_new(args):
    root = Path(args.output).resolve() / args.slug
    if root.exists() and any(root.iterdir()):
        print(f"目录已存在且非空：{root}")
        return 1
    if not args.endpoint and not args.host:
        print("需要 --host api.example.com，或加 --endpoint 让用户自填图床地址")
        return 1
    if args.host and not re.fullmatch(r"[A-Za-z0-9.-]+", args.host):
        print("--host 只写主机名，例如 api.example.com，不要带协议或路径")
        return 1
    if not ID_RE.match(args.id):
        print("--id 必须是小写反向域名，例如 io.github.user.easyimages")
        return 1
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(exist_ok=True)
    (root / "releases").mkdir(exist_ok=True)
    mark = (args.mark or args.name[:2]).upper()[:3]
    meta = dict(PLUGIN_TEMPLATE)
    meta.update(
        {
            "id": args.id,
            "name": args.name,
            "description": args.description or f"{args.name} 图床",
            "author": args.author,
            "repository": f"https://github.com/{args.repo}",
            "mark": mark,
            "color": args.color,
        }
    )
    if args.homepage:
        meta["homepage"] = args.homepage
    else:
        meta.pop("homepage", None)
    program = json.loads(json.dumps(PROGRAM_TEMPLATE))
    if args.endpoint:
        program["permissions"]["network"] = ["config.baseUrl"]
        program["upload"]["url"] = f"${{normalizeBaseUrl(config.baseUrl)}}{args.path}"
    else:
        program["permissions"]["network"] = [args.host]
        program["upload"]["url"] = f"https://{args.host}{args.path}"
    program["upload"]["response"]["url"] = args.url_path
    config = []
    if args.endpoint:
        config.append(
            {
                "key": "baseUrl",
                "label": "图床地址",
                "type": "text",
                "role": "endpoint",
                "required": True,
                "hint": "例如 https://img.example.com；装在子目录时包含子目录",
            }
        )
    if args.auth == "token":
        config.append(
            {
                "key": "token",
                "label": "API Token",
                "type": "secret",
                "role": "token",
                "required": True,
                "hint": "图床后台生成的 API Token",
            }
        )
    elif args.auth == "account":
        config += [
            {
                "key": "account",
                "label": "账号",
                "type": "text",
                "role": "account",
                "required": True,
            },
            {
                "key": "password",
                "label": "密码",
                "type": "secret",
                "required": True,
            },
        ]
    program["config"] = config
    if args.auth == "token":
        program["upload"]["headers"]["Authorization"] = "Bearer ${config.token}"
    write_json(root / "plugin.json", meta)
    write_json(root / "uploader.json", program)
    lines = []
    for field in config:
        lines.append(f"- `{field['label']}`（`{field['key']}`）：{field.get('hint', '')}")
    (root / "readme.md").write_text(
        README_TEMPLATE.format(
            name=args.name,
            description=meta["description"],
            config="\n".join(lines) or "本插件无需配置。",
        ),
        encoding="utf-8",
    )
    (root / "assets" / "icon.svg").write_text(
        ICON_TEMPLATE.format(color=args.color, mark=mark), encoding="utf-8"
    )
    (root / "LICENSE").write_text(
        LICENSE_TEMPLATE.format(year=time.gmtime().tm_year, author=args.author),
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(
        "releases/\n__pycache__/\n*.zip\n", encoding="utf-8"
    )
    registration = registration_from_plugin(meta, program, args.repo)
    (root / "registration.json").write_text(
        json.dumps(registration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已创建：{root}")
    print("下一步：按抓包结果填写 uploader.json 的 body.fields 与 response 路径，然后 validate。")
    return 0


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_register(args):
    root = Path(args.plugin).resolve()
    report = validate_plugin(root)
    meta = read_json(root / "plugin.json", Report(), "plugin.json") or {}
    entry = meta.get("entry")
    program = (
        read_json(root / entry, Report(), entry or "entry")
        if isinstance(entry, str) and entry
        else {}
    )
    if report.errors:
        report.print()
        print("插件本身未通过预检，未生成登记文件")
        return 1
    registration = registration_from_plugin(meta, program, args.repo)
    if not registration.get("releaseRepository"):
        print("需要 --repo owner/repo，或在 plugin.json 写 repository")
        return 1
    if args.allowed_links:
        hosts = [item.strip() for item in args.allowed_links.split(",") if item.strip()]
        if any("/" in host or ":" in host for host in hosts):
            print("allowedLinks 只写主机名，例如 docs.example.com")
            return 1
        registration["allowedLinks"] = hosts
    if args.asset_prefix:
        if "/" in args.asset_prefix or "\\" in args.asset_prefix:
            print("assetPrefix 不能包含路径分隔符")
            return 1
        registration["assetPrefix"] = args.asset_prefix
    if args.out:
        out = Path(args.out).resolve()
        if out.suffix == "":
            out = out / f"{registration['id']}.json"
    else:
        out = root / "registration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, registration)
    check_report = Report()
    check_registration(
        {**registration, "_filename": out.name,
         "_in_register_dir": out.parent.name.lower() == "registrations"},
        meta, program, check_report,
    )
    if check_report.errors:
        check_report.print()
        print("登记文件已写出，但仍有需要修正的问题")
        return 1
    print(f"已生成：{out}")
    print(json.dumps(registration, ensure_ascii=False, indent=2))
    return 0


def run(cmd, cwd=None, check=True, capture=True):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"命令失败（{result.returncode}）：{' '.join(cmd)}\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def tool(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"未找到 {name}，请先安装或改用指导模式")
    return path


def detect_environment():
    env = {
        "git": shutil.which("git") is not None,
        "gh": shutil.which("gh") is not None,
        "gh_authed": False,
        "user": None,
        "git_identity": False,
    }
    if env["gh"]:
        result = run(["gh", "auth", "status"], check=False)
        env["gh_authed"] = result.returncode == 0
        if env["gh_authed"]:
            who = run(["gh", "api", "user", "-q", ".login"], check=False)
            if who.returncode == 0:
                env["user"] = who.stdout.strip() or None
    if not env["user"] and env["git"]:
        who = run(["git", "config", "--get", "user.name"], check=False)
        if who.returncode == 0:
            env["user"] = who.stdout.strip() or None
    if env["git"]:
        name = run(["git", "config", "--get", "user.name"], check=False)
        mail = run(["git", "config", "--get", "user.email"], check=False)
        env["git_identity"] = (
            name.returncode == 0
            and bool(name.stdout.strip())
            and mail.returncode == 0
            and bool(mail.stdout.strip())
        )
    return env


def cmd_publish(args):
    root = Path(args.plugin).resolve()
    report = validate_plugin(root)
    if report.errors:
        report.print()
        print("插件未通过预检，未执行发布")
        return 1
    meta = json.loads((root / "plugin.json").read_text(encoding="utf-8-sig"))
    entry = meta.get("entry")
    program = (
        json.loads((root / entry).read_text(encoding="utf-8-sig"))
        if isinstance(entry, str) and entry
        else {}
    )
    env = detect_environment()
    print(f"环境：git={'有' if env['git'] else '无'} "
          f"gh={'已登录' if env['gh_authed'] else ('有未登录' if env['gh'] else '无')} "
          f"user={env['user'] or '未知'}")
    if env["git"] and not env["git_identity"]:
        print(
            "提示：git 还没设置提交身份，提交会失败。先运行：\n"
            "  git config --global user.name \"你的名字\"\n"
            "  git config --global user.email \"你的邮箱\""
        )

    owner = args.owner or env["user"]
    repo = args.repo or meta.get("repository", "")
    if repo.startswith("https://github.com/"):
        repo = repo[len("https://github.com/"):]
    repo = repo.strip("/")
    if not repo and owner:
        repo = f"{owner}/{args.repo_name or 'picora-plugin-' + meta['id'].split('.')[-1]}"
    if "/" not in repo:
        print("无法确定插件仓库，请用 --repo owner/repo 指定")
        return 1
    owner = repo.split("/")[0].lower()
    if not str(meta.get("id", "")).startswith(f"io.github.{owner}."):
        guessed = re.sub(r"[^a-z0-9]", "", owner)
        if owner and str(meta.get("id", "")).startswith(f"io.github.{guessed}."):
            print(
                f"插件 id={meta.get('id')} 与仓库所有者 {owner} 不匹配；"
                f"投稿要求 id 以 io.github.{owner}. 开头，用户名 {owner} 里的连字符不能删，"
                f"不能写成 io.github.{guessed}。请修正 plugin.json 的 id 后重试。"
            )
        else:
            print(
                f"插件 id={meta.get('id')} 与仓库所有者 {owner} 不匹配；"
                f"投稿要求 id 以 io.github.{owner}. 开头。请修正 plugin.json 的 id 后重试。"
            )
        return 1
    catalog = args.catalog or CATALOG_REPO
    if "/" not in catalog:
        print("无法确定模块仓库，请用 --catalog owner/repo 指定")
        return 1

    steps = ["init", "commit", "create", "push", "release", "register", "fork", "pr"]
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        unknown = wanted - set(steps)
        if unknown:
            print(f"未知步骤：{', '.join(sorted(unknown))}；可用：{', '.join(steps)}")
            return 1
        steps = [step for step in steps if step in wanted]

    if not env["git"]:
        return guide_mode(root, meta, program, repo, catalog, steps, "当前环境没有 git")
    if not args.execute:
        print("\n将执行：")
        for step in steps:
            print(f"  - {describe_step(step, repo, catalog, meta)}")
        print("\n这是预演。加 --execute 真正执行；创建公开仓库、Fork、开 PR 会对外可见。")
        return 0
    if not env["gh_authed"] and {"create", "release", "fork", "pr"} & set(steps):
        return guide_mode(
            root, meta, program, repo, catalog, steps,
            "gh 未安装或未登录，公开动作需手动完成",
        )

    return execute_steps(root, meta, program, repo, catalog, steps, args, env)


def describe_step(step, repo, catalog, meta):
    return {
        "init": f"git init 并在 {repo} 初始化仓库",
        "commit": "提交插件源码",
        "create": f"创建公开仓库 {repo} 并推送",
        "push": f"推送到 {repo}",
        "release": f"发布 v{meta['version']} 并上传插件 ZIP",
        "register": "生成 registration.json",
        "fork": f"Fork {catalog}",
        "pr": f"向 {catalog} 提交登记 PR",
    }[step]


def guide_mode(root, meta, program, repo, catalog, steps, reason):
    print(f"\n改为指导模式：{reason}\n")
    registration = registration_from_plugin(meta, program, repo)
    report = Report()
    check_registration(dict(registration), meta, program, report)
    if report.errors:
        print("登记文件自检未通过，投稿前必须先修正：")
        report.print()
        print("")
    script = Path(__file__).resolve()
    python = sys.executable or "python"
    print("1. 插件仓库")
    print(f"   cd \"{root}\"")
    print("   git init && git add . && git commit -m \"feat: 初始版本\"")
    print("   git branch -M main")
    print(f"   git remote add origin https://github.com/{repo}.git")
    print("   git push -u origin main")
    print("\n2. Release")
    print(f"   \"{python}\" \"{script}\" pack \"{root}\"")
    print(f"   在 https://github.com/{repo}/releases/new 发布正式 Release，")
    print(f"   上传 releases/*.picora-plugin.zip（不能是草稿或预发布）")
    print("\n3. 登记文件 registrations/<id>.json")
    print(json.dumps(registration, ensure_ascii=False, indent=2))
    print(f"\n4. Fork 并在 {catalog} 提交 PR")
    print(f"   Fork https://github.com/{catalog}")
    print(f"   在 registrations/ 下新增 {registration['id']}.json，内容同上")
    print(f"   向 {catalog}:main 提交 Pull Request")
    return 0


def execute_steps(root, meta, program, repo, catalog, steps, args, env):
    """发布前再次核对登记文件，避免把不一致的权限提交上去。"""

    def ensure_registration_ok(registration, meta, program):
        report = Report()
        check_registration(dict(registration), meta, program, report)
        if report.errors:
            report.print()
            raise RuntimeError("登记文件自检未通过，已停止")

    log = []
    clone_cache = []

    def step_init():
        if not (root / ".git").exists():
            run(["git", "init"], cwd=root)
            log.append("已初始化 git 仓库")
        else:
            log.append("已有 git 仓库，跳过 init")

    def step_commit():
        run(["git", "add", "-A"], cwd=root)
        status = run(["git", "status", "--porcelain"], cwd=root)
        if status.stdout.strip():
            run(["git", "commit", "-m", f"feat: {meta['name']} {meta['version']}"], cwd=root)
            log.append("已提交插件源码")
        else:
            log.append("没有待提交改动")
        # 必须在首次提交之后改名，空仓库上 `git branch -M` 会失败。
        head = run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, check=False)
        if head.returncode == 0:
            run(["git", "branch", "-M", "main"], cwd=root)
        else:
            raise RuntimeError("仓库里没有可提交的插件文件，请检查 .gitignore 或目录内容")
        if not (root / ".gitignore").is_file():
            log.append("提示：仓库没有 .gitignore，确认 releases/ 与 *.zip 不会提交")

    def step_create():
        existing = run(["gh", "repo", "view", repo], check=False)
        if existing.returncode == 0:
            run(["git", "remote", "remove", "origin"], cwd=root, check=False)
            run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=root)
            log.append(f"仓库已存在，已设置 origin")
        else:
            run(
                ["gh", "repo", "create", repo, "--public", "--source=.", "--remote=origin"],
                cwd=root,
            )
            log.append(f"已创建公开仓库 {repo}")

    def step_push():
        run(["git", "push", "-u", "origin", "main"], cwd=root)
        log.append("已推送 main")

    def step_release():
        tag = f"v{meta['version']}"
        pack_dir = root / "releases"
        pack_dir.mkdir(exist_ok=True)
        target = pack_dir / f"{meta['id'].split('.')[-1]}-{meta['version']}.picora-plugin.zip"
        build_zip(root, target)
        zip_report = Report()
        validate_zip(target, zip_report)
        if zip_report.errors:
            zip_report.print(verbose=True)
            target.unlink(missing_ok=True)
            raise RuntimeError("打包结果未通过 ZIP 校验，未发布 Release")
        exists = run(["gh", "release", "view", tag, "--repo", repo], check=False)
        if exists.returncode == 0:
            raise RuntimeError(
                f"{tag} 已存在。不要覆盖已发布版本的附件；请递增 plugin.json 的 version 后重试"
            )
        run(["git", "tag", tag], cwd=root, check=False)
        run(["git", "push", "origin", tag], cwd=root)
        run(
            ["gh", "release", "create", tag, str(target), "--repo", repo,
             "--title", f"{meta['name']} {meta['version']}", "--notes", "见 readme.md"],
            cwd=root,
        )
        log.append(f"已发布 Release {tag}")

    def step_register():
        registration = registration_from_plugin(meta, program, repo)
        ensure_registration_ok(registration, meta, program)
        out = root / "registration.json"
        write_json(out, registration)
        log.append(f"已生成 {out}")

    def catalog_clone():
        if clone_cache:
            return clone_cache[0]
        workdir = Path(tempfile.mkdtemp(prefix="picora-catalog-"))
        run(["gh", "repo", "fork", catalog, "--clone"], cwd=workdir, check=False)
        clone = workdir / catalog.split("/")[-1]
        if not clone.exists():
            owner = (env.get("user") or "me")
            fork_url = f"https://github.com/{owner}/{catalog.split('/')[-1]}.git"
            run(["git", "clone", fork_url, str(clone)])
        run(["git", "remote", "add", "upstream", f"https://github.com/{catalog}.git"],
            cwd=clone, check=False)
        clone_cache.append(clone)
        return clone

    def step_fork():
        clone = catalog_clone()
        log.append(f"已准备 Fork 仓库：{clone}")

    def step_pr():
        registration = registration_from_plugin(meta, program, repo)
        ensure_registration_ok(registration, meta, program)
        clone = catalog_clone()
        branch = f"add-{meta['id'].split('.')[-1]}"
        run(["git", "checkout", "-B", branch], cwd=clone)
        target = clone / "registrations" / f"{registration['id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json(target, registration)
        run(["git", "add", str(target.relative_to(clone))], cwd=clone)
        run(["git", "commit", "-m", f"feat: add {meta['name']} plugin"], cwd=clone)
        run(["git", "push", "-u", "origin", branch], cwd=clone)
        body = args.body or f"{meta['name']} 图床插件。"
        fork_owner = env.get("user") or repo.split("/")[0]
        result = run(
            ["gh", "pr", "create", "--repo", catalog, "--base", "main",
             "--head", f"{fork_owner}:{branch}",
             "--title", f"Add {meta['name']} plugin", "--body", body],
            cwd=clone,
        )
        log.append(result.stdout.strip() or "已提交 PR")

    handlers = {
        "init": step_init,
        "commit": step_commit,
        "create": step_create,
        "push": step_push,
        "release": step_release,
        "register": step_register,
        "fork": step_fork,
        "pr": step_pr,
    }
    try:
        for step in steps:
            handlers[step]()
    except RuntimeError as error:
        print("\n".join(f"- {line}" for line in log))
        print(f"\n失败：{error}")
        print("已完成的步骤不会回滚；修正后可用 --only 继续剩余步骤。")
        return 1
    print("\n".join(f"- {line}" for line in log))
    return 0


EXCLUDED = {
    "tools", "docs", "releases", "registrations", ".git", ".github",
    ".idea", "tests", "__pycache__",
}


def collect_files(root):
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in EXCLUDED:
            continue
        if path.name == "registration.json":
            continue
        if path.suffix.lower() == ".zip":
            continue
        if path.name.startswith("."):
            continue
        files.append((rel, path))
    return files


def build_zip(root, target):
    files = collect_files(root)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel, path in files:
            archive.write(path, rel.as_posix())
        if not any(rel.parts[0] == "assets" for rel, _ in files):
            archive.writestr("assets/", "")
    return files


def cmd_pack(args):
    root = Path(args.plugin).resolve()
    report = validate_plugin(root)
    if report.errors:
        report.print(verbose=args.all)
        print("预检未通过，未生成 ZIP")
        return 1
    meta = json.loads((root / "plugin.json").read_text(encoding="utf-8-sig"))
    name = args.name or meta["id"].split(".")[-1]
    version = meta["version"]
    out_dir = Path(args.out).resolve() if args.out else root / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}-{version}.picora-plugin.zip"
    files = build_zip(root, target)
    zip_report = Report()
    validate_zip(target, zip_report)
    if zip_report.errors:
        zip_report.print(verbose=True)
        target.unlink(missing_ok=True)
        return 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    with zipfile.ZipFile(target) as archive:
        names = [info.filename for info in archive.infolist()]
    print(f"已生成：{target}")
    print(f"大小：{target.stat().st_size} 字节，条目：{len(names)}")
    print(f"SHA256：{digest}")
    for name in names:
        print(f"  {name}")
    return 0


def normalize_base_url(value):
    text = str(value).strip()
    if not text:
        raise ValueError("请先填写图床基础 URL")
    if not re.match(r"^[a-z][a-z\d+.-]*:", text, re.I):
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("图床网址只能使用 HTTP/HTTPS，且不能带账号密码")
    if not re.fullmatch(r"[A-Za-z0-9.\-]+(?::\d{1,5})?", parsed.netloc):
        raise ValueError("图床网址的主机名无效，例如 https://img.example.com")
    if parsed.query or parsed.fragment:
        raise ValueError("图床网址不能带查询参数或锚点")
    if re.search(r"/upload/?$", parsed.path, re.I):
        raise ValueError("请填写基础网址，不要在末尾添加 /upload")
    path = re.sub(r"/+$", "", parsed.path)
    base = f"{parsed.scheme}://{parsed.netloc}{path}"
    return base.rstrip("/")


class Renderer:
    def __init__(self, config, image, root):
        self.config = config
        self.image = Path(image) if image else None
        self.root = root
        self.cache = {}
        self.now = time.time()
        self.uuid = str(uuid.uuid4())

    def clean(self, value):
        if value is None or value in {"None", "undetermined"}:
            return ""
        return value

    def resolve(self, key):
        if key.startswith("assets/"):
            path = self.root / key
            if not path.is_file():
                raise ValueError(f"资源不存在：{key}")
            return path.read_bytes()
        if key == "uuid":
            return self.uuid
        if key == "time.millis":
            return int(self.now * 1000)
        if key == "time.unix":
            return int(self.now)
        if key.startswith("file."):
            if not self.image:
                raise ValueError("需要 --image")
            name = key[5:]
            if name == "path":
                return str(self.image)
            if name == "name":
                return self.image.name
            data = self.image.read_bytes()
            if name == "bytes":
                return data
            if name == "base64":
                return base64.b64encode(data).decode()
            if name == "mime":
                return mimetypes.guess_type(self.image.name)[0] or "application/octet-stream"
            raise ValueError(f"未知文件变量：{key}")
        if key.startswith("config."):
            return self.clean(self.config.get(key[7:]))
        if key.startswith("steps."):
            # 前置步骤的输出无法离线获取，保留占位符以便检查其余部分。
            return "${" + key + "}"
        raise ValueError(f"回放不支持模板变量：{key}")

    def evaluate(self, expr):
        match = FUNC_RE.match(expr)
        if not match:
            return self.resolve(expr)
        name, raw = match.group(1), match.group(2)
        args = [self.evaluate(item.strip()) for item in raw.split(",")]
        if name == "urlEncode" and len(args) == 1:
            # 与客户端 Uri.encodeComponent 保持一致（保留 -_.!~*'() ）
            return quote(str(args[0]), safe="-_.!~*'()")
        if name == "base64" and len(args) == 1:
            return base64.b64encode(self.as_bytes(args[0])).decode()
        if name == "sha256" and len(args) == 1:
            return hashlib.sha256(self.as_bytes(args[0])).hexdigest()
        if name == "hmacSha256" and len(args) == 2:
            return hmac.new(self.as_bytes(args[0]), self.as_bytes(args[1]), hashlib.sha256).hexdigest()
        if name == "basicAuth" and len(args) == 2:
            return "Basic " + base64.b64encode(f"{args[0]}:{args[1]}".encode()).decode()
        if name == "normalizeBaseUrl" and len(args) == 1:
            return normalize_base_url(args[0])
        if name == "assetText" and len(args) == 1:
            return self.as_bytes(args[0]).decode("utf-8")
        raise ValueError(f"模板函数参数无效：{expr}")

    @staticmethod
    def as_bytes(value):
        return value if isinstance(value, bytes) else str(value).encode()

    def render(self, value):
        if isinstance(value, list):
            return [self.render(item) for item in value]
        if isinstance(value, dict):
            return {key: self.render(item) for key, item in value.items()}
        if not isinstance(value, str):
            return value
        exact = re.fullmatch(r"\$\{([^}]+)\}", value)
        if exact:
            return self.evaluate(exact.group(1).strip())
        return EXPR_RE.sub(lambda m: str(self.evaluate(m.group(1).strip())), value)


def read_path(value, path):
    if path == "$":
        return value
    current = value
    normalized = re.sub(r"^\$\.?", "", path)
    for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_-]*)|\[(\d+)\]", normalized):
        if match.group(1):
            if not isinstance(current, dict):
                return None
            current = current.get(match.group(1))
        else:
            index = int(match.group(2))
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
    return current


def condition_matches(condition, data):
    value = read_path(data, condition.get("path", ""))
    if "equals" in condition:
        expected = condition["equals"]
        if isinstance(expected, bool) or isinstance(value, bool):
            return value is expected
        if isinstance(expected, (int, float)) and isinstance(value, (int, float)):
            return float(value) == float(expected)
        return value == expected and type(value) is type(expected)
    if "exists" in condition:
        return (value is not None) == bool(condition["exists"])
    words = condition.get("containsAny")
    if isinstance(words, list):
        text = str(value).lower() if value is not None else ""
        return any(word.lower() in text for word in words)
    return True


def mask(text, secrets):
    out = str(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        out = out.replace(secret, "***")
    return out


def multipart_body(fields, file_field, image_bytes, filename, mime):
    boundary = "----PicoraReplay" + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        chunks.append(str(value).encode() + b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    )
    chunks.append(f"Content-Type: {mime}\r\n\r\n".encode())
    chunks.append(image_bytes + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def cmd_replay(args):
    root = Path(args.plugin).resolve()
    report = validate_plugin(root)
    if report.errors and not args.force:
        report.print(verbose=False)
        print("预检未通过，未回放；确认无误可加 --force")
        return 1
    meta = json.loads((root / "plugin.json").read_text(encoding="utf-8-sig"))
    program = json.loads((root / meta["entry"]).read_text(encoding="utf-8-sig"))
    has_prepare = bool(program.get("prepare"))
    upload = program.get("upload")
    mode_fields = []
    modes = program.get("authModes")
    if isinstance(modes, list) and modes:
        chosen = None
        usable = [m for m in modes if isinstance(m, dict)]
        if args.auth_mode:
            chosen = next((m for m in usable if m.get("id") == args.auth_mode), None)
            if chosen is None:
                print(
                    f"没有名为 {args.auth_mode} 的鉴权方式；可选："
                    + "、".join(str(m.get("id")) for m in usable)
                )
                return 1
        elif usable:
            chosen = usable[0]
            print(
                f"插件声明了 {len(usable)} 种鉴权方式，默认回放 {chosen.get('id')}；"
                "可用 --auth-mode 指定"
            )
        if chosen is not None:
            upload = chosen.get("upload")
            mode_fields = [f for f in chosen.get("config") or [] if isinstance(f, dict)]
            has_prepare = has_prepare or bool(chosen.get("prepare"))
    if not isinstance(upload, dict):
        print("插件没有可回放的上传请求")
        return 1
    if has_prepare and args.send:
        print(
            "插件含 prepare 步骤，回放不执行前置请求，无法完成真实上传。\n"
            "下面只渲染上传请求，请在客户端实测。"
        )
        args.send = False
    config = {}
    if args.config:
        try:
            config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            print(f"配置文件不存在：{args.config}")
            return 1
        except json.JSONDecodeError as error:
            print(f"配置文件不是合法 JSON：{error}")
            return 1
        if not isinstance(config, dict):
            print("配置文件必须是 JSON 对象，例如 {\"token\": \"...\"}")
            return 1
    missing = [
        field.get("key")
        for field in list(program.get("config", [])) + mode_fields
        if isinstance(field, dict)
        and field.get("key")
        and field.get("required")
        and config.get(field.get("key")) in (None, "")
    ]
    if missing:
        print("缺少必填配置：" + "、".join(missing))
        if args.send and not args.force:
            print("补齐 config 后重试，或加 --force")
            return 1
    renderer = Renderer(config, args.image, root)
    try:
        url = renderer.render(upload["url"])
        headers = renderer.render(upload.get("headers", {}))
        query = renderer.render(upload.get("query", {}))
        body_spec = upload.get("body", {})
        kind = body_spec.get("type", "multipart")
        fields = renderer.render(body_spec.get("fields", {}))
    except (ValueError, OSError) as error:
        print(f"渲染请求失败：{error}")
        return 1
    if query:
        separator = "&" if "?" in url else "?"
        url = url + separator + urlencode({k: v for k, v in query.items()}, doseq=True)
    image = Path(args.image) if args.image else None
    payload, content_type = None, None
    if kind != "none":
        if not image or not image.is_file():
            print("需要 --image 指向一张真实图片")
            return 1
        data = image.read_bytes()
        mime = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
        if kind == "multipart":
            payload, content_type = multipart_body(
                fields, body_spec.get("fileField", "file"), data, image.name, mime
            )
        elif kind == "binary":
            payload, content_type = data, mime
        elif kind == "json":
            payload = json.dumps(fields, ensure_ascii=False).encode()
            content_type = "application/json"
        elif kind == "form":
            payload = urlencode(fields).encode()
            content_type = "application/x-www-form-urlencoded"
        else:
            print(f"回放不支持 body.type={kind}")
            return 1
    secret_keys = {
        field["key"]
        for field in list(program.get("config", [])) + mode_fields
        if isinstance(field, dict)
        and (field.get("type") == "secret" or field.get("role") == "token")
    }
    secrets = {
        str(config[key]) for key in secret_keys if config.get(key) not in (None, "")
    }
    print(f"{upload.get('method', 'POST').upper()} {mask(url, secrets)}")
    for key, value in headers.items():
        print(f"{key}: {mask(value, secrets)}")
    if content_type:
        print(f"Content-Type: {content_type}")
    if kind == "multipart":
        print(f"文件字段：{body_spec.get('fileField', 'file')}")
    if fields:
        print("字段：")
        for key, value in fields.items():
            shown = "***" if str(value) in secrets else mask(value, secrets)
            print(f"  {key} = {shown}")
    parsed = urlparse(url)
    print(f"目标主机：{parsed.scheme}://{parsed.netloc}")
    if not args.send:
        print("\n未发送（dry-run）。确认后加 --send。")
        return 0

    import http.client

    timeout = upload.get("timeoutSeconds", 60)
    connection_class = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    connection = connection_class(parsed.netloc, timeout=timeout)
    if content_type:
        headers.setdefault("Content-Type", content_type)
    try:
        connection.request(upload.get("method", "POST").upper(), target, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
    except (OSError, http.client.HTTPException) as error:
        print(f"\n发送失败：{error}")
        print("网络不可达或被本机安全策略拦截；确认连通性后再在客户端实测。")
        return 2
    finally:
        connection.close()
    text = raw.decode("utf-8", "replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = text
    print(f"\nHTTP {status}")
    print(mask(text[:4000], secrets))
    spec = upload.get("response", {})
    statuses = spec.get("successStatuses", [200, 201])
    ok = status in statuses
    if ok and "success" in spec:
        ok = condition_matches(spec["success"], data)
    print(f"\n结果：{'成功' if ok else '失败'}")
    if ok:
        image_url = read_path(data, spec.get("url", ""))
        if isinstance(image_url, str):
            image_url = urljoin(url, image_url)
        delete_key = read_path(data, spec["deleteKey"]) if spec.get("deleteKey") else None
        print(f"图片：{image_url}")
        if delete_key is not None:
            print(f"deleteKey：{delete_key!r}")
            if isinstance(delete_key, (dict, list)):
                print("警告：deleteKey 必须是标量，客户端会拒绝")
    else:
        message = read_path(data, spec["errorMessage"]) if spec.get("errorMessage") else None
        code = read_path(data, spec["errorCode"]) if spec.get("errorCode") else None
        mapped = upload.get("errors", {}).get(str(status))
        print(f"错误码：{code}，消息：{message}，HTTP 映射：{mapped}")
    if args.json:
        print(mask(json.dumps({"status": status, "ok": ok, "body": data}, ensure_ascii=False), secrets))
    return 0 if ok else 2


def main():
    parser = argparse.ArgumentParser(description="Picora 图床插件工具")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="预检插件目录")
    validate.add_argument("plugin")
    validate.add_argument("--zip", help="同时检查已打包的 ZIP")
    validate.add_argument("--registration", help="同时核对登记文件")
    validate.add_argument("--all", action="store_true", help="显示全部警告")
    validate.set_defaults(func=cmd_validate)

    new = sub.add_parser("new", help="按图床信息生成插件骨架")
    new.add_argument("--output", default=".", help="父目录，默认当前目录")
    new.add_argument("--slug", required=True, help="目录名，例如 easyimages")
    new.add_argument("--id", required=True, help="反向域名，例如 io.github.user.host")
    new.add_argument("--name", required=True, help="插件显示名")
    new.add_argument("--author", required=True)
    new.add_argument("--repo", required=True, help="owner/repo")
    new.add_argument("--host", help="请求主机，例如 api.example.com；用 --endpoint 时可不填")
    new.add_argument("--path", default="/upload", help="上传路径")
    new.add_argument("--url-path", default="data.url", help="图片链接路径")
    new.add_argument("--auth", choices=["none", "token", "account"], default="token")
    new.add_argument("--endpoint", action="store_true", help="增加可配置图床地址字段")
    new.add_argument("--description", default="")
    new.add_argument("--homepage", default="")
    new.add_argument("--mark", default="")
    new.add_argument("--color", default="#6377E8")
    new.set_defaults(func=cmd_new)

    register = sub.add_parser("register", help="从插件生成登记文件")
    register.add_argument("plugin")
    register.add_argument("--repo", help="覆盖 owner/repo")
    register.add_argument("--out", help="输出文件或目录，默认 <插件目录>/registration.json")
    register.add_argument("--allowed-links", help="逗号分隔的主机名，写入 allowedLinks")
    register.add_argument("--asset-prefix", help="Release 附件名前缀")
    register.set_defaults(func=cmd_register)

    publish = sub.add_parser("publish", help="发布插件并投稿（默认只预演）")
    publish.add_argument("plugin")
    publish.add_argument("--owner", help="GitHub 用户名；默认取 gh 或 git 配置")
    publish.add_argument("--repo", help="插件仓库 owner/repo，或完整仓库 URL")
    publish.add_argument("--repo-name", help="仓库名，默认 picora-plugin-<name>")
    publish.add_argument("--catalog", help="模块仓库 owner/repo")
    publish.add_argument("--only", help="只执行部分步骤，逗号分隔")
    publish.add_argument("--body", help="PR 说明")
    publish.add_argument("--execute", action="store_true", help="真正执行")
    publish.set_defaults(func=cmd_publish)

    pack = sub.add_parser("pack", help="打包 .picora-plugin.zip")
    pack.add_argument("plugin")
    pack.add_argument("--name", help="产物前缀，默认取 id 最后一段")
    pack.add_argument("--out", help="输出目录，默认 <插件目录>/releases")
    pack.add_argument("--all", action="store_true")
    pack.set_defaults(func=cmd_pack)

    replay = sub.add_parser("replay", help="按 uploader.json 回放一次上传")
    replay.add_argument("plugin")
    replay.add_argument("-c", "--config", help="配置 JSON，例如 {\"baseUrl\": \"...\"}")
    replay.add_argument("-i", "--image", help="测试图片")
    replay.add_argument("--send", action="store_true", help="真正发送请求")
    replay.add_argument("--auth-mode", help="插件有多种鉴权方式时指定回放哪一种")
    replay.add_argument("--force", action="store_true", help="忽略预检错误")
    replay.add_argument("--json", action="store_true", help="追加输出原始响应 JSON")
    replay.set_defaults(func=cmd_replay)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
