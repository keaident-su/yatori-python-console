# -*- coding: utf-8 -*-
"""
学习通 Activity - 对应 Go 项目的 web/activity/XueXiTongActivity.go
实现学习通平台的用户活动（登录/刷课/课程拉取）
"""
import copy
import re
import threading
from typing import Optional, List, Any

from config.config import User, Setting
from web.activity.base_activity import UserActivityBase
from logic.xuexitong.models import XueXiTUserCache, XueXiTCourse
from logic.xuexitong import api as xxt_api
from logic.core.models import safe_json_parse, json_get
from utils.log import log_print, INFO, Green, White, Red, Default, Purple, Yellow, BoldRed


class XXTActivity(UserActivityBase):
    """学习通活动 - Web 模式下的用户操作入口"""

    def __init__(self, user: User = None):
        super().__init__(user)
        self._cache: Optional[XueXiTUserCache] = None
        self._brush_thread: Optional[threading.Thread] = None

    def login(self) -> Optional[Exception]:
        """学习通登录 - 支持密码登录和 Cookie 登录"""
        if not self.user.account:
            return Exception("账号为空")

        cache = XueXiTUserCache(
            account=self.user.account,
            password=self.user.password,
        )

        # Cookie 登录（密码长度>=50）
        if len(cache.password) >= 50:
            cache.is_cookie_login = True
            cache.cookie_str = cache.password
            uid_match = re.search(r'UID=(\d+)', cache.cookie_str)
            if uid_match:
                cache.uid = uid_match.group(1)
            self._cache = cache
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Green, "学习通 Cookie 登录成功")
            return None

        # 密码登录
        body, _ = xxt_api.login_api(cache, retry=8)
        if not body:
            return Exception("登录响应为空")

        data = safe_json_parse(body)
        if data and data.get("status") is True:
            self._cache = cache
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Green, "学习通密码登录成功")
            return None

        msg = data.get("msg2", data.get("msg1", "未知错误")) if data else "解析失败"
        log_print(INFO, "[", Green, self.user.account, White, "] ",
                  Red, f"学习通登录失败: {msg}")
        return Exception(f"登录失败: {msg}")

    def start(self) -> Optional[Exception]:
        """启动刷课 - 在后台线程运行"""
        if self._cache is None:
            err = self.login()
            if err:
                return err

        if self.is_running:
            return Exception("刷课已在运行中")

        self.is_running = True
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Purple, "学习通刷课已启动")

        self._brush_thread = threading.Thread(
            target=self._brush_loop, daemon=True)
        self._brush_thread.start()
        return None

    def stop(self) -> Optional[Exception]:
        """停止刷课"""
        self.is_running = False
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Yellow, "学习通刷课已停止")
        return None

    def pull_course_list(self) -> List[dict]:
        """拉取课程列表 - 调用学习通课程 API"""
        if self._cache is None:
            err = self.login()
            if err:
                return []

        body, _ = xxt_api.course_list_api(self._cache, retry=8)
        data = safe_json_parse(body)
        if not data:
            return []

        result = []
        channel_list = json_get(data, "channelList", default=[])
        for ch in channel_list:
            if not isinstance(ch, dict):
                continue
            content = ch.get("content", {})
            if not isinstance(content, dict):
                continue
            course_info = content.get("course", {})
            if not isinstance(course_info, dict):
                continue
            data_list = course_info.get("data", [])
            if isinstance(data_list, list) and data_list:
                c = data_list[0]
                result.append({
                    "courseId": str(c.get("id", "")),
                    "courseName": c.get("name", ""),
                    "teacher": c.get("teacherfactor", ""),
                    "classId": str(ch.get("id", "")),
                })
        return result

    def _brush_loop(self):
        """后台刷课主循环"""
        try:
            from logic.xuexitong import part as xxt_part
            setting = self._build_setting()
            users = [self.user]
            # 学习通多任务点：创建 cx_node 个 cache 副本
            cx_node = self.user.courses_custom.cx_node or 3
            caches = [copy.deepcopy(self._cache) for _ in range(cx_node)]
            xxt_part.run_brush_operation(setting, users, caches)
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      BoldRed, f"刷课异常: {e}")
        finally:
            self.is_running = False

    def _build_setting(self) -> Setting:
        """构建默认 Setting（Web模式使用全局配置时可扩展）"""
        return Setting()
