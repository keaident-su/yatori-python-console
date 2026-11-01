# -*- coding: utf-8 -*-
"""
Activity 抽象基类 - 对应 Go 项目的 web/activity/UserActivity.go
定义用户活动的统一接口（登录/启动/停止/缓存管理）
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

from config.config import User


class Activity(ABC):
    """用户活动抽象基类"""

    @abstractmethod
    def login(self) -> Optional[Exception]:
        """登录"""
        ...

    @abstractmethod
    def start(self) -> Optional[Exception]:
        """启动刷课"""
        ...

    @abstractmethod
    def stop(self) -> Optional[Exception]:
        """停止刷课"""
        ...

    @abstractmethod
    def get_user_cache(self) -> Any:
        """获取用户缓存"""
        ...

    @abstractmethod
    def set_user(self, user: User):
        """设置用户配置"""
        ...

    @abstractmethod
    def get_user(self) -> User:
        """获取用户配置"""
        ...


class UserActivityBase(Activity):
    """用户活动基类 - 提供通用的状态管理"""

    def __init__(self, user: User = None):
        self.user: User = user or User()
        self.is_running: bool = False
        self.user_cache: Any = None

    def set_user(self, user: User):
        self.user = user

    def get_user(self) -> User:
        return self.user

    def get_user_cache(self) -> Any:
        return self.user_cache
