# -*- coding: utf-8 -*-
"""Yatori Linux 打包(PyInstaller onedir) — 在Ubuntu venv内执行
产物: dist/yatori-linux/ (目录版, 含可执行文件+依赖)
"""
import os
import sys

import PyInstaller.__main__

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

# hiddenimports: 动态导入链(uvicorn协议/webview后端/nodriver等)
HIDDEN = [
    "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.loops.asyncio", "uvicorn.protocols", "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "webview", "webview.platforms.gtk",
    "nodriver", "pyaes", "mini_racer", "tls_client",
    "jmespath", "multipart", "aiosqlite",
    "sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.sqlite.aiosqlite",
    "rapidocr_onnxruntime", "onnxruntime", "cv2",
    "playwright", "playwright.sync_api",
    "websockets", "mss",
    # [2026-10-24] QtWebEngine渲染后端(VM/WebKit空白修复): 触发PyInstaller钩子
    "qtpy", "PyQt5", "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore",
    "PyQt5.QtCore", "PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.sip",
    "logic.xuexitong.api", "logic.zhihuishu.yidun.yidun_solver",
]

# datas: 配置/静态UI/图标/模型
DATAS = []
_d = os.path.join
for src, dst in (
    (_d("config", "logo.txt"), "config"),
    (_d("assets", "i18n"), "assets/i18n"),  # V3.0.11 多语言语言包
    (_d("web", "static"), "web/static"),
    (_d("assets", "app_icon.png"), "assets"),
    (_d("assets", "app_icon.ico"), "assets"),
    (_d("logic", "zhihuishu", "yidun"), "logic/zhihuishu/yidun"),
    # [V3.2.2 hotfix] 安全微伴登录验证码 CNN 模型(captcha.py 冻结环境从 _MEIPASS 根加载)
    (_d("logic", "weban", "captcha_model.onnx"), "."),
):
    if os.path.exists(src):
        DATAS.append((src, dst))

# [V3.2.2 hotfix] cv2 打包加固: 确保 cv2 核心扩展(.so/.pyd)与附属库完整
# (cv2 5.x 下旧 hook 可能只收 data 不收扩展 -> DNN 不可用)
try:
    from PyInstaller.utils.hooks import (
        collect_data_files as _cdf, collect_all as _ca)
    _cv2d, _cv2b, _cv2h = _ca("cv2")
    if _cv2d:
        DATAS += _cv2d
    for _item in _cv2b:
        DATAS.append(_item)
    HIDDEN += [h for h in _cv2h if h not in HIDDEN]
    # 兑底: 显式加入 cv2 扩展文件
    try:
        import cv2 as _cv2mod
        _cdir = os.path.dirname(_cv2mod.__file__)
        _n = 0
        for _f in os.listdir(_cdir):
            _fp = os.path.join(_cdir, _f)
            if not os.path.isfile(_fp):
                continue
            _low = _f.lower()
            if (".so" in _low) or _low.endswith(".pyd"):
                DATAS.append((_fp, "cv2"))
                _n += 1
        print(f"[datas] cv2 扩展 +{_n}")
    except Exception as _e2:
        print("[cv2 补充警告]", str(_e2)[:80])
except Exception as _e:
    print("[cv2 datas]", str(_e)[:100])

# playwright浏览器(内置, Linux首次也可 playwright install)
try:
    from PyInstaller.utils.hooks import collect_data_files
    pw = collect_data_files("playwright")
    if pw:
        DATAS += pw
        print(f"[datas] playwright +{len(pw)}")
except Exception as e:
    print("[playwright datas]", str(e)[:80])

args = [
    "main.py",
    "--name", "yatori-python-console-linux",
    "--onedir",
    "--noconfirm",
    "--clean",
    "--console",
    "--collect-all", "PyQt5",
]
for h in HIDDEN:
    args += ["--hidden-import", h]
for s, dst in DATAS:
    args += ["--add-data", f"{s}:{dst}"]

print("[PyInstaller 启动]", len(args), "args")
PyInstaller.__main__.run(args)
print("[PyInstaller 完成] dist/yatori-python-console-linux/")
