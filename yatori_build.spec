# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 —— yatori-python刷课系统
- 单文件 (onefile) 控制台程序
- config.yaml / assets(日志、人脸) 运行时放在 exe 同目录，首次运行自动生成
- 内置只读资源: config/logo.txt、tls_client 原生 dll
打包命令: pyinstaller yatori_build.spec --noconfirm
"""
import os
import glob
import tls_client

block_cipher = None

# ============ 内置资源 datas ============
datas = [
    # logo.txt -> 运行时位于 sys._MEIPASS/config/logo.txt (与 config.config.read_logo 对应)
    (os.path.join('config', 'logo.txt'), 'config'),
]

# tls_client 通过 os.path.dirname(__file__)/dependencies/tls-client-64.dll 加载原生库，
# 冻结环境下必须把对应平台的动态库放到 tls_client/dependencies/ 目录
_tls_dep_dir = os.path.join(os.path.dirname(tls_client.__file__), 'dependencies')
for _f in glob.glob(os.path.join(_tls_dep_dir, '*')):
    if _f.lower().endswith(('.dll', '.so', '.dylib')):
        datas.append((_f, 'tls_client/dependencies'))

# ============ 隐藏导入 ============
hiddenimports = [
    # uvicorn 运行时按需动态导入的模块
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    # 加密 / 解析相关
    'Crypto.Cipher.AES',
    'Crypto.Cipher.DES',
    'Crypto.Padding',
    'Crypto.Util.Padding',
    'bs4',
    'jmespath',
    'tls_client',
    'aiosqlite',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.sql.default_comparator',
    # 各平台逻辑（均为函数内 import，显式声明以防静态分析遗漏）
    'logic.xuexitong.part',
    'logic.yinghua.part',
    'logic.enaea.part',
    'logic.cqie.part',
    'logic.ketangx.part',
    'logic.icve.part',
    'logic.qingshuxuetang.part',
    'logic.welearn.part',
    'logic.haiqikeji.part',
    'logic.core.cpu_topology',
    # 多答题源引擎(函数内 import, 防静态分析遗漏)
    'logic.core.answer_engine',
    'logic.core.tiku_client',
    'web.server',
    'web.router',
]

# ============ 分析入口 ============
a = Analysis(
    ['main.py'],
    pathex=[os.path.abspath('.')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PyQt5', 'PySide2', 'notebook'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='yatori-python刷课系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
