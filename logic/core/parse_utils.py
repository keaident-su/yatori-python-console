# -*- coding: utf-8 -*-
"""
轻量纯解析函数模块 - 仅依赖标准库(re/json)
放置在轻量模块中的目的：供 cpu_pool 进程池子进程调用时，
Windows spawn 只需导入本模块，避免子进程加载 Crypto/requests/httpx 等重依赖。
所有函数必须是模块顶层纯函数（可 pickle、无副作用）。
"""
import json as _json
import re
from typing import Dict, List

_IFRAME_PATTERN = re.compile(
    r'<iframe\s+([^>]*)>', re.IGNORECASE | re.DOTALL)
_ATTR_PATTERN = re.compile(
    r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
    re.IGNORECASE)


def parse_iframe_data(html_string: str) -> List[Dict]:
    """解析卡片 description HTML 中的 iframe 标签
    对应 Go 的 parseIframeData()
    返回: [{"data": {...}, "other": {"module": "...", ...}, "has_data": True}, ...]
    """
    results = []
    if not html_string:
        return results

    for iframe_match in _IFRAME_PATTERN.finditer(html_string):
        attrs_str = iframe_match.group(1)
        iframe_attrs = {"data": {}, "other": {}, "has_data": False}

        for attr_match in _ATTR_PATTERN.finditer(attrs_str):
            key = attr_match.group(1).lower()
            value = attr_match.group(2) if attr_match.group(
                2) is not None else attr_match.group(3)
            if value is None:
                value = ""

            if key == "data" and value.strip():
                iframe_attrs["has_data"] = True
                # 清理: 替换 &quot; 为 "，移除多余空白
                cleaned = value.replace("&quot;", '"')
                cleaned = re.sub(r'\s+', '', cleaned)
                try:
                    iframe_attrs["data"] = _json.loads(cleaned)
                except Exception:
                    pass
            else:
                iframe_attrs["other"][key] = value

        results.append(iframe_attrs)

    return results
