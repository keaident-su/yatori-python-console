# -*- coding: utf-8 -*-
"""
学习公社数据模型
"""
from dataclasses import dataclass, field
from typing import List, Optional
from logic.core.models import UserCacheBase, CourseBase


@dataclass
class EnaeaUserCache(UserCacheBase):
    """学习公社用户缓存"""
    pre_url: str = "https://study.enaea.cn"
    session_id: str = ""
    circle_id: str = ""


@dataclass
class EnaeaProject:
    """学习公社项目"""
    circle_id: str = ""
    cluster_name: str = ""


@dataclass
class EnaeaCourse(CourseBase):
    """学习公社课程"""
    title_tag: str = ""
    course_title: str = ""
    course_id: str = ""
    circle_id: str = ""


@dataclass
class EnaeaVideo:
    """学习公社视频"""
    id: str = ""
    title_tag: str = ""
    course_name: str = ""
    course_content_str: str = ""
    study_progress: float = 0.0
    course_id: str = ""
    content_id: str = ""
    cc_video_id: str = ""
