# -*- coding: utf-8 -*-
"""
GPU 自动检测与加速调度
======================
全自动流程: 探测(NVML/nvidia-smi/WMI) → 评分 → 选执行后端 → 供各模块查询; 任何失败静默降级 CPU。

用法:
    from logic.core.gpu_accel import GPU_INFO, pick_ort_providers, decode_workers_hint
    GPU_INFO               # 探测结果(dict, 含 has_gpu/vendor/name/vram_mb/score)
    pick_ort_providers()   # 本机可用的 GPU 执行后端(平台自适应; 空=仅 CPU)
    decode_workers_hint()  # 依据 GPU/CPU 返回建议解码线程数

特性:
- 惰性 + 缓存: 进程内只探测一次, 探测耗时 <1.5s, 不阻塞启动(超时保护)
- 平台自适应: Windows→DirectML(全厂商) / macOS→CoreML / Linux→CUDA/OpenVINO
- 后端可用性取交集: 只有硬件有 GPU 且所选后端真实存在于 onnxruntime 才返回
  (避免"探测到 GPU 但后端不存在/不可用"的假加速)
- 硬件探测零依赖: 不 import onnxruntime/torch, 只读系统信息; 选后端时才惰性导入
"""
import glob
import os
import subprocess
import sys
import threading

_LOCK = threading.Lock()
_DETECTED = False
GPU_INFO = {
    "has_gpu": False,
    "vendor": "",      # NVIDIA / AMD / INTEL / ""
    "name": "",
    "vram_mb": 0,
    "score": 0,        # 0~100, 综合评分(用于动态调整并发/批大小)
    "desktop": False,  # 是否为独显
}


def _run(cmd, timeout=2.0):
    """静默执行命令(隐藏窗口), 返回 stdout 文本或空串"""
    try:
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, **kw)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def _detect_nvidia() -> bool:
    """nvidia-smi 探测 NVIDIA 独显"""
    out = _run(["nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits"])
    if not out:
        return False
    first = out.splitlines()[0]
    parts = [x.strip() for x in first.split(",")]
    if len(parts) >= 2:
        try:
            vram = int(float(parts[1]))
        except Exception:
            vram = 0
        GPU_INFO.update(has_gpu=True, vendor="NVIDIA", name=parts[0],
                        vram_mb=vram, desktop=True)
        return True
    return False


def _detect_wmi() -> bool:
    """Windows WMI 探测(AMD/Intel 等; 含集显, 后续评分筛选)"""
    out = _run(["powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM,VideoProcessor | "
                "ConvertTo-Csv -NoTypeInformation)"], timeout=4.0)
    if not out:
        return False
    best = None
    for line in out.splitlines()[1:]:
        cols = [c.strip('"') for c in line.split('","')]
        if not cols:
            continue
        name = cols[0] if cols else ""
        try:
            vram = int(cols[1]) if len(cols) > 1 and cols[1].isdigit() else 0
        except Exception:
            vram = 0
        if any(k in name.upper() for k in ("MICROSOFT BASIC", "REMOTE", "VIRTUAL")):
            continue
        vendor = "NVIDIA" if "NVIDIA" in name.upper() else (
            "AMD" if ("AMD" in name.upper() or "RADEON" in name.upper()) else (
                "INTEL" if "INTEL" in name.upper() else ""))
        cand = (vram, vendor, name)
        if best is None or cand[0] > best[0]:
            best = cand
    if best:
        vram_mb = int(best[0] / (1024 * 1024)
                      ) if best[0] > 0 else 0  # AdapterRAM 为字节
        GPU_INFO.update(has_gpu=True, vendor=best[1], name=best[2],
                        vram_mb=vram_mb, desktop=(best[1] == "NVIDIA"))
        return True
    return False


def _score():
    """依据厂商/显存打分(0~100): 用于动态调整并发与批大小"""
    if not GPU_INFO["has_gpu"]:
        GPU_INFO["score"] = 0
        return
    v = GPU_INFO["vendor"]
    vram = GPU_INFO["vram_mb"]
    base = {"NVIDIA": 70, "AMD": 55, "INTEL": 40}.get(v, 30)
    # 显存加成: 8GB+ 顶格
    vram_bonus = min(30, int(vram / 1024 * 4)) if vram else 10
    GPU_INFO["score"] = max(0, min(100, base + vram_bonus))
    # 分数过低(老核显/极小显存)视为无 GPU, 走 CPU 更稳
    if GPU_INFO["score"] < 35:
        GPU_INFO["has_gpu"] = False
        GPU_INFO["score"] = 0


def detect(force: bool = False) -> dict:
    """探测 GPU(进程内缓存); 任何异常返回 CPU 结果"""
    global _DETECTED
    if _DETECTED and not force:
        return GPU_INFO
    with _LOCK:
        if _DETECTED and not force:
            return GPU_INFO
        try:
            if not _detect_nvidia() and sys.platform == "win32":
                _detect_wmi()
            _score()
        except Exception:
            GPU_INFO.update(has_gpu=False, score=0)
        _DETECTED = True
    return GPU_INFO


try:
    detect()
except Exception:
    pass


# ============ 派生建议(供各模块取用) ============

def suggest_ort_providers() -> list:
    """(保留名) 建议的 GPU provider 顺序; 无可用 GPU 后端时返回空列表(仅 CPU)"""
    return pick_ort_providers()


