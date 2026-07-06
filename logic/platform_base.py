# -*- coding: utf-8 -*-
"""
平台处理器抽象基类 - 新增平台只需继承此类并注册
对应 Go 项目中各 logic/xxx/ 目录的统一抽象
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from config.config import User, Setting


class PlatformHandler(ABC):
    """
    平台处理器抽象基类
    每个平台需实现以下方法：
    - platform_type: 平台类型标识符（如 "XUEXITONG"）
    - filter_account(): 从配置中过滤出本平台账号
    - login(): 登录并返回用户缓存列表
    - run_brush(): 执行刷课操作
    """

    @property
    @abstractmethod
    def platform_type(self) -> str:
        """平台类型标识符"""
        ...

    @abstractmethod
    def filter_account(self, users: List[User]) -> List[User]:
        """从配置用户列表中过滤出属于本平台的账号"""
        ...

    @abstractmethod
    def login(self, users: List[User]) -> List[Any]:
        """
        批量登录用户
        :param users: 本平台用户列表
        :return: 登录后的用户缓存列表
        """
        ...

    @abstractmethod
    def run_brush(self, setting: Setting, users: List[User], user_caches: List[Any]):
        """
        执行刷课操作
        :param setting: 全局设置
        :param users: 本平台用户列表
        :param user_caches: 登录后的用户缓存列表
        """
        ...


# ============ 平台注册器 ============

_platform_registry: Dict[str, PlatformHandler] = {}


def register_platform(handler: PlatformHandler):
    """注册平台处理器"""
    _platform_registry[handler.platform_type] = handler


def get_platform_handler(platform_type: str) -> Optional[PlatformHandler]:
    """获取平台处理器"""
    return _platform_registry.get(platform_type)


def get_all_platform_handlers() -> Dict[str, PlatformHandler]:
    """获取所有已注册的平台处理器"""
    return _platform_registry.copy()
