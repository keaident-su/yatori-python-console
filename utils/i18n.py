# -*- coding: utf-8 -*-
"""[V3.0.11] 后端消息多语言(与前端共用 assets/i18n 语言包)
用法: from utils.i18n import srv_msg
      return Response(code=400, message=srv_msg("该账号已存在"))
查找顺序: 当前语言 server段 -> 当前语言 ui段 -> en-US ui段 -> 中文原文。
语言来源: config.yaml setting.i18n.lang (缺省 zh-CN)。
"""
import json
import os
import time

_CACHE = {}      # lang -> {"ts":t, "data":{...}}
_TTL = 30.0
_CFG = "./config.yaml"
i18n_dir = "./assets/i18n"


def _current_lang() -> str:
    try:
        from dao.config_store import ConfigStore
        st = ConfigStore.instance().get_setting() or {}
        lang = ((st.get("i18n") or {}).get("lang") or "").strip()
        if lang:
            return lang
    except Exception:
        pass
    try:
        import yaml
        if os.path.exists(_CFG):
            with open(_CFG, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            lang = (((d.get("setting") or {}).get("i18n")
                    or {}).get("lang") or "").strip()
            if lang:
                return lang
    except Exception:
        pass
    return "zh-CN"


def _norm(lang: str) -> str:
    """[MC 风格] 语言代码归一化: 小写下划线(zh_CN/zh-CN -> zh_cn)"""
    return str(lang or "").strip().lower().replace("-", "_")


def _load(lang: str) -> dict:
    now = time.time()
    lang = _norm(lang)
    hit = _CACHE.get(lang)
    if hit and now - hit["ts"] < _TTL:
        return hit["data"]
    data = {}
    p = os.path.join(i18n_dir, lang + ".json")
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
    except Exception:
        data = {}
    _CACHE[lang] = {"ts": now, "data": data}
    return data


def _lookup(d: dict, zh: str):
    """兼容 MC 扁平包 与旧 {server,ui} 结构"""
    if not isinstance(d, dict):
        return None
    v = d.get(zh)
    if isinstance(v, str) and v:
        return v
    for sec in ("server", "ui"):
        sub = d.get(sec)
        if isinstance(sub, dict):
            v = sub.get(zh)
            if isinstance(v, str) and v:
                return v
    return None


def srv_msg(zh: str, **fmt) -> str:
    """中文原文 -> 当前语言译文(自动回退; 兼容 MC 扁平包)"""
    text = zh
    try:
        lang = _norm(_current_lang())
        if lang and lang not in ("zh_cn", "zh"):
            v = _lookup(_load(lang), zh)
            if v:
                text = v
            else:
                v = _lookup(_load("en_us"), zh)
                if v:
                    text = v
    except Exception:
        text = zh
    if fmt:
        try:
            text = text.format(**fmt)
        except Exception:
            pass
    return text
