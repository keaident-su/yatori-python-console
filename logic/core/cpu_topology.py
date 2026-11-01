# -*- coding: utf-8 -*-
"""
CPU 拓扑探测与亲和性模块（异构处理器 P核/E核 自适应）
====================================================
仅依赖标准库（Windows spawn 子进程可安全导入）。

探测策略（尽力而为 + 安全降级，禁止硬编码 CPU 型号）：
- Windows: GetSystemCpuSetInformation 的 EfficiencyClass（Win10 1607+，
  性能核 EfficiencyClass 更高）；失败回退注册表
  HARDWARE\\DESCRIPTION\\System\\CentralProcessor 各核 ~MHz。
- Linux: /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq。
- macOS: sysctl hw.perflevel0/hw.perflevel1.physicalcpu。

判定规则（通用特征，不认型号）：
- 有 EfficiencyClass 差异 → 高等级为 P 核；
- 否则按最大频率聚类：频率差 >=15% 视为异构，>=最大值85% 的为 P 核；
- 虚拟机/旧系统探测不到 → 按同构(os.cpu_count())处理，绝不报错。

调度策略：进程池 worker 优先绑定 P 核（Linux sched_setaffinity /
Windows SetProcessAffinityMask），绑不了则交给系统调度器（降级）。
"""
import os
import sys

# 频率差达到该比例才认定为异构（避免同构机 turbo 差异误判）；
# Windows 注册表 ~MHz 为实时采样值，波动大，单独用更保守的阈值
_HETERO_SPREAD = 0.15
_HETERO_SPREAD_REALTIME = 0.30
# 频率达到最大值该比例的逻辑处理器视为性能核
_P_CORE_RATIO = 0.85


def _detect_windows():
    """Windows: 优先 GetSystemCpuSetInformation(EfficiencyClass)。
    只要该接口可用（即使全部核心能效等级相同=同构）即采信；
    仅当接口完全不可用（老系统）时才回退注册表 ~MHz。
    注意：~MHz 是实时运行频率采样值，同构机各核不同步，
    只能作为老系统上的最后手段（频率聚类阈值已相应放宽）。
    返回 {逻辑处理器编号: (频率或0, 能效等级)} 或 None
    """
    info = _detect_windows_cpusets()
    if info is not None:
        return info
    # 回退：注册表 ~MHz（老系统无 CpuSet 接口时的最后手段，
    # 实测多数机器各核同值=标称基频，将判为同构）
    try:
        import winreg
        freqs = {}
        base = r"HARDWARE\DESCRIPTION\System\CentralProcessor"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(
                            winreg.HKEY_LOCAL_MACHINE,
                            base + "\\" + sub) as sk:
                        mhz, _ = winreg.QueryValueEx(sk, "~MHz")
                        freqs[int(sub)] = (int(mhz), 0)
                except Exception:
                    pass
        return freqs or None
    except Exception:
        return None


