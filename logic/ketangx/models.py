# -*- coding: utf-8 -*-
"""码上研训数据模型"""
from dataclasses import dataclass
from typing import Optional
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class KetangxUserCache(UserCacheBase):
    pre_url: str = "https://openapiv5.ketangx.com"
    session_id: str = ""


@dataclass
class KetangxCourse(CourseBase):
    title: str = ""


@dataclass
class KetangxNode:
    id: str = ""
    title: str = ""
    type: str = ""
    is_complete: bool = False
    course_id: str = ""
