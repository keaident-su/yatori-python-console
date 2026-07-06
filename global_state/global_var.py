# -*- coding: utf-8 -*-
"""
全局状态管理 - 对应 Go 项目的 global/global.go
管理全局数据库引用、平台类型映射、用户活动映射
"""
from typing import Dict, Optional, Any

# 全局数据库会话工厂
global_session_factory = None

# 平台类型中文字符串映射
ACCOUNT_TYPE_STR: Dict[str, str] = {
    "XUEXITONG": "学习通",
    "YINGHUA": "英华学堂",
    "CANGHUI": "仓辉实训",
    "ENAEA": "学习公社",
    "CQIE": "重庆工程学院",
    "KETANGX": "码上研训",
    "ICVE": "智慧职教",
    "QSXT": "青书学堂",
    "WELEARN": "WeLearn",
    "HQKJ": "海旗科技",
}

# 用户活动映射 (key: uid)
_user_activity_map: Dict[str, Any] = {}


def get_user_activity(uid: str) -> Optional[Any]:
    """获取用户活动"""
    return _user_activity_map.get(uid)


def put_user_activity(uid: str, activity: Any):
    """添加/更新用户活动"""
    _user_activity_map[uid] = activity


def remove_user_activity(uid: str):
    """移除用户活动"""
    _user_activity_map.pop(uid, None)
