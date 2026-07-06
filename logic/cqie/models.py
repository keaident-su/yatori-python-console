# -*- coding: utf-8 -*-
"""重庆工程学院数据模型"""
from dataclasses import dataclass
from typing import Optional
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class CqieUserCache(UserCacheBase):
    """CQIE用户缓存"""
    pre_url: str = "https://jxjy.cqie.edu.cn"
    session_id: str = ""
    study_id: str = ""


@dataclass
class CqieCourse(CourseBase):
    """CQIE课程"""
    course_name: str = ""
    course_id: str = ""


@dataclass
class CqieVideo:
    """CQIE视频"""
    id: str = ""
    video_name: str = ""
    time_length: int = 0
    study_time: int = 0
    study_id: str = ""
