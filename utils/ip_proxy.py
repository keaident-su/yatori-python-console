# -*- coding: utf-8 -*-
"""
IP 代理池工具 - 对应 Go 项目的 IpProxyFileUtils.go
提供 IP 代理文件读取、代理检测、随机获取功能
"""
import random
from typing import List, Tuple, Optional

import httpx

# httpx >= 0.28.0 将 proxies 参数改为 proxy
_HTTPX_USE_PROXY = tuple(int(x)
                         for x in httpx.__version__.split(".")[:2]) >= (0, 28)

# 全局 IP 代理池
IP_PROXY_POOL: List[str] = []

# 是否开启 IP 代理标志
IS_PROXY_FLAG: bool = False


def ip_files_reader(path: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    读取 IP 代理池文件（每行一个 IP:端口）
    :return: (IP列表, 错误信息)
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            results = [line.strip() for line in f if line.strip()]
        return results, None
    except Exception as e:
        return None, str(e)


def check_proxy_ip(proxy_ip: str) -> Tuple[bool, str, Optional[str]]:
    """
    检测代理 IP 是否可用
    :param proxy_ip: 代理地址（如 127.0.0.1:8080）
    :return: (是否通过, 状态文本, 错误信息)
    """
    try:
        proxy_url = f"http://{proxy_ip}"
        proxy_kw = {"proxy" if _HTTPX_USE_PROXY else "proxies": proxy_url}
        with httpx.Client(timeout=10.0, **proxy_kw) as client:
            resp = client.get(
                "https://httpbin.org/ip",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                       "AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36"}
            )
            return True, str(resp.status_code), None
    except Exception as e:
        return False, "", str(e)


def rand_proxy_str() -> str:
    """随机获取一个代理 IP"""
    if not IP_PROXY_POOL:
        return ""
    return random.choice(IP_PROXY_POOL)
