# -*- coding: utf-8 -*-
"""海旗科技数据模型"""
from dataclasses import dataclass, field
from typing import List
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class HqkjUserCache(UserCacheBase):
    """海旗科技用户缓存"""
    pre_url: str = ""
    session_str: str = ""
    user_id: str = ""
    token: str = ""       # [V3.2.0] 登录响应 data 即为 Token(对齐 core HqkjLoginAction)
    school_id: str = ""   # [V3.2.0] selectdomain 返回的学校 id


@dataclass
class HqkjCourse(CourseBase):
    course_name: str = ""


@dataclass
class HqkjNode:
    id: str = ""
    node_name: str = ""
    progress: float = 0.0
    total_time: int = 0
    studied_time: int = 0
    course_id: str = ""
    video_id: str = ""


@dataclass
class HqkjWork:
    id: str = ""
    title: str = ""
    node_id: str = ""
    course_id: str = ""
    score: float = 0.0


@dataclass
class HqkjExam:
    id: str = ""
    title: str = ""
    node_id: str = ""
    course_id: str = ""
    score: float = 0.0
