# -*- coding: utf-8 -*-
"""[V3.2.3] 跨平台"可重做项"巡检框架（2026-10-26 用户定夺）

需求（用户定夺）:
  · 遍历 作业/章测/考试/其他测验，找出"可重做且有余量"的项
  · 已过期/已截止的作业和考试 → 跳过
  · 每次账号登录时检查一次 + 运行内每 1 小时检查一次
  · 各平台通用（本框架全平台接入；能力按平台实现，未实现=只发现不执行）

平台接入（在各自 part.py 末尾）:
    from logic.core import retake_scanner as rs
    rs.register("XUEXITONG", scan_fn, exec_fn=None)
    # scan_fn(cache, user, log) -> List[RetakeItem]   (内部自行拉课程)
    # exec_fn(cache, user, item, log) -> bool          (None=该平台只发现不执行)

判定（redoTimes + 阈值双重）:
    · expired=True            -> 跳过（已过期/已截止/已失效）
    · remaining == 0          -> 跳过（页面 redoTimes=0，无重做余量）
    · rate >= 阈值(%)         -> 跳过（得分率已达标）
    · remaining > 0 且 rate < 阈值 -> 可执行（remaining=-1 未知时也允许尝试）

日志（统一前缀【可重做巡检】）便于检索。
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

SCAN_INTERVAL = 3600  # 每小时

_SCANNERS: Dict[str, Callable] = {}
_EXECUTORS: Dict[str, Callable] = {}
_last_scan: Dict[str, float] = {}
_guard = threading.Lock()


@dataclass
class RetakeItem:
    """一个"可能可重做"的作业/章测/考试/测验"""
    platform: str
    course: str
    kind: str                     # 作业/章测/考试/测验
    name: str
    status: str = ""
    rate: Optional[float] = None  # 得分率(%)
    score: Optional[float] = None
    total: Optional[float] = None
    remaining: int = -1           # -1=未知, 0=无余量, >0=剩余重做次数
    expired: bool = False
    note: str = ""                # 附加说明(如平台限制)
    ref: Dict[str, Any] = field(default_factory=dict)  # 执行所需上下文


def register(platform_key: str, scan_fn: Callable,
             exec_fn: Optional[Callable] = None) -> None:
    _SCANNERS[platform_key] = scan_fn
    if exec_fn is not None:
        _EXECUTORS[platform_key] = exec_fn


def register_placeholder(platform_key: str, display_name: str = "") -> None:
    """平台接入占位: 已接入巡检调度, 但该平台暂无重做/重考接口(只发现不执行)"""
    _dn = display_name or platform_key

    def _scan(cache, user, log):
        try:
            log(f"[可重做巡检] {_dn}: 该平台暂无重做/重考接口, 本次仅记录空结果")
        except Exception:
            pass
        return []

    _SCANNERS[platform_key] = _scan


def has_scanner(platform_key: str) -> bool:
    return platform_key in _SCANNERS


def mark_scanned(account: str) -> None:
    with _guard:
        _last_scan[account] = time.time()


def seconds_until_next(account: str) -> float:
    """距下次巡检还需多少秒(登录时已扫过则按 1h 窗口)"""
    with _guard:
        last = _last_scan.get(account, 0.0)
    left = SCAN_INTERVAL - (time.time() - last)
    return max(0.0, left)


def scan(platform_key: str, cache, user, log: Callable) -> List[RetakeItem]:
    fn = _SCANNERS.get(platform_key)
    if fn is None:
        return []
    try:
        return list(fn(cache, user, log) or [])
    except Exception as e:
        try:
            log(f"[可重做巡检] 扫描异常: {type(e).__name__}: {str(e)[:120]}")
        except Exception:
            pass
        return []


def filter_actionable(items: List[RetakeItem], rate_th: int,
                      full_sw: int = 0) -> List[RetakeItem]:
    """过滤出"未过期 & 有余量 & 得分未达标"的可执行项

    full_sw=1(满分也重做): 忽略得分判定, 只要有余量就执行。
    """
    out = []
    for it in items:
        if it.expired:
            continue
        if it.remaining == 0:
            continue
        if (not full_sw) and it.rate is not None and it.rate >= rate_th:
            continue
        out.append(it)
    return out


def run(platform_key: str, cache, user, log: Callable,
        execute: bool = True) -> Dict[str, Any]:
    """执行一轮巡检(扫描+按判定执行)。调用方负责 1h 节奏。

    :return: {found, actionable, executed, ok, failed, items}
    """
    acc = str(getattr(user, "account", "") or "")
    mark_scanned(acc)
    items = scan(platform_key, cache, user, log)
    cc = getattr(user, "courses_custom", None)
    try:
        rate_th = int(getattr(cc, "cx_retake_rate", 80) or 80)
    except Exception:
        rate_th = 80
    rate_th = max(1, min(100, rate_th))
    try:
        full_sw = int(getattr(cc, "cx_retake_full_sw", 0) or 0)
    except Exception:
        full_sw = 0
    act = filter_actionable(items, rate_th, full_sw)
    stats = {"found": len(items), "actionable": len(act),
             "executed": 0, "ok": 0, "failed": 0, "items": items}
    if not items:
        log("[可重做巡检] 未发现可重做候选(作业/章测/考试)")
        return stats
    expired_n = sum(1 for x in items if x.expired)
    full_n = sum(1 for x in items if (not x.expired) and x.remaining == 0)
    pass_n = sum(1 for x in items if (not x.expired) and x.remaining != 0
                 and (not full_sw) and x.rate is not None
                 and x.rate >= rate_th)
    log(f"[可重做巡检] 候选{len(items)}项 | 可执行{len(act)}项 "
        f"(过期跳过{expired_n}/无余量{full_n}/已达标{pass_n}"
        f"{('·满分也重做已开' if full_sw else '')})")
    for it in items:
        _mark = ("过期" if it.expired else
                 ("无余量" if it.remaining == 0 else
                  ("已达标" if ((not full_sw) and it.rate is not None
                             and it.rate >= rate_th)
                   else "可执行")))
        _score = ("" if it.rate is None
                  else f" 得分率{it.rate:.1f}%")
        _rem = ("" if it.remaining < 0 else f" 余量{it.remaining}次")
        log(f"[可重做巡检] [{it.course}][{it.kind}] {it.name} | "
            f"状态:{it.status}{_score}{_rem} => {_mark}")
    if not execute or not act:
        return stats
    ex = _EXECUTORS.get(platform_key)
    if ex is None:
        log(f"[可重做巡检] {platform_key} 平台暂不支持自动重做, "
            f"以上 {len(act)} 项仅记录(可按需手动处理)")
        return stats
    for it in act:
        stats["executed"] += 1
        try:
            ok = bool(ex(cache, user, it, log))
        except Exception as e:
            ok = False
            log(f"[可重做巡检] 执行异常: {type(e).__name__}: {str(e)[:100]}")
        stats["ok" if ok else "failed"] += 1
    log(f"[可重做巡检] 执行完成: 成功{stats['ok']} 失败{stats['failed']} "
        f"/ 尝试{stats['executed']}")
    return stats
