# -*- coding: utf-8 -*-
"""[V3.2.4 mogo对齐] 智慧树课程"平时分"自动补充

玩法对齐 mogo: 智慧树(先刷后补平时分 / 单独补平时分) —— 每天自动补平时分。

实测接口(StuOnlineClient, stuonline 域 form POST 直连 2026-10-27):
- load_stu_habit  -> 课程起止(courseStartTime/courseEndTime) + 平时分相关(未结算时为 null)
- load_learn_report -> 成绩报告(课件/作业/考试/见面课分项; 未结算时多字段 null)
- load_course_forum -> qaStatisticsMap.myInteractionDto.{validAnswerAmount/validQuestionAmount/...}
                       我的互动统计(讨论区与 creditqa 问答域口径可能不同, null 时视为未知)

补分策略(安全幂等):
1) 先读取 stats 快照(habit/forum), 记日志;
2) 若互动数据未知或有效回答数 < 目标(默认 30), 直接调用 qa.run_course_qa 补讨论
   - qa 自带: 已回答过去重(dup)/1010 限流提前停/单次上限, 重复运行安全;
3) 返回 {habit_ok, forum_answer, qa: {...}, note} 供上层日志/通知。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _safe_int(v, d: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return d


def run_daily_bonus(cache, course, log=None, qa_limit: int = 35,
                    target_answers: int = 30) -> Dict[str, Any]:
    """智慧树平时分自动补充(互动优先)。

    :param cache: 登录缓存
    :param course: 课程对象(需 id / recruit_id / name)
    :param log: 日志对象(.info/.success/.warning)
    :param qa_limit: 单次 qa 补答上限(默认 35, 低于平台日限流)
    :param target_answers: 有效回答目标数(默认 30, 达到即跳过补答)
    """
    _info = log.info if (log is not None and hasattr(
        log, "info")) else (lambda *a, **k: None)
    _ok = log.success if (
        log is not None and hasattr(log, "success")) else _info
    stats: Dict[str, Any] = {"habit_ok": False, "forum_answer": None,
                             "qa": None, "note": ""}
    try:
        from logic.zhihuishu.api import StuOnlineClient
    except Exception as e:
        stats["note"] = f"依赖缺失: {e}"
        return stats
    cid = str(getattr(course, "id", "") or "")
    rid = str(getattr(course, "recruit_id", "") or "")
    cname = str(getattr(course, "name", "") or "")
    try:
        api = StuOnlineClient(cache.session)
    except Exception as e:
        stats["note"] = f"客户端初始化失败: {e}"
        return stats
    # 1) 快照: 学习习惯(起止/平时分) + 互动统计
    habit = {}
    forum = {}
    try:
        habit = api.load_stu_habit(rid, cid) or {}
        stats["habit_ok"] = bool(
            habit.get("courseStartTime") or habit.get("recruitId"))
    except Exception as e:
        _info(f"[平时分] habit 读取失败: {str(e)[:100]}")
    try:
        forum = api.load_course_forum(rid, cid) or {}
        dto = ((forum.get("qaStatisticsMap") or {}).get(
            "myInteractionDto") or {})
        va = dto.get("validAnswerAmount")
        stats["forum_answer"] = (None if va is None else _safe_int(va))
        _info(f"[平时分] 课程【{cname}】快照: 有效回答={stats['forum_answer']} "
              f"有效提问={dto.get('validQuestionAmount')} "
              f"课程期={habit.get('courseStartTime')}~{habit.get('courseEndTime')}")
    except Exception as e:
        _info(f"[平时分] forum 读取失败: {str(e)[:100]}")
    # 2) 互动补答(未知或未达标时)
    cur = stats["forum_answer"]
    need = (cur is None) or (cur < target_answers)
    if not need:
        stats["note"] = f"互动已达标({cur}>={target_answers}), 跳过补答"
        _ok(f"[平时分] 课程【{cname}】{stats['note']}")
        return stats
    try:
        from logic.zhihuishu.qa import run_course_qa
        qa = run_course_qa(cache, course, log=log, limit=qa_limit)
        stats["qa"] = qa
        _ok(f"[平时分] 课程【{cname}】互动补答: 成功{qa.get('ok', 0)} "
            f"重复{qa.get('dup', 0)} 失败{qa.get('fail', 0)} "
            f"限流{qa.get('limited', 0)} {qa.get('note', '')}")
    except Exception as e:
        stats["note"] = f"补答异常: {str(e)[:120]}"
        _info(f"[平时分] {stats['note']}")
    return stats
