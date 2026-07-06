# -*- coding: utf-8 -*-
"""
邮件工具 - 对应 Go 项目的 EmailUtils.go
支持 SMTP 邮件发送 + HTML 模板
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import List

from utils.log import log_print, INFO


def _build_email_html(title: str, content_html: str, as_plain_text: bool = False) -> str:
    """生成邮件 HTML 模板"""
    logo_url = "https://avatars.githubusercontent.com/u/185567923?s=1000&v=4"

    if as_plain_text:
        content_html = escape(content_html).replace("\n", "<br>")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:#f5f7fb;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f5f7fb;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" cellpadding="0" cellspacing="0" width="600"
               style="max-width:600px;background:#ffffff;border-radius:16px;box-shadow:0 6px 24px rgba(18,38,63,0.08);">
          <tr>
            <td align="center" style="padding:28px 24px 8px 24px;">
              <img src="{logo_url}" width="88" height="88" alt="logo"
                   style="display:block;border-radius:50%;width:88px;height:88px;border:2px solid #eef2f7;">
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:0 24px 8px 24px;">
              <div style="font-family:system-ui,sans-serif;font-size:22px;font-weight:700;color:#111827;">
                {escape(title)}
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 0 24px;">
              <div style="height:1px;background:linear-gradient(90deg,#e5e7eb,#f3f4f6,#e5e7eb);"></div>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 24px 8px 24px;">
              <div style="font-family:system-ui,sans-serif;font-size:15px;color:#374151;line-height:1.8;">
                {content_html}
              </div>
            </td>
          </tr>
        </table>
        <table role="presentation" cellpadding="0" cellspacing="0" width="600" style="max-width:600px;">
          <tr><td align="center" style="padding:14px 8px 0 8px;color:#6b7280;
              font-family:system-ui,sans-serif;font-size:12px;line-height:1.6;">
            这是一封系统通知邮件，请勿直接回复。
          </td></tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_mail(host: str, port: int, user_name: str, password: str,
              to_mails: List[str], content: str):
    """
    发送邮件
    :param host: SMTP 服务器地址
    :param port: SMTP 端口
    :param user_name: 发件人邮箱
    :param password: 授权码/密码
    :param to_mails: 收件人列表
    :param content: 邮件正文内容（支持 HTML）
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"Yatori课程助手 <{user_name}>"
        msg["To"] = ", ".join(to_mails)
        msg["Subject"] = "Yatori课程助手通知"

        email_html = _build_email_html("Yatori课程助手", content, False)
        msg.attach(MIMEText(email_html, "html", "utf-8"))

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(user_name, password)
            server.sendmail(user_name, to_mails, msg.as_string())

    except Exception as e:
        log_print(
            INFO, f"邮件发送失败: host={host} port={port} user={user_name} err={e}")
