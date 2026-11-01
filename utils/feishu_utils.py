# -*- coding: utf-8 -*-
"""[V3.2.2] 飞书群机器人通知

用法:
    from utils.feishu_utils import send_feishu
    send_feishu(webhook, "标题", "正文", secret="")

特性:
- 纯文本消息(msg_type=text), 自动去除 HTML 标签并转义换行
- 支持"签名校验"机器人(secret 非空时按 timestamp+hmac-sha256 生成 sign)
- 长度保护(飞书单条 text 上限约 20KB, 超出截断)
- 限流保护: 同 webhook 最小发送间隔(默认 1.2 秒), 防止频繁触发飞书 100次/分钟限制
- 错误结果打印到标准日志(不抛出), 绝不影响主流程
"""
import base64
import hashlib
import hmac
import json
import re
import threading
import time
from typing import Optional

import requests

_MIN_GAP = 1.2                      # 同 webhook 最小间隔(秒)
_last_sent = {}                     # webhook -> 上次发送时间戳
_gap_lock = threading.Lock()
_MAX_LEN = 8000                     # 正文截断长度(字符)


def _plain_text(s: str) -> str:
    """HTML 片段 -> 飞书纯文本(去标签 + <br> 转换行)"""
    t = str(s or "")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</p\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&nbsp;", " ").replace("&lt;", "<")
         .replace("&gt;", ">").replace("&amp;", "&"))
    return t.strip()


def _sign(secret: str, timestamp: int) -> str:
    """飞书签名: base64(hmac_sha256(key=timestamp+'\\n'+secret, msg=''))"""
    key = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(key, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_feishu(webhook: str, title: str, content: str,
                secret: str = "") -> bool:
    """发送飞书群消息(纯文本)。返回 True=成功"""
    url = (webhook or "").strip()
    if not url or "open.feishu.cn" not in url and "open.larksuite.com" not in url:
        return False
    # 限流(同 webhook 最小间隔)
    with _gap_lock:
        last = _last_sent.get(url, 0)
        wait = _MIN_GAP - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        _last_sent[url] = time.time()
    body_text = _plain_text(f"{title}\n{content}")[:_MAX_LEN]
    payload = {"msg_type": "text", "content": {"text": body_text}}
    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = _sign(secret, ts)
    try:
        r = requests.post(url, json=payload, timeout=12,
                          headers={"Content-Type": "application/json"})
        try:
            d = r.json() if r.text.strip().startswith("{") else {}
        except Exception:
            d = {}
        code = d.get("code", d.get("StatusCode", -1))
        if code == 0:
            return True
        _log_warn(
            f"飞书通知失败: code={code} msg={str(d.get('msg') or d.get('StatusMessage') or '')[:120]}")
        return False
    except Exception as e:
        _log_warn(f"飞书通知异常: {type(e).__name__}: {str(e)[:120]}")
        return False


def _log_warn(msg: str):
    try:
        from utils.log import log_print, INFO, Yellow
        log_print(INFO, Yellow, msg)
    except Exception:
        pass


def self_test(webhook: str, secret: str = "") -> bool:
    return send_feishu(webhook, "Yatori 通知自检",
                       f"这是一条测试消息 ({time.strftime('%Y-%m-%d %H:%M:%S')})",
                       secret=secret)
