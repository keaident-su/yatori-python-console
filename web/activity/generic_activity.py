# -*- coding: utf-8 -*-
"""
通用 Activity - 为无专属 Web Activity 的平台提供统一入口
支持：ENAEA / CQIE / KETANGX / WELEARN / ICVE / QSXT / HQKJ
通过 importlib 动态加载各平台的 part 模块
"""
import importlib
import threading
import time
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
    "WEBAN":   "logic.weban.part",
    "ZHIHUISHU": "logic.zhihuishu.part",
    "DZYX": "logic.dazhongyunxue.part",
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
    "WEBAN":   "安全微伴",
    "ZHIHUISHU": "智慧树",
    "DZYX": "大众云学",
    "XUEXITONG": "学习通",
    "YINGHUA": "英华学堂",
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
        """拉取课程列表+进度

        分发到平台 part 模块的 web_course_list(cache, user) 实现;
        平台未实现时返回空列表并提示。
        """
        mod = self._load_part_module()
        fn = getattr(mod, "web_course_list", None) if mod else None
        if fn is None:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Yellow, f"{self._display_name} 暂不支持Web端拉取课程列表，请使用刷课模式")
            return []
        if not self._caches:
            err = self.login()
            if err:
                return []
        cache = self._caches[0] if self._caches else None
        try:
            return fn(cache, self.user) or []
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Red, f"拉取课程列表失败: {e}")
            return []

    def course_detail_stat(self, course_id: str) -> dict:
        """课程详情统计(作业/考试清单, 2026-10-17 全平台)

        分发到平台 part 模块的 web_course_detail_stat(cache, user, course_id);
        平台未实现时返回 supported:false (前端显示"暂不支持")。
        """
        mod = self._load_part_module()
        fn = getattr(mod, "web_course_detail_stat", None) if mod else None
        if fn is None:
            return {"supported": False}
        if not self._caches:
            err = self.login()
            if err:
                return {"supported": False}
        cache = self._caches[0] if self._caches else None
        try:
            return fn(cache, self.user, str(course_id)) or {"supported": False}
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Red, f"课程详情统计失败: {e}")
            return {"supported": False}

    def _retake_log(self):
        """[V3.2.3] 可重做巡检专用日志"""
        def _f(m):
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      str(m))
        return _f

    def _brush_loop(self):
        """后台刷课主循环(含 v3.2.3 可重做巡检守护: 登录即扫 + 每小时一次)"""
        _crashed = False  # [V3.2.5] 异常崩溃标记(供启动监督器判断是否自动重启)
        try:
            mod = self._load_part_module()
            if not mod:
                return
            from web.service.user_service import load_web_setting
            from logic.core import retake_scanner as _rt_scan
            _pkey = self._platform_type
            _first_scan = True
            while self.is_running:
                setting = load_web_setting()
                mod.run_brush_operation(setting, [self.user], self._caches)
                if not self.is_running or not _rt_scan.has_scanner(_pkey):
                    break
                # [V3.2.3] 可重做巡检: 登录后立即一次, 之后每 1 小时一次(守护循环)
                try:
                    _cache0 = (self._caches or [None])[0]
                    if _cache0 is None:
                        break
                    if _first_scan:
                        _rt_scan.run(_pkey, _cache0, self.user,
                                     self._retake_log(), execute=True)
                        _first_scan = False
                    _left = _rt_scan.seconds_until_next(self.user.account)
                    while _left > 0 and self.is_running:
                        time.sleep(min(30, _left))
                        _left -= 30
                    if not self.is_running:
                        break
                    _rt_scan.run(_pkey, _cache0, self.user,
                                 self._retake_log(), execute=True)
                except Exception as _rse:
                    log_print(INFO, "[", Green, self.user.account, Default,
                              "] ", Red, f"巡检异常: {str(_rse)[:100]}")
                    break
        except Exception as e:
            _crashed = True
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      BoldRed, f"{self._display_name} 刷课异常: {e}")
        finally:
            self.is_running = False
            # [V3.2.5] 通知启动监督器: 崩溃则可能自动重启(守护自动重启);
            # 正常完成/用户停止则清除期望态, 不重启
            try:
                from web.service import start_supervisor as _sup
                _sup.on_exit(getattr(self.user, "uid", ""), self.user.account,
                             crashed=_crashed)
            except Exception:
                pass
