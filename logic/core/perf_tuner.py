# -*- coding: utf-8 -*-
"""
运行期性能微调器 (perf tuner)
================================================================
依据 psutil 实测 CPU 负载动态给出全局系数(0.5 ~ 1.5):
  - 负载持续 < 50% : 系数 +0.1 (提速, 上限 1.5)
  - 负载持续 > 85% : 系数 -0.1 (降速, 下限 0.5)
消费方通过 logic.core.parallel 的 tuned_* 函数或本模块 get_scale() 实时取值。
说明: 系数只影响"下一次取用"的值(新任务/新线程池), 不强制打断进行中任务;
     任何异常均静默(系数保持 1.0), 绝不影响主流程。
"""
import threading
import time

_SCALE = 1.0
_LOCK = threading.Lock()
_STARTED = False

LOW_LOAD = 50.0     # 低负载阈值(%)
HIGH_LOAD = 85.0    # 高负载阈值(%)
STEP = 0.1
SCALE_MIN = 0.5
SCALE_MAX = 1.5
INTERVAL = 10.0     # 采样周期(秒)

# 最近一次实测负载(状态展示用)
LAST_LOAD = -1.0


def get_scale() -> float:
    """当前动态系数(1.0=档位原值)"""
    with _LOCK:
        return _SCALE


def set_scale(v: float):
    """手动设定系数(调试/前端强制干预用, 会被区间钳制)"""
    global _SCALE
    with _LOCK:
        _SCALE = max(SCALE_MIN, min(SCALE_MAX, float(v)))


def status() -> dict:
    """状态快照(日志/前端展示)"""
    with _LOCK:
        return {"scale": _SCALE, "last_load": LAST_LOAD,
                "low": LOW_LOAD, "high": HIGH_LOAD,
                "min": SCALE_MIN, "max": SCALE_MAX}


def _loop():
    global _SCALE, LAST_LOAD
    try:
        import psutil
        psutil.cpu_percent(None)   # 预热(第一次必返回0, 丢弃)
    except Exception:
        return                     # 无 psutil: 保持恒定 1.0
    while True:
        time.sleep(INTERVAL)
        try:
            load = float(psutil.cpu_percent(None))   # 本区间平均值
            LAST_LOAD = load
            with _LOCK:
                if load < LOW_LOAD and _SCALE < SCALE_MAX:
                    _SCALE = min(SCALE_MAX, round(_SCALE + STEP, 2))
                elif load > HIGH_LOAD and _SCALE > SCALE_MIN:
                    _SCALE = max(SCALE_MIN, round(_SCALE - STEP, 2))
        except Exception:
            pass


def start():
    """启动后台采样线程(幂等; 由 launcher 调用)"""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    try:
        t = threading.Thread(target=_loop, daemon=True, name="perf-tuner")
        t.start()
    except Exception:
        pass
