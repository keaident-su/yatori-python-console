# -*- coding: utf-8 -*-
"""智慧树无浏览器认证状态与用户主动会话导入。

本模块只处理用户主动提供的 Cookie/token。不会读取浏览器、APP 数据库、
系统凭据目录，也不会生成或伪造验证码挑战结果。
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

from Crypto.Cipher import AES
from requests.cookies import RequestsCookieJar, create_cookie


class LoginStatus(str, Enum):
    SUCCESS = "LOGIN_SUCCESS"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    SMS_REQUIRED = "SMS_REQUIRED"
    EXTRA_AUTH_REQUIRED = "EXTRA_AUTH_REQUIRED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    UNSUPPORTED = "UNSUPPORTED_LOGIN"
    NETWORK_ERROR = "NETWORK_ERROR"


@dataclass
class LoginChallenge:
    """需要用户确认或补充输入的登录节点。"""
    kind: str
    message: str
    retryable: bool = True
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoginResult:
    """平台无关的登录结果载体。"""
    status: LoginStatus
    message: str = ""
    challenge: LoginChallenge | None = None
    user_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "message": self.message,
            "userId": self.user_id,
        }
        if self.challenge:
            result["challenge"] = {
                "kind": self.challenge.kind,
                "message": self.challenge.message,
                "retryable": self.challenge.retryable,
                "details": self.challenge.details,
            }
        return result


_ALLOWED_DOMAINS = (".zhihuishu.com", "zhihuishu.com")
_SESSION_VERSION = 1


def session_key(account: str) -> str:
    """生成与平台账号绑定、但不暴露账号原文的会话键。"""
    return hashlib.sha256(f"ZHIHUISHU:{account.strip()}".encode("utf-8")).hexdigest()


def _session_root() -> Path:
    """返回会话密文目录，不依赖系统浏览器或用户浏览器配置。"""
    root = os.environ.get("YATORI_DATA_DIR", "").strip()
    path = Path(root) if root else Path("assets")
    path = path / "zhihuishu_sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _master_key() -> bytes:
    path = _session_root() / "master.key"
    try:
        key = path.read_bytes()
        if len(key) == 32:
            return key
    except OSError:
        pass
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _session_path(uid: str) -> Path:
    safe_uid = "".join(ch for ch in str(uid) if ch.isalnum() or ch in "-_")
    if not safe_uid:
        raise ValueError("UID 不能为空")
    return _session_root() / f"{safe_uid}.json"


def parse_user_cookies(value: Any) -> RequestsCookieJar:
    """解析用户主动提交的 Cookie JSON 或 Cookie 请求头。"""
    if isinstance(value, dict):
        raw = value
    elif isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("Cookie 不能为空")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = {item.split("=", 1)[0].strip(): item.split("=", 1)[1].strip()
                   for item in text.split(";") if "=" in item}
    else:
        raise ValueError("Cookie 格式必须是 JSON 对象、列表或请求头字符串")

    jar = RequestsCookieJar()
    if isinstance(raw, dict):
        items = [{"name": k, "value": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError("Cookie JSON 顶层必须是对象或列表")

    if not items:
        raise ValueError("Cookie 不能为空")
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError("Cookie 条目缺少 name")
        domain = str(item.get("domain", "") or "").lower()
        if domain and not any(domain == d.lstrip(".") or domain.endswith(d)
                              for d in _ALLOWED_DOMAINS):
            # ★ 2026-10-09 修复: 非智慧树域 Cookie(如易盾 c.dun.163.com) 直接跳过,
            # 而非抛异常导致整个会话读取失败(load_session 静默返回 None)
            continue
        jar.set_cookie(create_cookie(
            name=str(item["name"]), value=str(item.get("value", "")),
            domain=domain, path=item.get("path", "/") or "/",
            expires=item.get("expires"), secure=bool(item.get("secure", True)),
            rest=item.get("rest", {}),
        ))
    return jar


def cookie_payload(jar: RequestsCookieJar) -> list[dict[str, Any]]:
    """将 CookieJar 转换为可加密保存的最小结构。"""
    return [{
        "name": c.name, "value": c.value, "domain": c.domain,
        "path": c.path, "expires": c.expires, "secure": c.secure,
        "rest": c.__dict__.get("_rest", {}),
    } for c in jar]


def save_session(uid: str, jar: RequestsCookieJar, token: str = "") -> None:
    """使用 AES-GCM 保存会话密文。"""
    plain = json.dumps({"version": _SESSION_VERSION,
                        "cookies": cookie_payload(jar),
                        "token": token}, ensure_ascii=False).encode()
    nonce = os.urandom(12)
    cipher = AES.new(_master_key(), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plain)
    payload = {"version": _SESSION_VERSION,
               "data": base64.b64encode(nonce + tag + ciphertext).decode("ascii")}
    _session_path(uid).write_text(json.dumps(payload), encoding="utf-8")


def load_session(uid: str) -> tuple[RequestsCookieJar, str] | None:
    """读取会话密文；损坏、版本不兼容或不存在时返回 None。"""
    try:
        payload = json.loads(_session_path(uid).read_text(encoding="utf-8"))
        if payload.get("version") != _SESSION_VERSION:
            return None
        raw = base64.b64decode(payload["data"])
        nonce, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
        cipher = AES.new(_master_key(), AES.MODE_GCM, nonce=nonce)
        data = json.loads(cipher.decrypt_and_verify(ciphertext, tag).decode())
        return parse_user_cookies(data.get("cookies", [])), str(data.get("token", ""))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def delete_session(uid: str) -> None:
    try:
        _session_path(uid).unlink(missing_ok=True)
    except OSError:
        pass


def cas_user_id(jar: RequestsCookieJar) -> str:
    """从用户提交的 CASLOGC 中提取 userId，仅用于账号绑定校验。"""
    try:
        value = jar.get_dict().get("CASLOGC", "")
        return str(json.loads(unquote_plus(value)).get("userId", "")) if value else ""
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
