# -*- coding: utf-8 -*-
"""
核心模块 - 共享的 HTTP 客户端、数据模型、AI 答题、外置题库
"""
from logic.core.http_client import HttpClient
from logic.core.models import UserCacheBase, CourseBase, NodeBase
from logic.core.ai_client import AIClient, ai_check, ai_problem_message
from logic.core.external_que import ExternalQueClient, check_api_que_request

__all__ = [
    "HttpClient",
    "UserCacheBase", "CourseBase", "NodeBase",
    "AIClient", "ai_check", "ai_problem_message",
    "ExternalQueClient", "check_api_que_request",
]
