# -*- coding: utf-8 -*-
"""
智慧树数据模型与异常定义
移植自外部项目 zhihuishu_sdk(fuckzhs 的 models/course.py 与 core/exceptions.py),
按本项目风格精简, 并在命名上与各平台 cache 对齐(如 ZhsUserCache)。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from logic.core.models import UserCacheBase


# ============ 异常层次(移植自 SDK core/exceptions.py, 精简保留主流程所需) ============

class ZhsError(Exception):
    """智慧树模块所有自定义异常的基类"""


class ZhsAuthError(ZhsError):
    """认证失败(账号或密码错误、需要短信/额外验证等)"""


class ZhsCaptchaError(ZhsError):
    """服务端要求人机验证(验证码)"""


class ZhsAPIError(ZhsError):
    """接口返回非预期错误码"""


class ZhsTokenExpired(ZhsError):
    """Polymas Token 过期且无法自动刷新"""


# ============ 数据模型 ============

class CourseType(Enum):
    """智慧树课程类型(不同课程用不同 API 体系)"""
    HIKE = "hike"               # 共享课(SPOC)
    POLYMAS_AI = "polymas_ai"   # 新版 Polymas AI 课

    @classmethod
    def from_str(cls, s: str) -> "CourseType":
        """解析字符串为课程类型"""
        mapping = {"hike": cls.HIKE, "polymas_ai": cls.POLYMAS_AI}
        if s not in mapping:
            raise ValueError(f"Unknown course type: {s!r}")
        return mapping[s]


@dataclass
class ZhsCourse:
    """智慧树课程条目"""
    id: str = ""                                # 课程ID(courseId)
    name: str = ""                              # 课程名称
    course_type: CourseType = CourseType.HIKE   # 课程类型
    class_id: Optional[str] = None              # 班级ID(Polymas AI 课需要)


@dataclass
class ZhsUserCache(UserCacheBase):
    """智慧树用户缓存 - 持有登录后的 HTTP 会话"""
    session: Any = None                 # ManagedSession(登录后的会话)
    cas_user_id: str = ""               # CAS userId(用于 Polymas token 归属校验)


@dataclass
class StudyProgress:
    """课程学习进度汇总(用于日志与事件通知)"""
    total_videos: int = 0
    completed_videos: int = 0
    elapsed_seconds: float = 0.0

    def bump_total(self):
        """累计任务点总数"""
        self.total_videos += 1

    def bump_completed(self):
        """累计完成任务点数"""
        self.completed_videos += 1
