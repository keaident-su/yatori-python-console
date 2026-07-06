# -*- coding: utf-8 -*-
"""
英华学堂 Activity - 对应 Go 项目的 web/activity/YinghuaActivity.go
实现英华学堂平台的用户活动（登录/刷课/课程拉取）
"""
from utils.log import log_print, INFO, Green, White, Red, Default, Purple, Yellow
from config.config import User
from typing import Optional, List
import threading
from typing import Optional, List, Any

from config.config import User, Setting
from web.activity.base_activity import UserActivityBase
from logic.yinghua.models import YingHuaUserCache
from logic.yinghua import aggregation as yinghua_agg
from logic.yinghua import api as yinghua_api
from utils.log import log_print, INFO, Green, White, Red, Default, Purple, Yellow, BoldRed


class YingHuaActivity(UserActivityBase):
    """英华学堂活动 - Web 模式下的用户操作入口"""

    def __init__(self, user: User = None):
        super().__init__(user)
        self._cache: Optional[YingHuaUserCache] = None
        self._brush_thread: Optional[threading.Thread] = None

    def login(self) -> Optional[Exception]:
        """英华学堂登录 - 调用 aggregation 层的登录动作"""
        if not self.user.account or not self.user.url:
            return Exception("账号或URL为空")

        cache = YingHuaUserCache(
            pre_url=self.user.url,
            account=self.user.account,
            password=self.user.password,
        )
        err = yinghua_agg.ying_hua_login_action(cache)
        if err:
            log_print(INFO, "[", Green, self.user.account, White, "] ",
                      Red, f"英华学堂登录失败: {err}")
            return err

        # 启动保活线程
        self._cache = cache
        keep_alive_thread = threading.Thread(
            target=self._keep_alive_loop, args=(cache,), daemon=True)
        keep_alive_thread.start()

        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Green, "英华学堂登录成功")
        return None

    def start(self) -> Optional[Exception]:
        """启动刷课 - 在后台线程运行刷课操作"""
        if self._cache is None:
            err = self.login()
            if err:
                return err

        if self.is_running:
            return Exception("刷课已在运行中")

        self.is_running = True
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Purple, "英华学堂刷课已启动")

        self._brush_thread = threading.Thread(
            target=self._brush_loop, daemon=True)
        self._brush_thread.start()
        return None

    def stop(self) -> Optional[Exception]:
        """停止刷课"""
        self.is_running = False
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Yellow, "英华学堂刷课已停止")
        return None

    def pull_course_list(self) -> List[dict]:
        """拉取课程列表 - 调用 aggregation 层的课程动作"""
        if self._cache is None:
            err = self.login()
            if err:
                return []

        course_list, err = yinghua_agg.course_list_action(self._cache)
        if err:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Red, f"拉取课程列表失败: {err}")
            return []

        result = []
        for course in course_list:
            result.append({
                "courseId": course.id,
                "courseName": course.name,
                "progress": course.progress,
                "startDate": str(course.start_date) if course.start_date else "",
            })
        return result

    def _brush_loop(self):
        """后台刷课主循环"""
        try:
            from logic.yinghua import part as yinghua_part
            setting = self._build_setting()
            users = [self.user]
            caches = [self._cache]
            yinghua_part.run_brush_operation(setting, users, caches)
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      BoldRed, f"刷课异常: {e}")
        finally:
            self.is_running = False

    def _keep_alive_loop(self, cache: YingHuaUserCache):
        """登录保活 - 每5分钟发送心跳"""
        import time
        while True:
            time.sleep(5 * 60)
            try:
                result = yinghua_api.keep_alive_api(cache, retry=8)
                log_print(INFO, "[", Green, cache.account, Default, "] ",
                          f"英华心跳保活: {result}")
            except Exception as e:
                log_print(INFO, "[", Green, cache.account, Default, "] ",
                          Red, f"保活失败: {e}")

    def _build_setting(self) -> Setting:
        """构建默认 Setting（Web模式使用全局配置时可扩展）"""
        return Setting()


"""
英华学堂 Activity - 对应 Go 项目的 web/activity/YinghuaActivity.go
实现英华学堂平台的用户活动
"""


class YingHuaActivity(UserActivityBase):
    """英华学堂活动"""

    def __init__(self, user: User = None):
        super().__init__(user)

    def login(self) -> Optional[Exception]:
        """
        英华学堂登录
        TODO: 实现实际的登录逻辑
        """
        log_print(INFO, "[", Green, self.user.account, White, "] ",
                  Red, "英华学堂登录功能待实现（需重写 HTTP API 层）")
        return NotImplementedError("英华学堂登录 API 待实现")

    def start(self) -> Optional[Exception]:
        """启动刷课"""
        self.is_running = True
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Purple, "英华学堂刷课已启动")
        return None

    def stop(self) -> Optional[Exception]:
        """停止刷课"""
        self.is_running = False
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Yellow, "英华学堂刷课已停止")
        return None

    def pull_course_list(self) -> List[dict]:
        """
        拉取课程列表
        TODO: 实现实际的课程拉取逻辑
        """
        return []
