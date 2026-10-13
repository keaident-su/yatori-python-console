# -*- coding: utf-8 -*-
"""
多核并行配置模块 - 所有并发参数基于 CPU 逻辑核心/线程数动态计算
=================================================================
【基准核数规则】(2026-09-24 与用户确认)
  - 默认(basicSetting.fullCpuMode=0): 基准 = 逻辑核数 - 1 (n-1, 给系统保留一份)
  - 全速(basicSetting.fullCpuMode=1): 基准 = 逻辑核数     (n, 吃满全部)
【性能档位】(basicSetting.performanceGear)
  - aggressive(默认): 登录=基准×1.5 / 提交=基准 / AI=基准/2 / 视频=基准×3/4
  - conservative:     登录=基准   / 提交=基准/2 / AI=基准/2 / 视频=基准/2
【节点间隔】2.0/基准 秒, 下限 0.06s
【动态微调】perf_tuner 依据 psutil 实测负载给全局系数(0.5~1.5),
  所有 tuned_* 取值 = 档位值 × 系数 (仅影响运行期实时取值, 不影响已建池)
【注入方式】main.py 启动最早处读取 config.yaml → 设环境变量:
  YATORI_FULL_CPU / YATORI_PERF_GEAR → 本模块惰性读取(兼容热更新时 refresh)

异构处理器(大小核)：P/E 核拓扑见 cpu_topology.py, worker 优先绑 P 核。
"""
import os

from logic.core.cpu_topology import (
    P_CPUS, E_CPUS, IS_HETEROGENEOUS, TOPOLOGY_DESC,
    SCHEDULE_STRATEGY, BIND_POSSIBLE, P_CORE_COUNT)

# CPU 逻辑处理器数（含超线程；多路处理器为全部插槽之和）
CPU_COUNT = os.cpu_count() or 4


def _full_cpu() -> bool:
    """全速开关: True=吃满全部逻辑核 / False(默认)=n-1 保留一份"""
    return os.environ.get("YATORI_FULL_CPU") == "1"


def _gear() -> str:
    """性能档位: aggressive(默认) / conservative"""
    g = (os.environ.get("YATORI_PERF_GEAR") or "aggressive").strip().lower()
    return "conservative" if g == "conservative" else "aggressive"


def base_cores() -> int:
    """基准核数 = n(全速) 或 n-1(默认)"""
    return CPU_COUNT if _full_cpu() else max(1, CPU_COUNT - 1)


# ==================== 型号配置(cpus/*.yaml)优先 ====================

def _prof(key: str):
    """取该 CPU 型号配置中的参数值(自动处理全速缩放); 未配置返回 None

    约定: cpus/*.yaml 中的值 = 默认模式(n-1基准)推荐值;
    全速模式下: 并发类按 n/(n-1) 上调, 间隔类按 (n-1)/n 缩小。
    """
    try:
        from logic.core import cpu_profile
        v = cpu_profile.get(key)
    except Exception:
        return None
    if v is None:
        return None
    n = max(2, CPU_COUNT)
    base = max(1, n - 1)
    if _full_cpu():
        if key in ("nodeStartInterval",):
            v = v * base / n
        else:
            v = v * n / base
    return v


# ==================== 档位公式 (全部惰性, 支持热更新/动态读取) ====================

def login_workers() -> int:
    """账号登录并行工作线程数(型号配置优先; 公式: 激进基准×1.5 / 稳健基准)"""
    v = _prof("loginWorkers")
    if v is not None:
        return max(2, int(v))
    b = base_cores()
    if _gear() == "conservative":
        return max(8, b)
    return max(8, int(b * 1.5))


def work_concurrency() -> int:
    """作业/考试/章测等答题提交级并发(型号配置优先; 公式: 激进基准 / 稳健基准/2)"""
    v = _prof("workConcurrency")
    if v is not None:
        return max(2, int(v))
    b = base_cores()
    if _gear() == "conservative":
        return max(2, b // 2)
    return max(2, b)


def ai_concurrency() -> int:
    """AI 请求并发(型号配置优先; 公式: 基准/2)"""
    v = _prof("aiConcurrency")
    if v is not None:
        return max(1, int(v))
    b = base_cores()
    return max(2, b // 2)


def fast_video_workers() -> int:
    """快速刷视频并发(型号配置优先; 公式: 激进基准×3/4 / 稳健基准/2)"""
    v = _prof("fastVideoWorkers")
    if v is not None:
        return max(2, int(v))
    b = base_cores()
    if _gear() == "conservative":
        return max(5, b // 2)
    return max(5, int(b * 3 / 4))


def node_start_interval() -> float:
    """节点启动间隔(型号配置优先; 公式: 2.0/基准, 下限 0.06s)"""
    v = _prof("nodeStartInterval")
    if v is not None:
        return max(0.06, round(v, 3))
    return max(0.06, round(2.0 / base_cores(), 3))


def http_max_connections() -> int:
    v = _prof("httpMaxConnections")
    if v is not None:
        return max(64, int(v))
    return max(128, base_cores() * 16)


def http_max_keepalive() -> int:
    v = _prof("httpMaxConnections")
    if v is not None:
        return max(32, int(v) // 2)
    return max(64, base_cores() * 8)


def cpu_pool_workers() -> int:
    """CPU密集解析进程池(型号配置优先; 公式: 异构按P核/同构按核数的一半)"""
    v = _prof("cpuPoolWorkers")
    if v is not None:
        return max(2, int(v))
    base = P_CORE_COUNT if IS_HETEROGENEOUS else CPU_COUNT
    w = max(2, base // 2)
    if not _full_cpu():
        w = max(2, w - 1)
    return w


# ==================== 运行期微调(perf_tuner 系数) ====================

def _tuner_scale() -> float:
    try:
        from logic.core.perf_tuner import get_scale
        return float(get_scale())
    except Exception:
        return 1.0


def _tuned(v: int, floor: int = 1) -> int:
    return max(floor, int(v * _tuner_scale()))


def tuned_login_workers() -> int:
    return _tuned(login_workers(), 4)


def tuned_work_concurrency() -> int:
    return _tuned(work_concurrency(), 1)


def tuned_ai_concurrency() -> int:
    return _tuned(ai_concurrency(), 1)


def tuned_fast_video_workers() -> int:
    return _tuned(fast_video_workers(), 3)


def tuned_node_start_interval() -> float:
    """间隔与系数反比: 负载低→间隔更短; 下限 0.06s"""
    v = node_start_interval() / max(0.5, min(1.5, _tuner_scale()))
    return max(0.06, round(v, 3))


# ==================== 启动横幅 ====================

def perf_summary() -> str:
    """一行性能策略摘要(启动日志用)"""
    mode = "全速吃满" if _full_cpu() else "默认(n-1保留一份)"
    return (f"性能策略: {mode}[{base_cores()}/{CPU_COUNT}核] 档位={_gear()} | "
            f"登录={login_workers()} 提交={work_concurrency()} "
            f"AI={ai_concurrency()} 视频={fast_video_workers()} "
            f"节点间隔={node_start_interval()}s")
