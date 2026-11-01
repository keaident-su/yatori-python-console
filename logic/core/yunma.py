# -*- coding: utf-8 -*-
"""[V3.2.4 mogo对齐] 云码打码平台兜底

参考 mogo 的打码设置(CONFIG/dmData.txt):
  - 云端: http://api.jfbym.com/api/YmServer/customApi  (优先使用)
  - 本地: http://127.0.0.1:1234/dmApi?aKey=xxx###类型码表

本模块只实现"云端通用接口"(jfbym customApi 协议), 供本地 OCR 失败时升级兜底:
  POST {url}  body JSON: {"token": ..., "type": "10310", "image": "<base64>"}
  响应 {"code":10000, "data":{"data":"识别结果", ...}}
type 常用: 10310=通用数英混合  50100=通用数英(旧)  10110=纯数字  具体以平台文档为准。
"""
from __future__ import annotations

import base64
import json
from typing import Optional

_DEFAULT_URL = "http://api.jfbym.com/api/YmServer/customApi"


def recognize(image_bytes: bytes, token: str, url: str = "",
              type_: str = "10310", timeout: float = 20.0) -> str:
    """调用云码平台识别验证码图片, 返回文本(失败返回空串, 不抛异常)"""
    if not image_bytes or not token:
        return ""
    try:
        import httpx
    except Exception:
        return ""
    target = (url or "").strip() or _DEFAULT_URL
    payload = {
        "token": str(token),
        "type": str(type_ or "10310"),
        "image": base64.b64encode(image_bytes).decode("ascii"),
    }
    try:
        resp = httpx.post(target, json=payload, timeout=timeout, verify=False)
        data = resp.json()
    except Exception:
        return ""
    try:
        code = data.get("code")
        if code != 10000:
            return ""
        d = data.get("data") or {}
        if isinstance(d, dict):
            return str(d.get("data") or "").strip()
        return str(d or "").strip()
    except Exception:
        return ""


def recognize_with_config(image_bytes: bytes, setting=None) -> str:
    """按全局配置(basic_setting: yunma_sw/yunma_url/yunma_token/yunma_type)识别

    :param setting: Setting 对象(可空; 空则读取当前加载的全局配置)
    """
    try:
        if setting is None:
            from config.config import load_config  # 尽量复用已加载配置
            setting = getattr(load_config, "_current", None)
    except Exception:
        setting = None
    try:
        bs = getattr(setting, "basic_setting",
                     None) if setting is not None else None
        if bs is None:
            return ""
        if int(getattr(bs, "yunma_sw", 0) or 0) != 1:
            return ""
        return recognize(image_bytes,
                         token=str(getattr(bs, "yunma_token", "") or ""),
                         url=str(getattr(bs, "yunma_url", "") or ""),
                         type_=str(getattr(bs, "yunma_type", "") or "10310"))
    except Exception:
        return ""
