# -*- coding: utf-8 -*-
"""学习通"模式矩阵 + remark 任务DSL"参考层
参考逆向 mogo v2.3 recovered/xxt_policy.py(外部契约重建), 用于:
  - 统一 19 种刷课模式 -> feature 集(便于按需只做某类任务)
  - 解析 remark 简易语法的任务指令(name(value)|flag), 含 考试码(code)
本模块为纯数据/解析工具, 不改现有逻辑; 现有 coursesCustom 仍为配置源。
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

XXT_MODE_NAMES: Tuple[str, ...] = (
    "学习通", "学习通(积分课)", "学习通(单课件)", "学习通(章测)",
    "学习通(单考试)", "学习通(考试列表)", "学习通(单作业)", "学习通(收信箱)",
    "学习通(学习次数)", "学习通(阅读)", "学习通(讨论)", "学习通(复习模式)",
    "学习通(考试采集填充)", "学习通(考试列表题库采集)",
    "学习通(考试列表考试采集填充)", "学习通(作业采集填充)",
    "学习通(章测采集填充)", "学习通(题库采集)", "学习通(题库暴力采集)",
)

XXT_MODE_FEATURES: Dict[str, Tuple[str, ...]] = {
    "学习通": ("courseware", "assignments", "exams", "chapter_tests", "discussions",
            "interactions", "study_count", "progress_timing", "score_management",
            "face_or_locked_content"),
    "学习通(积分课)": ("courseware", "assignments", "exams", "chapter_tests",
                 "study_count", "progress_timing", "score_management"),
    "学习通(单课件)": ("courseware", "chapter_tests", "discussions", "interactions",
                 "study_count", "progress_timing"),
    "学习通(章测)": ("chapter_tests",),
    "学习通(单考试)": ("exams", "score_management"),
    "学习通(考试列表)": ("exams", "progress_timing", "score_management"),
    "学习通(单作业)": ("assignments", "score_management"),
    "学习通(收信箱)": ("assignments", "exams", "score_management"),
    "学习通(学习次数)": ("study_count",),
    "学习通(阅读)": ("courseware",),
    "学习通(讨论)": ("question_bank",),
    "学习通(复习模式)": ("courseware", "chapter_tests", "study_count", "progress_timing"),
    "学习通(考试采集填充)": ("exams", "question_bank", "score_management"),
    "学习通(考试列表题库采集)": ("exams", "question_bank"),
    "学习通(考试列表考试采集填充)": ("exams", "question_bank", "score_management"),
    "学习通(作业采集填充)": ("assignments", "question_bank", "score_management"),
    "学习通(章测采集填充)": ("chapter_tests", "question_bank"),
    "学习通(题库采集)": ("assignments", "exams", "chapter_tests", "question_bank"),
    "学习通(题库暴力采集)": ("exams", "question_bank"),
}


def features_for(mode: str) -> Tuple[str, ...]:
    return XXT_MODE_FEATURES.get(mode, XXT_MODE_FEATURES["学习通"])


def parse_remark(remark: str) -> Dict[str, object]:
    """解析 remark: `名称(值)|flag` -> dict。
    例: '视频速度(10)|学习次数(30)|考试码(EA4123)|不做考试|章测无视对错'
    -> {'视频速度':'10','学习次数':'30','考试码':'EA4123','不做考试':True,'章测无视对错':True}
    """
    out: Dict[str, object] = {}
    for raw in (remark or "").split("|"):
        item = raw.strip()
        if not item or item == "无":
            continue
        m = re.fullmatch(r"(.+?)\(([^()]*)\)", item)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
        else:
            out[item] = True
    return out


def exam_code_from_remark(remark: str) -> str:
    """从 remark 抽取考试码(键名: 考试码 / 考试码(值))."""
    d = parse_remark(remark)
    v = d.get("考试码")
    return str(v) if isinstance(v, str) else ""
