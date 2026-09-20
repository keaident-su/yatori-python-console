# -*- coding: utf-8 -*-
"""
打包流水线 —— yatori-python刷课系统 V1.1.0

流程:
  1. 复制源码到隔离的 build_stage 目录(不动原始源码树)
  2. 用 Cython 将全部模块(config/logic/utils/dao/entity/global_state/web)
     编译为原生扩展
  3. 清理已编译模块的 .py/.c 中间文件
  4. 在 stage 内逐个 import 全量校验(确保扩展可正常加载)
  5. 用 PyInstaller 打包单文件(内置 logo / tls 原生库 / OCR 模型)
  6. 产物输出到 dist/yatori-python刷课系统V1.1.0.exe

用法: python build_protected.py
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "build_stage"
APP_NAME = "yatori-python刷课系统V1.1.0"
PACKAGES = ["config", "logic", "utils", "dao", "entity", "global_state", "web"]
ENTRY = "main.py"

# __init__.py 是否保持源码(打包兼容回退开关)。False=一并编译
KEEP_INIT_SOURCE = os.environ.get("YATORI_KEEP_INIT_SOURCE", "0") == "1"


def log(msg: str):
    print(f"[protect-build] {msg}", flush=True)


def run(cmd, cwd: Path) -> int:
    log("run: " + " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, cwd=str(cwd))
    return proc.returncode


# ---------------- 1. 准备 stage ----------------

def clean_stage():
    if STAGE.exists():
        shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True, exist_ok=True)


def copy_sources() -> list:
    """复制入口与自研包到 stage, 返回待编译的 .py 相对路径列表"""
    shutil.copy2(ROOT / ENTRY, STAGE / ENTRY)
    modules = []
    for pkg in PACKAGES:
        src_pkg = ROOT / pkg
        for dirpath, dirnames, filenames in os.walk(src_pkg):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", "build")]
            for fn in filenames:
                src = Path(dirpath) / fn
                rel = src.relative_to(ROOT)
                dst = STAGE / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                # 只复制 .py 与必要数据文件(如 config/logo.txt), 跳过编译产物
                if fn.endswith((".py", ".txt", ".yaml", ".yml", ".json")):
                    shutil.copy2(src, dst)
                if fn.endswith(".py"):
                    if KEEP_INIT_SOURCE and fn == "__init__.py":
                        continue
                    modules.append(rel.as_posix())
    log(f"copied {len(modules)} modules to stage")
    return modules


# ---------------- 2. Cython 编译 ----------------

def write_setup(modules: list):
    (STAGE / "setup_cython.py").write_text(
        _setup_code(modules), encoding="utf-8")


def _setup_code(modules: list) -> str:
    # 注意: setup() 必须放在 __main__ 保护内。
    # cythonize(nthreads>1) 内部用进程池, Windows spawn 子进程会重新执行本脚本,
    # 若无 __main__ 保护会直接报 "start a new process before bootstrap"。
    return '''# -*- coding: utf-8 -*-
"""自动生成: Cython 编译配置"""
import os
from setuptools import setup
from Cython.Build import cythonize

MODULES = %r


def main():
    setup(
        name="yatori-protected",
        version="1.1.0",
        ext_modules=cythonize(
            MODULES,
            language_level=3,
            nthreads=max(1, (os.cpu_count() or 4)),
            quiet=True,
            annotate=False,
            compiler_directives={
                "language_level": 3,
                "binding": True,            # 保留函数签名(FastAPI 依赖注入/反射需要)
                "embedsignature": False,    # 不嵌入源码签名
                "emit_code_comments": False,
                "always_allow_keywords": True,
            },
        ),
    )


if __name__ == "__main__":
    main()
''' % (modules,)


def module_has_pyd(rel_py: str) -> bool:
    """判断某 .py 是否已成功产出原生扩展(.pyd/.so)"""
    pyd_stem = (STAGE / rel_py).with_suffix("")
    parent = pyd_stem.parent
    if not parent.exists():
        return False
    return any(f.name.startswith(pyd_stem.name + ".")
               and f.suffix in (".pyd", ".so") for f in parent.iterdir())


def build_ext(modules: list) -> list:
    """编译全部模块; 整体失败则逐模块补齐, 返回成功编译的模块列表"""
    parallel = str(max(1, min(4, (os.cpu_count() or 4))))
    run([sys.executable, "setup_cython.py", "build_ext",
         "--inplace", "--parallel", parallel], STAGE)
    compiled = [m for m in modules if module_has_pyd(m)]
    failed = [m for m in modules if m not in compiled]
    if failed:
        log(f"bulk build left {len(failed)} modules, retry one by one")
        one_setup = STAGE / "setup_cython_one.py"
        for m in failed:
            one_setup.write_text(_setup_code([m]), encoding="utf-8")
            run([sys.executable, one_setup.name, "build_ext",
                 "--inplace", "--parallel", "2"], STAGE)
            if module_has_pyd(m):
                compiled.append(m)
            else:
                log(f"  compile failed (kept as source): {m}")
        one_setup.unlink(missing_ok=True)
    log(f"compiled {len(compiled)}/{len(modules)} modules")
    return compiled


def prune_sources(compiled: list):
    """清理已编译模块的 .py/.c 中间文件"""
    removed = 0
    for rel in compiled:
        py = STAGE / rel
        if py.exists():
            py.unlink()
            removed += 1
        c = py.with_suffix(".c")
        if c.exists():
            c.unlink()
    # 兼容 KEEP_INIT_SOURCE: __init__ 被编译时其 .py 也需删除, 由 compiled 列表覆盖
    shutil.rmtree(STAGE / "build", ignore_errors=True)
    for c in STAGE.rglob("*.c"):
        c.unlink()
    log(f"pruned {removed} source files (no first-party .py left except entry)")


# ---------------- 3. 导入校验 ----------------

def dotted(rel_py: str) -> str:
    name = rel_py[:-3].replace("/", ".")
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    return name


def verify_imports(modules: list) -> bool:
    names = sorted({dotted(m) for m in modules})
    code = (
        "import sys, importlib, traceback\n"
        "sys.path.insert(0, '.')\n"
        "names = %r\n"
        "bad = []\n"
        "for n in names:\n"
        "    try:\n"
        "        importlib.import_module(n)\n"
        "    except Exception as e:\n"
        "        bad.append((n, repr(e)))\n"
        "print('IMPORT-FAILED:', len(bad))\n"
        "for n, e in bad:\n"
        "    print('  -', n, '->', e)\n"
        "sys.exit(1 if bad else 0)\n"
    ) % (names,)
    log("verifying imports in stage ...")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(STAGE),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    tail = (proc.stdout or "").strip().splitlines()
    for line in tail[:12]:
        log(line)
    if proc.returncode != 0:
        log("IMPORT VERIFY FAILED")
        return False
    log(f"import verify OK ({len(names)} modules)")
    return True


# ---------------- 4. 生成 spec 并打包 ----------------

SPEC = STAGE / "yatori_build_protected.spec"

SPEC_TEMPLATE = '''# -*- mode: python ; coding: utf-8 -*-
"""打包配置(由 build_protected.py 自动生成使用)"""
import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

sys.path.insert(0, os.path.abspath("."))

APP_NAME = %r

# ---- 内置数据 ----
datas = [(os.path.join("config", "logo.txt"), "config")]

# tls_client 原生库(运行时按 dirname(__file__)/dependencies 加载)
# 必须按平台过滤: Win=.dll / Linux=.so / macOS=.dylib
# (不能全收: macOS 上 PyInstaller 会把 Linux 的 ELF .so 当 Mach-O 解析而报错)
import tls_client  # noqa: E402
_tls_dep = os.path.join(os.path.dirname(tls_client.__file__), "dependencies")
if sys.platform == "win32":
    _tls_ext = (".dll",)
elif sys.platform == "darwin":
    _tls_ext = (".dylib",)
else:
    _tls_ext = (".so",)
for _f in glob.glob(os.path.join(_tls_dep, "*")):
    if _f.lower().endswith(_tls_ext):
        datas.append((_f, "tls_client/dependencies"))

# 本地 OCR 模型与配置(rapidocr_onnxruntime wheel 内置)
datas += collect_data_files("rapidocr_onnxruntime")

# ---- 隐藏导入 ----
# 模块已全部编译为原生扩展, PyInstaller 无法静态分析其 import,
# 因此第三方依赖必须显式收集; 项目模块由文件扫描得出。
THIRD_PARTY = [
    "fastapi", "starlette", "uvicorn", "pydantic", "pydantic_core", "anyio",
    "httpx", "httpcore", "h11", "h2", "certifi", "idna", "sniffio",
    "yaml", "sqlalchemy", "aiosqlite",
    "Crypto", "bs4", "soupsieve",
    "PIL", "requests", "urllib3", "charset_normalizer",
    "tls_client", "cffi",
    "rapidocr_onnxruntime", "onnxruntime", "numpy", "cv2",
    "shapely", "pyclipper", "six",
    "jmespath", "multipart",
]
hiddenimports = []
for _p in THIRD_PARTY:
    try:
        if _p == "tls_client":
            # 排除 dependencies 子包: 该目录包含各平台原生库(含 Linux ELF .so),
            # macOS 上会被当作扩展模块收集并触发 Mach-O 解析错误而构建失败;
            # tls_client 运行时用 ctypes 直接加载库文件(已由上方 datas 按平台打入),
            # 不依赖该子包被 import。
            hiddenimports += collect_submodules(
                _p, on_error="ignore",
                filter=lambda name: name != "tls_client.dependencies")
        else:
            hiddenimports += collect_submodules(_p, on_error="ignore")
    except Exception:
        pass

# 扫描 stage 内自研原生扩展(.pyd/.so) -> 模块名(以 os.sep 拼接, 避免转义问题)
for _root, _dirs, _files in os.walk("."):
    _dirs[:] = [d for d in _dirs if d not in ("build", "dist", "pyi_work", "__pycache__")]
    for _f in _files:
        if not (_f.endswith(".pyd") or _f.endswith(".so")):
            continue
        _stem = _f.split(".")[0]          # 如 part.cp313-win_amd64.pyd / part.cpython-313-x86_64-linux-gnu.so -> part
        if _stem == "__init__":
            _mod = os.path.relpath(_root, ".").replace(os.sep, "/")
        else:
            _mod = os.path.relpath(os.path.join(_root, _stem), ".").replace(os.sep, "/")
        _mod = _mod.replace("/", ".")
        if _mod and _mod != "." and _mod not in hiddenimports:
            hiddenimports.append(_mod)

# uvicorn 运行时动态导入
hiddenimports += [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.loops.asyncio", "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "email.mime.text", "email.mime.multipart", "sqlite3",
]

a = Analysis(
    ["main.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2", "notebook",
              "pandas", "scipy", "torch", "tls_client.dependencies"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
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
'''.replace("%r", repr(APP_NAME), 1)


def write_spec():
    SPEC.write_text(SPEC_TEMPLATE, encoding="utf-8")
    log(f"spec written: {SPEC.name}")


def run_pyinstaller() -> bool:
    rc = run([sys.executable, "-m", "PyInstaller",
              SPEC.name, "--noconfirm", "--clean",
              "--distpath", str(STAGE / "dist"),
              "--workpath", str(STAGE / "pyi_work")], STAGE)
    return rc == 0


def publish() -> Path:
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    src = STAGE / "dist" / f"{APP_NAME}{exe_suffix}"
    if not src.exists():
        raise RuntimeError(f"binary not found: {src}")
    out_dir = ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / src.name
    shutil.copy2(src, dst)
    if sys.platform != "win32":
        os.chmod(dst, 0o755)
    return dst


def main():
    log(f"APP_NAME = {APP_NAME}")
    clean_stage()
    modules = copy_sources()
    write_setup(modules)
    compiled = build_ext(modules)
    if not compiled:
        log("FATAL: nothing compiled")
        return 1
    kept = [m for m in modules if m not in compiled]
    if kept:
        log(f"NOT compiled (kept as source): {len(kept)} -> {kept[:10]}")
    prune_sources(compiled)
    if not verify_imports([m for m in modules]):
        return 1
    write_spec()
    if not run_pyinstaller():
        log("PyInstaller FAILED")
        return 1
    exe = publish()
    size_mb = exe.stat().st_size / 1048576
    log(f"OK -> {exe} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
