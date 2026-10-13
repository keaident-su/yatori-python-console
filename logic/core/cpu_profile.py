# -*- coding: utf-8 -*-
"""
CPU 型号识别与配置文件加载 (cpus/*.yaml)
================================================================
机制(2026-09-24 与用户确认):
  ① 识别本机 CPU 型号(Windows 注册表 / Linux /proc/cpuinfo / macOS sysctl)
  ② 逐级匹配 cpus/ 目录: 精确(归一化) → 别名(aliases) → 包含
  ③ 未命中 → 返回空配置(由 parallel 公式兜底), 并提示建议添加
  ④ 用户新增 {型号}.yaml 即自动生效, 无需改源码

归一化规则: 去掉 (R)(TM)/CPU/@频率/w 后缀/多余空格, 统一小写与下划线。
"""
import os
import re
import sys
import threading
from typing import Optional, Tuple

_LOCK = threading.Lock()
_LOADED = False
_MODEL = ""            # 本机 CPU 原始识别名
_PROFILE = {}          # 命中的配置(dict)
_SOURCE = ""           # 命中来源(文件名 / "内置公式")
_PROFILE_DIR = ""      # cpus 目录绝对路径


# ==================== CPU 型号识别 ====================

def _read_windows() -> str:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        with key:
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        return str(val or "").strip()
    except Exception:
        return ""


def _read_linux() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _read_macos() -> str:
    try:
        import subprocess
        out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                             capture_output=True, text=True, timeout=3)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def get_cpu_model() -> str:
    """本机 CPU 型号(带缓存)"""
    global _MODEL
    if _MODEL:
        return _MODEL
    m = ""
    if sys.platform == "win32":
        m = _read_windows() or _read_macos() or _read_linux()
    elif sys.platform == "darwin":
        m = _read_macos()
    else:
        m = _read_linux()
    _MODEL = m
    return m


# ==================== 归一化 ====================

_PAT_RM = re.compile(
    r"\((?:R|TM|C)\)|®|™|(?:CPU|Processor|with|w/)\b|@\s*[\d.]+\s*(?:GHz|MHz)?",
    re.IGNORECASE)
# 注意: 不可使用 "Gen Intel.*$" 之类贪心规则(会误吃 "13th Gen Intel(R) Core(TM) i7-..." 主体)
_PAT_TAIL = re.compile(
    r"(?:\s+\d+(?:\.\d+)?\s*(?:GHz|MHz))|Radeon.*$|Graphics.*$|ES\s*$",
    re.IGNORECASE)


def normalize(s: str) -> str:
    """归一化: 便于跨写法比对(去修饰/频率/核显后缀, 统一小写下划线)"""
    s = str(s or "")
    s = _PAT_RM.sub(" ", s)
    s = _PAT_TAIL.sub(" ", s)
    s = s.replace("(R)", " ").replace("(TM)", " ").replace("(C)", " ")
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s)
    return s.strip("_").lower()


# ==================== 配置加载与匹配 ====================

def _profile_dir() -> str:
    """cpus 目录: 优先 exe 同级(打包环境), 其次源码根目录
    (本文件位于 logic/core/ 下, 需上溯 3 层到项目根)"""
    global _PROFILE_DIR
    if _PROFILE_DIR:
        return _PROFILE_DIR
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))   # logic/core/cpu_profile.py -> 根
    _PROFILE_DIR = os.path.join(base, "cpus")
    return _PROFILE_DIR


def _iter_profiles():
    """产出 (文件名, 数据dict)"""
    d = _profile_dir()
    if not os.path.isdir(d):
        return
    try:
        import yaml
    except Exception:
        return
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith((".yaml", ".yml")) or fn.startswith("_"):
            continue
        p = os.path.join(d, fn)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                yield fn, data
        except Exception:
            continue


def _match(model: str) -> Tuple[dict, str]:
    """逐级匹配: 精确 → 别名 → 包含; 返回 (profile, 文件名) 或 ({}, "")"""
    nm_model = normalize(model)
    if not nm_model:
        return {}, ""
    exact, alias, contain = {}, {}, {}
    for fn, data in _iter_profiles():
        fn_nm = normalize(os.path.splitext(fn)[0])
        m_nm = normalize(str(data.get("model", "")))
        if nm_model and nm_model in (fn_nm, m_nm):
            exact = exact or (data, fn)
            continue
        aliases = data.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if any(normalize(str(a)) == nm_model for a in aliases):
            alias = alias or (data, fn)
            continue
        # 包含匹配: 文件名型号是全称的一部分(处理 "w/ Radeon" 等后缀)
        if fn_nm and (fn_nm in nm_model or nm_model in fn_nm) and len(fn_nm) >= 6:
            contain = contain or (data, fn)
    for hit in (exact, alias, contain):
        if hit:
            return hit[0], hit[1]
    return {}, ""


def load(force: bool = False) -> dict:
    """加载本机 CPU 配置(幂等缓存); 未命中返回空 dict(公式兜底)"""
    global _LOADED, _PROFILE, _SOURCE
    with _LOCK:
        if _LOADED and not force:
            return _PROFILE
        try:
            model = get_cpu_model()
            profile, fname = _match(model)
            _PROFILE = profile
            _SOURCE = fname if fname else ""
        except Exception:
            _PROFILE, _SOURCE = {}, ""
        _LOADED = True
    return _PROFILE


def get(key: str) -> Optional[float]:
    """取配置中的某参数; 未配置/未命中返回 None(由调用方走公式)"""
    v = load().get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_int(key: str) -> Optional[int]:
    v = get(key)
    return None if v is None else int(v)


def tuner_override() -> dict:
    """tuner 子配置(可选覆盖)"""
    t = load().get("tuner")
    return t if isinstance(t, dict) else {}


# ==================== 启动提示 ====================

def startup_banner() -> str:
    """一行识别结果(启动日志用)"""
    model = get_cpu_model() or "未知型号"
    load()
    if _SOURCE:
        return f"CPU: {model} → 已加载配置 cpus/{_SOURCE}"
    d = _profile_dir()
    return (f"CPU: {model} → 未找到专属配置(使用内置公式); "
            f"如需最优参数, 可按 cpus/README_CPU配置规范.md 添加 "
            f"cpus/{normalize(model) or 'Your_CPU'}.yaml")
