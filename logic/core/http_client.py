# -*- coding: utf-8 -*-
"""
通用 HTTP 客户端 - 对应 Go 项目中各平台共享的 HTTP 请求模式
支持：代理、重试、SSL跳过、Cookie管理、multipart表单、JSON请求
"""
import time
import random
import string
from typing import Optional, Dict, Any, Tuple

import httpx

# httpx >= 0.28.0 将 proxies 参数改为 proxy
_HTTPX_USE_PROXY = tuple(int(x)
                         for x in httpx.__version__.split(".")[:2]) >= (0, 28)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class HttpClient:
    """
    通用 HTTP 客户端
    - 支持 httpx.Client session（自动管理 Cookie）
    - 支持可选代理
    - 支持 SSL 跳过验证
    - 支持 502/504/500 自动重试
    - 支持 multipart/form-data 和 JSON
    """

    def __init__(self, proxy_ip: Optional[str] = None,
                 verify_ssl: bool = False,
                 timeout: float = 30.0):
        """
        初始化 HTTP 客户端
        :param proxy_ip: 代理 IP，格式 "ip:port"
        :param verify_ssl: 是否验证 SSL 证书
        :param timeout: 超时时间（秒）
        """
        self.proxy_ip = proxy_ip
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None
        self._ua: str = DEFAULT_USER_AGENT  # 可自定义的 UA

    def _get_client(self) -> httpx.Client:
        """获取或创建 httpx.Client 实例"""
        if self._client is None or self._client.is_closed:
            kwargs = dict(
                verify=self.verify_ssl,
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            )
            if self.proxy_ip:
                proxy_url = f"http://{self.proxy_ip}"
                # httpx>=0.28 将 proxies 重命名为 proxy
                proxy_key = "proxy" if _HTTPX_USE_PROXY else "proxies"
                kwargs[proxy_key] = proxy_url
            self._client = httpx.Client(**kwargs)
        return self._client

    def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            self._client.close()

    def set_proxy(self, proxy_ip: str):
        """动态设置代理"""
        self.proxy_ip = proxy_ip
        self.close()

    @property
    def cookies(self) -> httpx.Cookies:
        """获取当前 Cookie"""
        return self._get_client().cookies

    def set_cookie(self, name: str, value: str, domain: str = ""):
        """设置 Cookie"""
        self._get_client().cookies.set(name, value, domain=domain)

    def load_cookies(self, cookie_dict: Dict[str, str]):
        """从 dict 批量加载 Cookie"""
        if cookie_dict:
            for name, value in cookie_dict.items():
                self._get_client().cookies.set(name, value)

    def _is_retry_needed(self, text: str) -> bool:
        """检查是否需要重试"""
        return (
            "502 Bad Gateway" in text
            or "504 Gateway Time-out" in text
            or '"status":false,"_code":500' in text
        )

    def request(self, method: str, url: str,
                data: Optional[Dict[str, Any]] = None,
                json_data: Optional[Dict[str, Any]] = None,
                headers: Optional[Dict[str, str]] = None,
                files: Optional[Dict] = None,
                retry: int = 8,
                use_multipart: bool = False) -> Tuple[str, Optional[httpx.Response]]:
        """
        通用请求方法
        :param method: HTTP 方法
        :param url: 请求 URL
        :param data: 表单数据（dict）
        :param json_data: JSON 数据（dict）
        :param headers: 额外请求头
        :param files: 文件上传
        :param retry: 重试次数
        :param use_multipart: 是否使用 multipart/form-data
        :return: (响应文本, 响应对象)
        """
        if retry < 0:
            return "", None

        client = self._get_client()
        req_headers = dict(headers or {})
        last_err = None

        try:
            if json_data is not None:
                resp = client.request(
                    method, url, json=json_data, headers=req_headers
                )
            elif use_multipart and data is not None:
                resp = client.request(
                    method, url, data=data, files=files, headers=req_headers
                )
            elif data is not None:
                resp = client.request(
                    method, url, data=data, headers=req_headers
                )
            else:
                resp = client.request(method, url, headers=req_headers)

            body = resp.text
            if self._is_retry_needed(body):
                time.sleep(0.15)
                return self.request(
                    method, url, data, json_data, headers, files,
                    retry - 1, use_multipart
                )
            return body, resp

        except Exception as e:
            last_err = e
            time.sleep(0.15)
            return self.request(
                method, url, data, json_data, headers, files,
                retry - 1, use_multipart
            )

    def get(self, url: str, headers: Optional[Dict[str, str]] = None,
            retry: int = 8) -> Tuple[str, Optional[httpx.Response]]:
        """GET 请求"""
        return self.request("GET", url, headers=headers, retry=retry)

    def post_form(self, url: str, data: Dict[str, Any],
                  headers: Optional[Dict[str, str]] = None,
                  retry: int = 8,
                  use_multipart: bool = True) -> Tuple[str, Optional[httpx.Response]]:
        """POST 表单请求（默认 multipart/form-data）"""
        return self.request(
            "POST", url, data=data, headers=headers,
            retry=retry, use_multipart=use_multipart
        )

    def post_json(self, url: str, json_data: Dict[str, Any],
                  headers: Optional[Dict[str, str]] = None,
                  retry: int = 8) -> Tuple[str, Optional[httpx.Response]]:
        """POST JSON 请求"""
        return self.request(
            "POST", url, json_data=json_data, headers=headers, retry=retry
        )

    def get_image(self, url: str, retry: int = 8) -> Tuple[Optional[bytes], Optional[httpx.Response]]:
        """GET 图片请求，返回 (图片字节, 响应对象)"""
        if retry < 0:
            return None, None
        client = self._get_client()
        try:
            resp = client.get(url, headers={"Connection": "keep-alive"})
            if resp.status_code == 200:
                return resp.content, resp
            time.sleep(0.15)
            return self.get_image(url, retry - 1)
        except Exception:
            time.sleep(0.15)
            return self.get_image(url, retry - 1)


def generate_random_string(length: int = 10) -> str:
    """生成随机字符串"""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def generate_random_hex(length: int = 10) -> str:
    """生成随机十六进制字符串"""
    chars = "0123456789abcdefABCDEF"
    return "".join(random.choices(chars, k=length))
