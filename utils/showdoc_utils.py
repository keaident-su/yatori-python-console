# -*- coding: utf-8 -*-
"""
ShowDoc推送工具 - 在原有邮件通知基础上新增的推送方案(微信通知)

原理: 在 push.showdoc.com.cn 登录后会生成专属推送地址,
向该地址 POST/GET title、content 两个参数即可推送到微信。
成功返回 {"error_code":0,"error_message":"ok"}。

与邮件通知相互独立: 由 setting.showdocInform.sw 单独控制开关,
两者可以同时开启、同时关闭。
"""
import httpx

from utils.log import log_print, INFO


def send_showdoc(url: str, title: str, content: str) -> bool:
    """向 ShowDoc 推送服务发送一条消息

    :param url: ShowDoc 专属推送地址(含token, 从 push.showdoc.com.cn 获取)
    :param title: 消息标题
    :param content: 消息内容(支持 文本/Markdown/HTML)
    :return: 是否推送成功
    """
    if not url:
        return False
    url = url.strip()
    if not url:
        return False
    try:
        with httpx.Client(timeout=10.0, verify=False,
                          follow_redirects=True) as client:
            resp = client.post(url, data={"title": title, "content": content})
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                # 个别情况下返回非JSON, 只要HTTP成功也视为已送达
                return True
            error_code = data.get("error_code", -1)
            if error_code == 0:
                return True
            log_print(INFO, f"ShowDoc推送失败: code={error_code} "
                      f"msg={data.get('error_message', '')}")
            return False
    except Exception as e:
        log_print(INFO, f"ShowDoc推送异常: url={url} err={e}")
        return False
