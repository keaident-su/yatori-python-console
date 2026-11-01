# -*- coding: utf-8 -*-
"""
视图对象 - 对应 Go 项目的 entity/vo/ 目录
包含请求和响应的数据结构
"""
from dataclasses import dataclass, field
from typing import Any, Optional, List


@dataclass
class Response:
    """统一响应结构"""
    code: int = 200
    message: str = ""
    data: Any = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "data": self.data}


@dataclass
class AddAccountRequest:
    """添加账号请求"""
    account_type: str = ""
    url: str = ""
    account: str = ""
    password: str = ""


@dataclass
class DeleteAccountRequest:
    """删除账号请求"""
    uid: str = ""
    account_type: str = ""
    url: str = ""
    account: str = ""
    password: str = ""


@dataclass
class AccountLoginCheckRequest:
    """账号登录检测请求"""
    uid: str = ""
    account_type: str = ""
    account: str = ""
    password: str = ""


@dataclass
class CourseInformResponse:
    """课程信息响应"""
    course_id: str = ""
    course_name: str = ""
    instructor: str = ""
    progress: float = 0.0

    def to_dict(self) -> dict:
        return {
            "courseId": self.course_id,
            "courseName": self.course_name,
            "instructor": self.instructor,
            "progress": self.progress,
        }
