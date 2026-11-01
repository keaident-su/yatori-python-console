# -*- coding: utf-8 -*-
"""
公告工具 - 对应 Go 项目的 AnnouncementUtils.go
用于拉取和显示远程公告
"""
import httpx


def pull_announcement() -> str:
    """拉取远程公告"""
    url = "https://yatori-dev.github.io/yatori-docs/notice/yatori-go-console-inform.txt"
    try:
        with httpx.Client(timeout=5.0, verify=False) as client:
            resp = client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.13; rv:88.0) "
                              "Gecko/20100101 Firefox/88.0"
            })
            resp.raise_for_status()
            return resp.text
    except Exception:
        return ""


def show_announcement():
    """显示公告"""
    text = pull_announcement()
    if text:
        print(text)
