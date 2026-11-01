# -*- coding: utf-8 -*-
"""
对象工具 - 对应 Go 项目的 ObjectUtils.go
提供 dataclass/对象 转 dict 等工具函数
"""
import json
from dataclasses import asdict, is_dataclass
from typing import Any


def struct_to_map(obj: Any) -> dict:
    """
    将 dataclass 实例或 SQLAlchemy 模型转为字典
    优先使用 to_dict() 方法，否则使用 dataclass asdict，最后用 __dict__
    """
    if obj is None:
        return {}

    # 如果有 to_dict 方法
    if hasattr(obj, 'to_dict') and callable(obj.to_dict):
        return obj.to_dict()

    # 如果是 dataclass
    if is_dataclass(obj):
        return asdict(obj)

    # SQLAlchemy 模型
    if hasattr(obj, '__table__'):
        result = {}
        for column in obj.__table__.columns:
            result[column.name] = getattr(obj, column.name, None)
        return result

    # 普通对象
    if hasattr(obj, '__dict__'):
        return dict(obj.__dict__)

    return {}


def obj_to_json(obj: Any, ensure_ascii: bool = False) -> str:
    """对象转 JSON 字符串"""
    return json.dumps(struct_to_map(obj), ensure_ascii=ensure_ascii, default=str)