def _detect_windows_cpusets():
    """GetSystemCpuSetInformation 解析：{逻辑处理器: (MaxFrequency, EfficiencyClass)}"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        fn = k32.GetSystemCpuSetInformation
        fn.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                       ctypes.POINTER(ctypes.c_ulong),
                       ctypes.c_void_p, ctypes.c_ulong]
        fn.restype = ctypes.c_int
        handle = k32.GetCurrentProcess()
        need = ctypes.c_ulong(0)
        fn(None, 0, ctypes.byref(need), handle, 0)
        if need.value <= 0:
            return None
        buf = (ctypes.c_ubyte * need.value)()
        got = ctypes.c_ulong(0)
        if not fn(buf, need.value, ctypes.byref(got), handle, 0):
            return None
        data = bytes(buf[:got.value])
        raw = []  # (size, entry_bytes)
        off = 0
        while off + 8 <= len(data):
            size = int.from_bytes(data[off:off + 4], "little")
            etype = int.from_bytes(data[off + 4:off + 8], "little")
            if size < 16 or size > 1024:
                break
            if etype == 0:  # CpuSetInformation
                raw.append(data[off:off + size])
            off += size
        return _parse_cpuset_entries(raw)
    except Exception:
        return None


def _parse_cpuset_entries(raw):
    """解析 CpuSet 条目。不同 Windows 版本字段布局存在差异（实测
    Win11 26H2 为字节紧凑布局，与文档 WORD 布局不同），因此对两种
    候选布局各自解析并自校验：能解析出连续不重复逻辑处理器编号
    (0..n-1) 的布局才是正确布局。均不成立则返回 None。
    布局A(文档版): LPI@14(WORD) Eff@19；布局B(实测紧凑版): LPI@14(BYTE) Eff@18
    """
    if not raw:
        return {}
    groups = set()
    for e in raw:
        if len(e) >= 14:
            groups.add(int.from_bytes(e[12:14], "little"))
    if groups - {0}:
        # 多处理器组(>64核多路服务器)：混合架构不会跨组，
        # 按同构多路处理，不参与异构判定
        return None

    for lpi_is_word, eff_off in ((True, 19), (False, 18)):
        cand = {}
        ok = True
        for e in raw:
            if len(e) < 20:
                ok = False
                break
            if lpi_is_word:
                lpi = int.from_bytes(e[14:16], "little")
            else:
                lpi = e[14]
            maxf = (int.from_bytes(e[24:28], "little")
                    if len(e) >= 28 else 0)
            if lpi in cand:
                ok = False
                break
            cand[lpi] = (maxf, e[eff_off])
        # 自校验：逻辑处理器编号必须是连续的 0..n-1
        if ok and cand and sorted(cand) == list(range(len(cand))):
            return cand
    return None


def _detect_linux():
    """Linux: cpuinfo_max_freq；虚拟机无 cpufreq 返回 None(降级同构)"""
    try:
        freqs = {}
        base = "/sys/devices/system/cpu"
        for name in os.listdir(base):
            if not (name.startswith("cpu") and name[3:].isdigit()):
                continue
            idx = int(name[3:])
            path = os.path.join(base, name, "cpufreq", "cpuinfo_max_freq")
            try:
                with open(path) as f:
                    freqs[idx] = (int(f.read().strip()), 0)
            except Exception:
                pass
        return freqs or None
    except Exception:
        return None


def _detect_macos():
    """macOS: perflevel0/1 逻辑核数；Apple 不暴露逻辑号映射，按编号顺序近似"""
    try:
        import subprocess

        def _sysctl(name):
            out = subprocess.check_output(
                ["sysctl", "-n", name], timeout=5).decode().strip()
            return int(out)

        pl0 = _sysctl("hw.perflevel0.logicalcpu")
        pl1 = _sysctl("hw.perflevel1.logicalcpu")
        total = _sysctl("hw.logicalcpu")
        freqs = {}
        for i in range(total):
            # 性能核赋高频(2)，能效核低频(1)；无 pl1 则全同值(同构)
            freqs[i] = (2 if (pl1 <= 0 or i < pl0) else 1, 0)
        return freqs or None
    except Exception:
        return None


def _classify(freqs, realtime_freq=False):
    """按通用特征(能效等级/最大频率)划分 P/E 核
    realtime_freq=True 表示频率为实时采样值（如Windows注册表~MHz），
    采用更保守的阈值防误判。
    返回 (p_cpus, e_cpus, is_heterogeneous)
    """
    if not freqs:
        return None, None, False
    # 1) EfficiencyClass 差异（Windows 混合架构权威信号）
    effs = [eff for _, eff in freqs.values()]
    if effs and max(effs) > min(effs):
        top = max(effs)
        p = sorted(c for c, (_, e) in freqs.items() if e == top)
        ec = sorted(c for c, (_, e) in freqs.items() if e != top)
        return p, ec, True
    # 2) 最大频率聚类
    fs = [f for f, _ in freqs.values() if f > 0]
    if not fs:
        return None, None, False
    mx, mn = max(fs), min(fs)
    spread_thr = (_HETERO_SPREAD_REALTIME if realtime_freq
                  else _HETERO_SPREAD)
    if (mx - mn) / mx < spread_thr:
        return None, None, False
    thr = mx * _P_CORE_RATIO
    p = sorted(c for c, (f, _) in freqs.items() if f >= thr)
    ec = sorted(c for c, (f, _) in freqs.items() if 0 < f < thr)
    if not p or not ec:
        return None, None, False
    return p, ec, True


def apply_affinity(cpu_ids):
    """将当前进程绑定到指定逻辑处理器；失败静默返回 False（绝不抛异常）"""
    try:
        if not cpu_ids:
            return False
        if sys.platform.startswith("linux") and hasattr(
                os, "sched_setaffinity"):
            os.sched_setaffinity(0, set(cpu_ids))
            return True
        if sys.platform == "win32":
            # 亲和性掩码仅覆盖第0组64个逻辑处理器
            if any(c >= 64 for c in cpu_ids):
                return False
            mask = 0
            for c in cpu_ids:
                mask |= (1 << c)
            import ctypes
            k32 = ctypes.windll.kernel32
            fn = k32.SetProcessAffinityMask
            # 显式声明参数类型，避免 64 位掩码/句柄被截断
            fn.argtypes = [ctypes.c_void_p, ctypes.c_ulonglong]
            fn.restype = ctypes.c_int
            return bool(fn(k32.GetCurrentProcess(), mask))
    except Exception:
        pass
    return False  # macOS 等不支持亲和性的平台


def pool_worker_init(cpu_ids, do_bind):
    """进程池 worker 初始化回调（必须为模块顶层函数，spawn 可 pickle）"""
    if do_bind and cpu_ids:
        apply_affinity(cpu_ids)


def _detect_all():
    """主探测入口：返回 (p_cpus, e_cpus, is_hetero, desc, strategy)
    任何异常一律降级为同构，绝不抛出。
    """
    total = os.cpu_count() or 4
    try:
        realtime = False
        if sys.platform == "win32":
            freqs = _detect_windows()
            # 空 dict = 接口已采信但无第0组条目，直接按同构处理
            if freqs is not None and not freqs:
                return (list(range(total)), [], False,
                        f"同构处理器: {total}逻辑处理器",
                        "同构-全部核心均摊", False)
            # 走到注册表回退路径时频率为实时值，用保守阈值
            realtime = _detect_windows_cpusets() is None
        elif sys.platform.startswith("linux"):
            freqs = _detect_linux()
        elif sys.platform == "darwin":
            freqs = _detect_macos()
        else:
            freqs = None
        p, e, hetero = _classify(freqs, realtime)
        if hetero and p:
            bindable = (sys.platform.startswith("linux")
                        and hasattr(os, "sched_setaffinity")) or (
                sys.platform == "win32"
                and all(c < 64 for c in p))
            strategy = ("异构-进程池绑定P核" if bindable
                        else "异构-降级(系统调度器托管)")
            desc = (f"异构处理器: {total}逻辑处理器"
                    f"（P核{len(p)}个逻辑处理器/E核{len(e)}个）")
            return p, e, True, desc, strategy, bindable
        # 同构（或频率信息不足）
        if freqs:
            return (list(range(total)), [], False,
                    f"同构处理器: {total}逻辑处理器",
                    "同构-全部核心均摊", False)
        return (list(range(total)), [], False,
                f"拓扑未知: {total}逻辑处理器",
                "同构-默认(探测降级)", False)
    except Exception:
        return (list(range(total)), [], False,
                f"拓扑未知: {total}逻辑处理器",
                "同构-默认(探测降级)", False)


# ---- 模块级探测结果（import 时一次性计算，spawn 子进程重新计算亦安全） ----
P_CPUS, E_CPUS, IS_HETEROGENEOUS, TOPOLOGY_DESC, \
    SCHEDULE_STRATEGY, BIND_POSSIBLE = _detect_all()

# 性能核逻辑处理器数（同构时等于全部逻辑处理器数）
P_CORE_COUNT = len(P_CPUS) if P_CPUS else (os.cpu_count() or 4)
