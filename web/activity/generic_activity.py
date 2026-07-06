# -*- coding: utf-8 -*-
"""
通用 Activity - 为无专属 Web Activity 的平台提供统一入口
支持：ENAEA / CQIE / KETANGX / WELEARN / ICVE / QSXT / HQKJ
通过 importlib 动态加载各平台的 part 模块
"""
import importlib
import threading
from typing import Optional, List, Any

from config.config import User, Setting
from web.activity.base_activity import UserActivityBase
from utils.log import log_print, INFO, Green, White, Red, Default, Purple, Yellow, BoldRed

# 平台 → 模块路径映射
_PLATFORM_MODULE_MAP = {
    "ENAEA":   "logic.enaea.part",
    "CQIE":    "logic.cqie.part",
    "KETANGX": "logic.ketangx.part",
    "WELEARN": "logic.welearn.part",
    "ICVE":    "logic.icve.part",
    "QSXT":    "logic.qingshuxuetang.part",
    "HQKJ":    "logic.haiqikeji.part",
}

# 平台显示名
_PLATFORM_DISPLAY = {
    "ENAEA":   "学习公社",
    "CQIE":    "重庆工程学院",
    "KETANGX": "码上研训",
    "WELEARN": "WeLearn",
    "ICVE":    "智慧职教",
    "QSXT":    "青书学堂",
    "HQKJ":    "海旗科技",
}


class GenericActivity(UserActivityBase):
    """通用平台活动 - 复用各平台的 part 模块实现登录与刷课"""

    def __init__(self, user: User = None, platform_type: str = ""):
        super().__init__(user)
        self._platform_type = platform_type
        self._display_name = _PLATFORM_DISPLAY.get(
            platform_type, platform_type)
        self._part_module = None
        self._caches: List[Any] = []
        self._brush_thread: Optional[threading.Thread] = None

    def _load_part_module(self):
        """懒加载平台 part 模块"""
        if self._part_module is None:
            module_path = _PLATFORM_MODULE_MAP.get(self._platform_type)
            if not module_path:
                return None
            self._part_module = importlib.import_module(module_path)
        return self._part_module

    def login(self) -> Optional[Exception]:
        """调用平台 part.user_login_operation 登录"""
        mod = self._load_part_module()
        if not mod:
            return Exception(f"未知平台类型: {self._platform_type}")

        try:
            from config.config import JSONDataForConfig
            # 构造单用户 JSONDataForConfig
            cfg = JSONDataForConfig()
            cfg.users = [self.user]

            users = mod.filter_account(cfg)
            if not users:
                return Exception(f"账号 {self.user.account} 不属于平台 {self._display_name}")

            self._caches = mod.user_login_operation(users)
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Green, f"{self._display_name} 登录成功")
            return None
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, White, "] ",
                      Red, f"{self._display_name} 登录失败: {e}")
            return e

    def start(self) -> Optional[Exception]:
        """启动刷课"""
        if not self._caches:
            err = self.login()
            if err:
                return err

        if self.is_running:
            return Exception("刷课已在运行中")

        self.is_running = True
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Purple, f"{self._display_name} 刷课已启动")

        self._brush_thread = threading.Thread(
            target=self._brush_loop, daemon=True)
        self._brush_thread.start()
        return None

    def stop(self) -> Optional[Exception]:
        """停止刷课"""
        self.is_running = False
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Yellow, f"{self._display_name} 刷课已停止")
        return None

    def pull_course_list(self) -> List[dict]:
        """
        拉取课程列表
        通用平台不单独实现课程拉取 API，返回提示信息
        """
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Yellow, f"{self._display_name} 暂不支持Web端拉取课程列表，请使用刷课模式")
        return []

    def _brush_loop(self):
        """后台刷课主循环"""
        try:
            mod = self._load_part_module()
            if not mod:
                return
            setting = Setting()
            users = [self.user]
            mod.run_brush_operation(setting, users, self._caches)
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      BoldRed, f"{self._display_name} 刷课异常: {e}")
        finally:
            self.is_running = False
