# -*- coding: utf-8 -*-
"""智慧职教数据模型"""
from dataclasses import dataclass
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class IcveUserCache(UserCacheBase):
    pre_url: str = "https://zyk.icve.com.cn"
    cookie_str: str = ""
    is_cookie_login: bool = False


@dataclass
class IcveCourse(CourseBase):
    course_name: str = ""


@dataclass
class IcveNode:
    id: str = ""
    node_name: str = ""
    progress: float = 0.0
    total_time: int = 0
    course_id: str = ""
    audio_video_id: str = ""
