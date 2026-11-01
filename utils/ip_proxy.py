# -*- coding: utf-8 -*-
"""
IP 代理池工具 - 对应 Go 项目的 IpProxyFileUtils.go
提供 IP 代理文件读取、代理检测、随机获取功能
"""
import random
import hashlib
from typing import List, Tuple, Optional

import httpx

# httpx >= 0.28.0 将 proxies 参数改为 proxy
_HTTPX_USE_PROXY = tuple(int(x)
                         for x in httpx.__version__.split(".")[:2]) >= (0, 28)

# 全局 IP 代理池
IP_PROXY_POOL: List[str] = []

# 是否开启 IP 代理标志
IS_PROXY_FLAG: bool = False

# 健康存活代理池(健康检测后写入, 优先于 IP_PROXY_POOL)
ALIVE_POOL: List[str] = []


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
        proxy_url = str(proxy_ip) if "://" in str(proxy_ip) else f"http://{proxy_ip}"
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


def _norm_proxy(entry: str) -> str:
    """归一化代理条目: 带 scheme(socks5://user:pass@h:p / http://h:p)原样保留, 否则补 http://"""
    e = str(entry or "").strip()
    if not e:
        return ""
    return e if "://" in e else ("http://" + e)


def proxy_for_account(account: str) -> str:
    """一号一出口: 按账号稳定映射到池内同一条(优先取健康存活池 ALIVE_POOL)."""
    pool = ALIVE_POOL if ALIVE_POOL else IP_PROXY_POOL
    if not pool:
        return ""
    try:
        idx = int(hashlib.md5(str(account).encode("utf-8")).hexdigest(), 16) % len(pool)
    except Exception:
        idx = 0
    return _norm_proxy(pool[idx])


def fetch_proxies_from_api(url: str, timeout: int = 12) -> List[str]:
    """从代理提取API(快代理格式: 每行 ip:port)拉取代理列表; 兼容 json{data|result|list}."""
    try:
        with httpx.Client(timeout=timeout, verify=False) as c:
            r = c.get(url, headers={"User-Agent": "Mozilla/5.0"})
        txt = r.text or ""
        try:
            j = r.json()
            for k in ("data", "result", "ips", "list"):
                v = j.get(k) if isinstance(j, dict) else None
                if isinstance(v, list):
                    return [str(x).strip() for x in v if str(x).strip()]
        except Exception:
            pass
        return [ln.strip() for ln in txt.splitlines() if ln.strip() and ":" in ln]
    except Exception:
        return []


def refresh_alive(proxies: Optional[List[str]] = None, timeout: int = 6) -> List[str]:
    """健康检测并更新存活池 ALIVE_POOL, 返回存活列表."""
    global ALIVE_POOL
    pool = proxies if proxies is not None else IP_PROXY_POOL
    alive = []
    for p in pool:
        ok, _, _ = check_proxy_ip(p)
        if ok:
            alive.append(p)
    ALIVE_POOL = alive
    return alive


def verify_egress_ip(proxy: str = "") -> dict:
    """经代理校验出口IP归属地(ipservice.ws.126.net). 返回 {ip, location} 或 {error}."""
    try:
        kw = {}
        if proxy:
            pu = _norm_proxy(proxy)
            kw = {"proxy": pu} if _HTTPX_USE_PROXY else {"proxies": {"all://": pu}}
        with httpx.Client(timeout=12, verify=False, **kw) as c:
            ip = c.get("https://api.ipify.org?format=json").json().get("ip", "")
            loc = c.get("https://ipservice.ws.126.net/locate/api/getLocByIp",
                        params={"ip": ip}).json()
            return {"ip": ip, "location": (loc or {}).get("result", loc)}
    except Exception as e:
        return {"error": str(e)}
