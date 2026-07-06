# -*- coding: utf-8 -*-
"""
英华学堂数据模型 - 对应 Go 项目的 yatori-go-core 英华相关结构体
"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from logic.core.models import UserCacheBase, CourseBase


@dataclass
class YingHuaUserCache(UserCacheBase):
    """英华用户缓存 - 对应 YingHuaUserCache"""
    ver_code: str = ""      # 验证码
    cookie: str = ""        # 验证码用的 session cookie
    sign: str = ""          # 签名


@dataclass
class YingHuaCourse(CourseBase):
    """英华课程 - 对应 YingHuaCourse"""
    mode: int = 0              # 课程模式
    start_date: Optional[datetime] = None  # 开始时间
    end_date: Optional[datetime] = None    # 结束时间
    progress: float = 0.0     # 学习进度
    video_count: int = 0      # 视频总数
    video_learned: int = 0    # 已学习视频数量


@dataclass
class YingHuaNode:
    """英华节点 - 对应 YingHuaNode"""
    id: str = ""
    course_id: str = ""
    name: str = ""
    video_duration: int = 0    # 视频时长（秒）
    node_lock: int = 0         # 解锁状态
    unlock_time: Optional[datetime] = None  # 解锁时间
    progress: float = 0.0      # 观看进度（0-100）
    viewed_duration: int = 0   # 已观看时长
    state: int = 0             # 视频状态
    error_code: int = 0        # 错误码
    error_message: str = ""    # 错误信息
    tab_video: bool = False    # 是否有视频
    tab_file: bool = False     # 是否有文件
    tab_vote: bool = False     # 是否有投票
    tab_work: bool = False     # 是否有作业
    tab_exam: bool = False     # 是否有考试


@dataclass
class YingHuaExam:
    """英华考试 - 对应 YingHuaExam"""
    id: str = ""
    exam_id: str = ""
    node_id: str = ""
    course_id: str = ""
    title: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limited_time: float = 0.0  # 考试限时
    score: float = 0.0         # 试卷总分


@dataclass
class YingHuaWork:
    """英华作业 - 对应 YingHuaWork"""
    id: str = ""
    work_id: str = ""
    node_id: str = ""
    course_id: str = ""
    title: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    score: float = 0.0
    allow: int = 0      # 允许做题次数
    frequency: int = 0


@dataclass
class YingHuaExamTopic:
    """英华考试题目 - 对应 YingHuaExamTopic"""
    answer_id: str = ""
    type: str = ""      # 单选/多选/判断/填空/简答
    question: "YingHuaQuestion" = None


@dataclass
class YingHuaQuestion:
    """英华题目 - 对应 YingHuaQuestion"""
    id: str = ""
    title: str = ""
    answers: List[str] = field(default_factory=list)  # 选项标识 A/B/C/D
    options: List[str] = field(default_factory=list)  # 选项内容
