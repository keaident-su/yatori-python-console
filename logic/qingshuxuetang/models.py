# -*- coding: utf-8 -*-
"""青书学堂数据模型"""
from dataclasses import dataclass
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class QsxtUserCache(UserCacheBase):
    pre_url: str = "https://degree.qingshuxuetang.com"
    session_str: str = ""
    token: str = ""            # App端Authorization-QS令牌(2026-10-15)
    school_id: str = ""
    class_id: str = ""
    user_id: str = ""


@dataclass
class QsxtCourse(CourseBase):
    course_name: str = ""
    school_id: str = ""     # 2026-10-15 作业链App参数
    class_id: str = ""
    period_id: str = ""


@dataclass
class QsxtNode:
    id: str = ""
    node_name: str = ""
    node_type: str = ""  # video / material
    progress: float = 0.0
    total_time: int = 0
    studied_time: int = 0
    course_id: str = ""
    chapter_id: str = ""


@dataclass
class QsxtWork:
    id: str = ""
    title: str = ""
    node_id: str = ""
    course_id: str = ""
    score: float = 0.0
