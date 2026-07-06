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
