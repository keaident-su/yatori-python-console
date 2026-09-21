# -*- coding: utf-8 -*-
"""
全局平台与能力探测 - 多系统/多架构适配的单一事实源

覆盖: Windows / macOS(Intel+ARM) / Linux(多架构) / Android(APK) / Docker
用途: 平台判定、处理器架构规范化、关键能力(OCR/浏览器验证码/进程池)状态、启动画像
"""
import os
import platform
import sys


def is_windows() -> bool:
    """Windows"""
    return sys.platform == "win32"


def is_macos() -> bool:
    """macOS(Intel / Apple Silicon 均适用)"""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """Linux(任意处理器架构)"""
    return sys.platform.startswith("linux")


def is_android() -> bool:
    """Android(APK/Chaquopy/Termux)环境判定

    Android 上不存在可供 nodriver 驱动的桌面 Chromium,
    浏览器自动化验证码整体不可用; 仅登录图形验证码(本地 OCR)可尝试。
    """
    if sys.platform in ("android", "linux-android"):
        return True
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    if "com.termux" in os.environ.get("PREFIX", ""):
        return True
    return False


def is_docker() -> bool:
    """Docker 容器环境判定"""
    try:
        if os.path.exists("/.dockerenv"):
            return True
        with open("/proc/1/cgroup", "r", encoding="utf-8",
                  errors="ignore") as f:
            content = f.read()
        return ("docker" in content) or ("containerd" in content)
    except OSError:
        return False


def get_arch() -> str:
    """规范化处理器架构名(x86_64/arm64/armv7/riscv64/loongarch64/ppc64le/s390x 等)"""
    m = (platform.machine() or "").lower()
    alias = {
        "amd64": "x86_64",
        "aarch64": "arm64",
        "armv7l": "armv7",
        "armv8l": "armv7",
        "i386": "x86",
        "i686": "x86",
    }
    return alias.get(m, m or "unknown")


def supports_process_pool() -> bool:
    """多进程计算池是否可用

    Android(multiprocessing 不可用)与 PyInstaller 冻结环境(子进程代价高)不支持;
    亦可用环境变量 YATORI_DISABLE_CPU_POOL=1 强制禁用。
    """
    if is_android():
        return False
    if os.environ.get("YATORI_DISABLE_CPU_POOL", "") == "1":
        return False
    return not getattr(sys, "frozen", False)


def _module_installed(name: str) -> bool:
    """轻量检查模块是否已安装(不实际导入, 不触发重依赖加载)"""
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def platform_summary() -> str:
    """单行平台画像(启动打印用): 系统/架构/(容器) + 关键能力安装状态"""
    if is_android():
        sys_name = "Android"
    elif is_windows():
        sys_name = "Windows"
    elif is_macos():
        sys_name = "macOS"
    elif is_linux():
        sys_name = "Linux"
    else:
        sys_name = sys.platform
    parts = [sys_name, get_arch()]
    if is_docker():
        parts.append("Docker")
    caps = ["OCR:" + ("可用" if (_module_installed("rapidocr_onnxruntime")
                                  or _module_installed("ddddocr"))
                       else "未安装(自动降级)")]
    if is_android():
        caps.append("浏览器验证码:不可用(Android, 自动降级)")
    else:
        caps.append("浏览器验证码:" + ("可用" if _module_installed("nodriver")
                                        else "未安装(自动降级)"))
    caps.append("进程池:" + ("可用" if supports_process_pool() else "已禁用(自动内联)"))
    parts.append(" / ".join(caps))
    return " ".join(parts)
