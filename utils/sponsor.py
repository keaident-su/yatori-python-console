# -*- coding: utf-8 -*-
"""赞助支持提示(2026-10-20)

背景: 项目完全免费开源, 持续维护需成本(正版抓包工具/服务器等);
  作者需要一点支持。在【程序开屏LOGO后】与【所有任务全部完成时】展示赞助横幅,
  完成界面额外自动弹出微信赞赏码图片(每进程仅弹一次, 避免多账号重复弹窗)。
"""
import os
import sys

# 赞赏码文件名(放在 assets/ 下)
SPONSOR_QR_NAME = "微信赞赏码.png"
_GOLD = "\033[93m"   # 亮黄
_CYAN = "\033[96m"   # 青
_RST = "\033[0m"
_popup_shown = False   # 进程级节流: 自动弹图每进程仅一次


def _base_dirs():
    """返回可能存放 assets/ 的基础目录(exe目录 > 源码目录)"""
    out = []
    try:
        if getattr(sys, "frozen", False):
            out.append(os.path.dirname(os.path.abspath(sys.executable)))
    except Exception:
        pass
    try:
        out.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except Exception:
        pass
    try:
        out.append(os.getcwd())
    except Exception:
        pass
    return out


def find_qr() -> str:
    """定位赞赏码图片路径; 找不到返回空串"""
    for base in _base_dirs():
        for sub in ("assets", ""):
            p = os.path.join(base, sub, SPONSOR_QR_NAME) if sub else os.path.join(base, SPONSOR_QR_NAME)
            try:
                if os.path.isfile(p):
                    return p
            except Exception:
                continue
    return ""


def print_sponsor_banner(popup_qr: bool = False) -> None:
    """打印赞助横幅
    popup_qr=True: 额外尝试用系统看图工具自动打开赞赏码(完成界面用; 每进程仅一次)
    """
    global _popup_shown
    qr = find_qr()
    line = "=" * 62
    try:
        print()
        print(f"{_GOLD}{line}{_RST}")
        print(f"{_GOLD}  💖 感谢使用 Yatori 开源刷课系统{_RST}")
        print(f"{_GOLD}  项目完全免费，持续维护需要成本（正版抓包工具/服务器等）。{_RST}")
        print(f"{_GOLD}  如果它帮到了您，欢迎微信扫码赞赏，支持作者继续维护：{_RST}")
        if qr:
            print(f"{_CYAN}  微信赞赏码：{qr}{_RST}")
            if popup_qr and not _popup_shown:
                _popup_shown = True
                try:
                    os.startfile(qr)  # Windows 默认看图工具打开
                    print(f"{_CYAN}  （赞赏码已自动打开，扫码即可赞赏）{_RST}")
                except Exception:
                    pass
        else:
            print(f"{_CYAN}  （赞赏码图片：assets/{SPONSOR_QR_NAME}）{_RST}")
        print(f"{_GOLD}{line}{_RST}")
        print()
    except Exception:
        pass