# ============ ORT 执行后端自适应(单一事实源) ============
# 平台优先顺序(取 onnxruntime 实际可用后端与之的交集):
#   Windows → CUDA(装有完整 cuDNN 环境时最快) → DirectML(exe 内置, 全厂商) → OpenVINO
#   macOS   → CoreML(官方 wheel 自带)
#   Linux   → CUDA / ROCm / OpenVINO
# 注: 逐级按优先级尝试, 任一档验证失败自动降档(见 ocr_utils._try_init_rapidocr)
_PLATFORM_EP_ORDER = {
    "win32": ["CUDAExecutionProvider", "DmlExecutionProvider",
              "OpenVINOExecutionProvider"],
    "darwin": ["CoreMLExecutionProvider"],
    "linux": ["CUDAExecutionProvider", "ROCMExecutionProvider",
              "OpenVINOExecutionProvider"],
}

_PROVIDERS_LOCK = threading.Lock()
_PROVIDERS_CACHE = None


def _mount_cuda_dlls():
    """Windows: 将 NVIDIA 运行库挂到 DLL 搜索路径(失败静默忽略)

    包含: pip 安装的 nvidia-*(cuDNN/cuBLAS 等)的 bin 目录 与 CUDA_PATH/CUDA_HOME/bin。
    目的: 让"只 pip 装了 nvidia-cudnn-cuXX、未装完整 CUDA Toolkit"的机器也能启用 CUDA EP。
    """
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return
    dirs = []
    try:
        import site
        bases = []
        try:
            bases += list(site.getsitepackages())
        except Exception:
            pass
        try:
            bases.append(site.getusersitepackages())
        except Exception:
            pass
        for b in bases:
            try:
                dirs += glob.glob(os.path.join(b, "nvidia", "*", "bin"))
            except Exception:
                pass
    except Exception:
        pass
    for key in ("CUDA_PATH", "CUDA_HOME"):
        p = (os.environ.get(key) or "").strip()
        if p:
            dirs += [os.path.join(p, "bin"), os.path.join(p, "bin", "x64")]
    for d in dirs:
        try:
            if d and os.path.isdir(d):
                os.add_dll_directory(d)
        except Exception:
            pass


def available_ort_providers() -> list:
    """onnxruntime 实际可用的执行后端(惰性导入 onnxruntime; 失败返回空列表)"""
    try:
        _mount_cuda_dlls()
        import onnxruntime as _ort
        return list(_ort.get_available_providers())
    except Exception:
        return []


def pick_ort_providers() -> list:
    """挑出本机真正可用的 GPU 执行后端(按平台优先级; 不含 CPU; 空=仅 CPU)

    仅当"硬件探测到 GPU"且"该平台对应的后端真实存在"时才返回,
    避免出现"探测到 GPU 但后端不存在"的假加速。
    环境变量 YATORI_OCR_CPU=1 可强制走 CPU(便于对比/排查)。
    """
    global _PROVIDERS_CACHE
    if _PROVIDERS_CACHE is not None:
        return _PROVIDERS_CACHE
    if os.environ.get("YATORI_OCR_CPU", "").strip().lower() in ("1", "true", "yes", "on"):
        _PROVIDERS_CACHE = []          # 强制 CPU
        return _PROVIDERS_CACHE
    with _PROVIDERS_LOCK:
        if _PROVIDERS_CACHE is None:
            picked = []
            try:
                g = detect()
                if g.get("has_gpu"):
                    avail = set(available_ort_providers())
                    for name in _PLATFORM_EP_ORDER.get(sys.platform, []):
                        if name in avail and name not in picked:
                            picked.append(name)
            except Exception:
                picked = []
            _PROVIDERS_CACHE = picked
    return _PROVIDERS_CACHE


def decode_workers_hint() -> int:
    """解码/解析建议线程数: 有强 GPU 时解码可让 GPU 分担, 减少 CPU 线程"""
    g = detect()
    cpu = os.cpu_count() or 4
    if g["has_gpu"] and g["score"] >= 60:
        return max(1, cpu // 2)
    return max(1, min(4, cpu - 1)) if cpu <= 4 else max(1, cpu // 2)


def summary() -> str:
    """一行摘要(启动日志用)"""
    g = detect()
    if not g["has_gpu"]:
        return "GPU: 未检测到可用独立显卡/核显加速, 使用 CPU 模式"
    return (f"GPU: {g['name']} ({g['vendor']}, {g['vram_mb']}MB, "
            f"评分 {g['score']}/100)")


# ============ onnxruntime GPU 真实可用性检测 ============
def ort_gpu_available() -> bool:
    """确认当前 onnxruntime 真实具备 GPU 执行器(避免“假可用”拖慢/报错)
    仅当安装了 onnxruntime-gpu(CUDA) 或 onnxruntime-directml 时才返回 True。"""
    try:
        import onnxruntime as ort
        provs = ort.get_available_providers() or []
        return any(p in provs for p in (
            "CUDAExecutionProvider", "DmlExecutionProvider", "ROCMExecutionProvider"))
    except Exception:
        return False


# 说明(2026-09-24): 此前会自动设置 OMP/ORT 线程环境变量,
# 经实测会限制 CPU 版 ONNX/OpenCV 并行度导致变慢, 已按用户要求删除;
# 现不再干预任何线程环境, 仅提供真实可用性检测供 OCR 模块调用。
