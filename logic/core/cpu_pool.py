# -*- coding: utf-8 -*-
"""
CPU 密集计算进程池 - 用 multiprocessing 绕开 Python GIL，真正吃满多核
用于 HTML/JSON 大批量解析等纯计算任务（函数必须是模块顶层可 pickle 的纯函数）。

Windows spawn 注意事项：
- 进程池惰性创建（不在 import 时创建）
- 传入函数必须是模块顶层函数，参数必须可 pickle
- main.py 已有 if __name__ == "__main__" 保护
异构 CPU（大小核混合）：worker 进程初始化时通过
initializer 绑定 P 核（优先吃满高性能核，探测失败自动降级）。
任何异常都会优雅降级为当前进程内联执行，绝不影响主流程。
"""
import atexit
import threading
from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Iterable, List, Any

from logic.core.parallel import CPU_POOL_WORKERS
from logic.core.cpu_topology import (
    P_CPUS, IS_HETEROGENEOUS, BIND_POSSIBLE, pool_worker_init)

_pool = None
_pool_lock = threading.Lock()
_pool_disabled = False  # 一旦创建/使用失败则永久禁用，直接内联执行


def _get_pool():
    global _pool, _pool_disabled
    if _pool_disabled:
        return None
    with _pool_lock:
        if _pool is None and not _pool_disabled:
            try:
                # 异构CPU且平台支持亲和性时，worker 进程初始化即绑定P核；
                # 同构/探测降级时 do_bind=False，行为与原有一致
                _bind = IS_HETEROGENEOUS and BIND_POSSIBLE
                _pool = ProcessPoolExecutor(
                    max_workers=CPU_POOL_WORKERS,
                    initializer=pool_worker_init,
                    initargs=(P_CPUS if _bind else [], _bind))
            except Exception:
                _pool_disabled = True
                _pool = None
    return _pool


def cpu_map(func: Callable, items: Iterable[Any], chunksize: int = 1) -> List[Any]:
    """将纯计算函数 func 分发到进程池并行执行；失败自动降级为串行内联执行"""
    items = list(items)
    if not items:
        return []
    # 单元素或数据量小不值得跨进程序列化开销，直接内联
    if len(items) == 1:
        return [func(items[0])]
    pool = _get_pool()
    if pool is None:
        return [func(x) for x in items]
    global _pool_disabled
    try:
        return list(pool.map(func, items, chunksize=chunksize))
    except Exception:
        # 进程池异常（如序列化失败）：本次降级内联，并禁用进程池避免反复重试
        _pool_disabled = True
        try:
            pool.shutdown(wait=False)
        except Exception:
            pass
        _pool = None
        return [func(x) for x in items]


def _shutdown():
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.shutdown(wait=False)
            except Exception:
                pass
            _pool = None


atexit.register(_shutdown)
