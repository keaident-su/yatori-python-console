# -*- coding: utf-8 -*-
"""运行时状态通道(2026-10-22 新增)

刷课流程埋点 -> 内存状态 -> 前端(进度大屏/控制台)轮询展示:
  1. 当前阶段/课程/任务点     (set_stage/set_task)
  2. 考试进行中答题进度        (set_exam: done/total)
  3. 考试gate预约等待提示      (add_gate: 计划时间+原因)

设计要点:
  · 键=account(逻辑层只有account); 接口层 uid->account 后读取
  · 进程内内存dict(不落盘, 重启即清空——状态本就是瞬时的)
  · 线程安全: 单锁保护; 前端只读快照
"""
import threading
import time
from typing import Dict, List, Optional

_LOCK = threading.Lock()
_RT: Dict[str, dict] = {}   # account -> state


def _now_ms() -> int:
    return int(time.time() * 1000)


def update(account: str, **kw) -> None:
    """通用合并更新"""
    if not account:
        return
    with _LOCK:
        st = _RT.setdefault(str(account), {})
        st.update(kw)
        st["updatedAt"] = _now_ms()


def set_stage(account: str, stage: str, course: str = "",
              task: str = "") -> None:
    """阶段切换(课程学习/拓展阅读/增加时长/考试/结束...)"""
    update(account, stage=stage, course=course, taskPoint=task)


def set_task(account: str, course: str, task_point: str,
             task_type: str = "") -> None:
    """当前正在执行的任务点"""
    update(account, stage="学习任务点", course=course,
           taskPoint=task_point, taskType=task_type)


def set_exam(account: str, course: str, done: int, total: int,
             status: str = "答题中") -> None:
    """考试进行中答题进度(done/total)"""
    update(account, stage="考试", course=course,
           exam={"course": course, "done": int(done),
                 "total": int(total), "status": status})


def clear_exam(account: str) -> None:
    update(account, exam=None)


def add_gate(account: str, course: str, wait_desc: str,
             reason: str = "") -> None:
    """考试gate预约/等待登记(如 次日07:03 后自动进入)"""
    if not account:
        return
    with _LOCK:
        st = _RT.setdefault(str(account), {})
        gates: List[dict] = [g for g in (st.get("examGates") or [])
                             if g.get("course") != course]
        gates.append({"course": course, "waitDesc": wait_desc,
                      "reason": reason, "ts": _now_ms()})
        st["examGates"] = gates
        st["updatedAt"] = _now_ms()


def clear_gate(account: str, course: Optional[str] = None) -> None:
    """解除gate(考完/放弃); course=None 清全部"""
    if not account:
        return
    with _LOCK:
        st = _RT.get(str(account))
        if not st:
            return
        if course is None:
            st["examGates"] = []
        else:
            st["examGates"] = [g for g in (st.get("examGates") or [])
                               if g.get("course") != course]
        st["updatedAt"] = _now_ms()


def finish(account: str) -> None:
    """账号刷课流程结束"""
    update(account, stage="已结束", taskPoint="", exam=None,
           resting=0, restResumeAt=0, restResumeHm="")


def get(account: str) -> dict:
    """读取状态快照(前端接口用)"""
    with _LOCK:
        st = _RT.get(str(account)) or {}
        return dict(st)
