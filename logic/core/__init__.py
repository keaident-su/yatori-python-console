# -*- coding: utf-8 -*-
"""
核心模块 - 共享的 HTTP 客户端、数据模型、AI 答题、外置题库、多答题源引擎
"""
from logic.core.http_client import HttpClient
from logic.core.models import UserCacheBase, CourseBase, NodeBase
from logic.core.ai_client import AIClient, ai_check, ai_problem_message
from logic.core.external_que import ExternalQueClient, check_api_que_request
from logic.core.tiku_client import EmmcyTikuClient, AxeTikuClient
from logic.core.answer_engine import (
    AnswerEngine, AnswerSource, LocalTikuCache,
    configure_answer_engine, answer_query, answer_query_detail,
    run_startup_token_check,
)

__all__ = [
    "HttpClient",
    "UserCacheBase", "CourseBase", "NodeBase",
    "AIClient", "ai_check", "ai_problem_message",
    "ExternalQueClient", "check_api_que_request",
    "EmmcyTikuClient", "AxeTikuClient",
    "AnswerEngine", "AnswerSource", "LocalTikuCache",
    "configure_answer_engine", "answer_query", "answer_query_detail",
    "run_startup_token_check",
]
