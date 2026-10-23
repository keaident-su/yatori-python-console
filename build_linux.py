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
    "PyQt5", "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore",
    "PyQt5.QtCore", "PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.sip",
    "logic.xuexitong.api", "logic.zhihuishu.yidun.yidun_solver",
]

# datas: 配置/静态UI/图标/模型
DATAS = []
_d = os.path.join
for src, dst in (
    (_d("config", "logo.txt"), "config"),
    (_d("web", "static"), "web/static"),
    (_d("assets", "app_icon.png"), "assets"),
    (_d("assets", "app_icon.ico"), "assets"),
    (_d("logic", "zhihuishu", "yidun"), "logic/zhihuishu/yidun"),
):
    if os.path.exists(src):
        DATAS.append((src, dst))

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
