# -*- coding: utf-8 -*-
"""
多核并行配置模块 - 所有并发参数基于 CPU 逻辑核心/线程数动态计算
Windows 下 os.cpu_count() 包含超线程与多路(双路E5/NUMA)全部逻辑处理器，
线程数可超过单路核心数，目标是"有多少核心/线程就尽量吃满多少"。
异构处理器(大小核混合)：优先吃满 P 核，不够再扩展到 E 核，
拓扑探测与调度策略见 logic/core/cpu_topology.py。
"""
import os

from logic.core.cpu_topology import (
    P_CPUS, E_CPUS, IS_HETEROGENEOUS, TOPOLOGY_DESC,
    SCHEDULE_STRATEGY, BIND_POSSIBLE, P_CORE_COUNT)

# CPU 逻辑处理器数（含超线程；多路处理器为全部插槽之和）
CPU_COUNT = os.cpu_count() or 4


def _scaled(divisor: int, floor: int, ceil: int = 0) -> int:
    v = max(floor, CPU_COUNT // max(1, divisor))
    if ceil > 0:
        v = min(v, ceil)
    return v


# ---- AI 请求并发（原固定2，对齐Go AiSem；现按核心数扩展） ----
AI_CONCURRENCY = _scaled(4, 2)

# ---- 账号登录并行工作线程数（I/O密集，可超配） ----
LOGIN_WORKERS = _scaled(1, 8, 128)

# ---- 海旗科技快速刷视频并发（原固定5） ----
FAST_VIDEO_WORKERS = _scaled(2, 5, 64)

# ---- CPU密集解析进程池工作进程数（绕开GIL，真正吃满多核） ----
# 异构CPU按P核逻辑处理器数计（worker 将绑定P核，优先吃满高性能核）；
# 同构CPU按全部逻辑处理器数计
_POOL_BASE = P_CORE_COUNT if IS_HETEROGENEOUS else CPU_COUNT
CPU_POOL_WORKERS = max(2, _POOL_BASE // 2)

# ---- mode3 节点线程启动间隔（秒）：核心越多间隔越短，保留最小节流防风控 ----
NODE_START_INTERVAL = max(0.1, round(2.0 / CPU_COUNT, 3))

# ---- httpx 连接池上限（每个账号独立连接池，按核心数放大） ----
HTTP_MAX_CONNECTIONS = max(128, CPU_COUNT * 16)
HTTP_MAX_KEEPALIVE = max(64, CPU_COUNT * 8)

# ---- 作业/考试/章测等答题提交级并发 ----
WORK_CONCURRENCY = _scaled(4, 2)
