# -*- coding: utf-8 -*-
"""
通用数据模型 - 各平台共享的基类
"""
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from datetime import datetime


@dataclass
class UserCacheBase:
    """用户缓存基类 - 对应各平台的 UserCache"""
    pre_url: str = ""          # 平台前置 URL
    account: str = ""          # 账号
    password: str = ""         # 密码
    ip_proxy_sw: bool = False  # 是否开启 IP 代理
    proxy_ip: str = ""         # 代理 IP
    token: str = ""            # 会话 Token
    cookie_dict: Dict[str, str] = field(default_factory=dict)  # 会话 Cookie


@dataclass
class CourseBase:
    """课程基类"""
    id: str = ""
    name: str = ""


@dataclass
class NodeBase:
    """节点基类（视频/作业/考试等）"""
    id: str = ""
    name: str = ""
    progress: float = 0.0


@dataclass
class Question:
    """题目模型 - 用于作业/考试"""
    id: str = ""
    question_type: int = 0    # 题型：1单选 2多选 3判断 4填空 5简答 6名词解释 7论述 8连线
    title: str = ""           # 题目内容
    options: List[str] = field(default_factory=list)  # 选项
    answer: str = ""          # 答案
    correct_answer: str = ""  # 正确答案
    score: float = 0.0        # 分值


@dataclass
class WorkExamBase:
    """作业/考试基类"""
    id: str = ""
    name: str = ""
    node_id: str = ""
    course_id: str = ""
    score: float = 0.0
    questions: List[Question] = field(default_factory=list)
    answer_id: str = ""       # 答题记录 ID


@dataclass
class StudyResult:
    """学习提交结果"""
    success: bool = False
    msg: str = ""
    raw_response: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


def safe_json_parse(text: str) -> Optional[Dict]:
    """安全解析 JSON"""
    import json
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def json_get(data: Any, *keys, default=None) -> Any:
    """
    嵌套字典安全取值
    用法: json_get(data, "result", "data", "studyId")
    """
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
        if current is None:
            return default
    return current
