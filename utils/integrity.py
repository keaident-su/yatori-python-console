# -*- coding: utf-8 -*-
"""启动完整性自校验(方案A 增强)

原理: 打包脚本在 Cython 编译完成后, 对全部自研原生扩展(.pyd/.so)
计算 SHA-256 清单并生成 _integrity_data.py 一并打入 exe;
程序启动时(frozen 环境)重新计算 _MEIPASS 内实际文件摘要并比对,
不一致即说明原生扩展被篡改/替换 —— 立即静默退出。

注意: 本校验提高逆向与篡改门槛, 不构成绝对防护(清单本身随包内置)。
"""
import hashlib
import os
import sys

# 自研包目录(与 build_protected.py PACKAGES 保持一致)
_OWN_DIRS = ("config", "logic", "utils", "dao", "entity",
             "global_state", "web")


def _sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def collect_native_hashes(base_dir: str) -> dict:
    """收集 base_dir 下自研包内全部 .pyd/.so 的 {相对路径(正斜杠): sha256}"""
    out = {}
    for d in _OWN_DIRS:
        root = os.path.join(base_dir, d)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not (fn.endswith(".pyd") or fn.endswith(".so")):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, base_dir).replace(os.sep, "/")
                try:
                    out[rel] = _sha256(full)
                except OSError:
                    out[rel] = ""
    return out


def verify_integrity(manifest: dict) -> bool:
    """frozen 环境下比对实际原生扩展摘要; 通过返回 True

    :param manifest: 构建期生成的 {相对路径: sha256} 清单
    """
    if not isinstance(manifest, dict) or not manifest:
        return True   # 无清单(开发态/旧包)不拦截
    if not getattr(sys, "frozen", False):
        return True   # 源码运行不校验
    base = getattr(sys, "_MEIPASS", None) or \
        os.path.dirname(os.path.abspath(sys.executable))
    actual = collect_native_hashes(base)
    for rel, expect in manifest.items():
        got = actual.get(rel)
        if got is None or (expect and got != expect):
            return False
    return True
