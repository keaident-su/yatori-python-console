# -*- coding: utf-8 -*-
"""
外置题库客户端 - 对应 Go 项目的 que-core/external 包
支持通过 HTTP API 对接外置题库
"""
import json
from typing import List, Optional, Dict, Any

import httpx

from utils.log import log_print, INFO, BoldRed, Default

# httpx >= 0.28.0 将 proxies 参数改为 proxy
_HTTPX_USE_PROXY = tuple(int(x)
                         for x in httpx.__version__.split(".")[:2]) >= (0, 28)


def _proxy_kwargs(proxy_ip):
    """构建代理参数 dict"""
    if not proxy_ip:
        return {}
    url = f"http://{proxy_ip}"
    return {"proxy" if _HTTPX_USE_PROXY else "proxies": url}


class ExternalQueClient:
    """外置题库客户端"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def check(self, retry: int = 3, proxy_ip: Optional[str] = None) -> Optional[Exception]:
        """检查外置题库可用性"""
        if retry < 0:
            return Exception("外置题库检查重试次数耗尽")
        try:
            resp = httpx.get(
                f"{self.base_url}/check",
                timeout=10,
                **_proxy_kwargs(proxy_ip),
            )
            if resp.status_code == 200:
                return None
            return Exception(f"外置题库检查失败，状态码：{resp.status_code}")
        except Exception as e:
            import time
            time.sleep(0.5)
            return self.check(retry - 1, proxy_ip)

    def search(self, question: str, options: Optional[List[str]] = None,
               proxy_ip: Optional[str] = None) -> str:
        """
        查询题目答案
        :param question: 题目内容
        :param options: 选项列表
        :param proxy_ip: 代理 IP
        :return: 答案字符串
        """
        try:
            payload = {"question": question}
            if options:
                payload["options"] = options

            resp = httpx.post(
                f"{self.base_url}/search",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
                **_proxy_kwargs(proxy_ip),
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("answer", data.get("data", ""))
            return ""
        except Exception as e:
            log_print(INFO, BoldRed, f"外置题库请求失败：{e}")
            return ""


def check_api_que_request(base_url: str, retry: int = 3,
                          proxy_ip: Optional[str] = None) -> Optional[Exception]:
    """检查外置题库可用性（快捷函数）"""
    client = ExternalQueClient(base_url)
    return client.check(retry, proxy_ip)


def search_api_que(base_url: str, question: str,
                   options: Optional[List[str]] = None,
                   proxy_ip: Optional[str] = None) -> str:
    """外置题库搜索答案（快捷函数）"""
    client = ExternalQueClient(base_url)
    return client.search(question, options, proxy_ip)
