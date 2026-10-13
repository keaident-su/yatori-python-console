# -*- coding: utf-8 -*-
"""反调试/反附加守护(Windows)

设计目标(方案A - Cython 原生编译之上的增强, 提高动态分析门槛):
- 启动时与运行期周期性检测调试器/调试器附加(IsDebuggerPresent /
  CheckRemoteDebuggerPresent), 命中后立即静默退出;
- 非 Windows 平台为 no-op, 不影响跨平台构建;
- 守护线程为 daemon, 不阻塞主流程; 幂等启动。

注意: 本模块仅提高逆向门槛, 不构成绝对防护。
"""
import sys
import threading

_GUARD_STARTED = threading.Event()
_CHECK_INTERVAL = 2.0   # 秒


def _win_debugger_present() -> bool:
    """Windows 下检测调试器(前台调试/远程附加)"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32   # type: ignore[attr-defined]
        # 1) 自身是否被调试
        if k32.IsDebuggerPresent():
            return True
        # 2) 是否被远程调试器附加
        handle = k32.GetCurrentProcess()
        dbg = ctypes.c_int(0)
        if k32.CheckRemoteDebuggerPresent(handle, ctypes.byref(dbg)):
            return bool(dbg.value)
    except Exception:
        return False
    return False


def _guard_loop():
    while True:
        if _win_debugger_present():
            # 静默退出, 不暴露检测逻辑细节
            import os
            os._exit(0)
        threading.Event().wait(_CHECK_INTERVAL)


def start_anti_debug_guard():
    """启动反调试守护(幂等; 非 Windows 直接返回)"""
    if _GUARD_STARTED.is_set():
        return
    _GUARD_STARTED.set()
    if sys.platform != "win32":
        return
    # 启动前先查一次(命中直接退出), 再起守护线程
    if _win_debugger_present():
        import os
        os._exit(0)
    t = threading.Thread(target=_guard_loop, name="yatori-antidebug",
                         daemon=True)
    t.start()
