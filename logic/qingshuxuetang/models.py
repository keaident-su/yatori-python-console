# -*- coding: utf-8 -*-
"""青书学堂数据模型"""
from dataclasses import dataclass
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class QsxtUserCache(UserCacheBase):
    pre_url: str = "https://degree.qingshuxuetang.com"
    session_str: str = ""


@dataclass
class QsxtCourse(CourseBase):
    course_name: str = ""


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
