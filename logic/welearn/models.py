# -*- coding: utf-8 -*-
"""WeLearn数据模型"""
from dataclasses import dataclass
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class WeLearnUserCache(UserCacheBase):
    pre_url: str = "https://welearn.sflep.com"
    uid: str = ""
    session_str: str = ""


@dataclass
class WeLearnCourse(CourseBase):
    course_name: str = ""
    study_plan_id: str = ""


@dataclass
class WeLearnNode:
    id: str = ""
    node_name: str = ""
    progress: float = 0.0
    total_time: int = 0
    studied_time: int = 0
    course_id: str = ""
    scorm_id: str = ""
