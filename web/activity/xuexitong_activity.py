# -*- coding: utf-8 -*-
"""
学习通 Activity - 对应 Go 项目的 web/activity/XueXiTongActivity.go
实现学习通平台的用户活动（登录/刷课/课程拉取）
"""
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
        # 启动锁(2026-09-28): 防前端并发/重复点击导致多次登录与线程叠加
        self._start_lock = threading.Lock()

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
        """启动刷课 - 在后台线程运行

        2026-09-28: 全流程加锁防并发重复启动; 各步骤打日志便于排查
        """
        with self._start_lock:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      f"启动请求处理中(缓存{'已就绪' if self._cache else '需登录'})...")
            if self._cache is None:
                log_print(INFO, "[", Green, self.user.account, Default, "] ",
                          "开始登录...")
                err = self.login()
                if err:
                    log_print(INFO, "[", Green, self.user.account, Default,
                              "] ", Red, f"启动中止: 登录失败 {err}")
                    return err

            if self.is_running:
                log_print(INFO, "[", Green, self.user.account, Default, "] ",
                          Yellow, "启动被拒: 刷课已在运行中")
                return Exception("刷课已在运行中")

            self.is_running = True
            # 清除上次的停止标志(重新启动时恢复运行)
            from logic.xuexitong import part as xxt_part
            xxt_part.clear_stop(self.user.account)
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Purple, "学习通刷课已启动")

            self._brush_thread = threading.Thread(
                target=self._brush_loop, daemon=True,
                name=f"xxt-brush-{self.user.account}")
            self._brush_thread.start()
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      f"后台刷课线程已拉起({self._brush_thread.name})")
            return None

    def stop(self) -> Optional[Exception]:
        """停止刷课"""
        self.is_running = False
        # 通知引擎层优雅退出(视频轮询/节点调度/建池循环均设检查点)
        from logic.xuexitong import part as xxt_part
        xxt_part.request_stop(self.user.account)
        log_print(INFO, "[", Green, self.user.account, Default, "] ",
                  Yellow, "学习通刷课已停止")
        return None

    def pull_course_list(self) -> List[dict]:
        """拉取课程列表+总进度 - 复用 part.web_course_list(统一结构)"""
        if self._cache is None:
            err = self.login()
            if err:
                return []
        try:
            from logic.xuexitong import part as xxt_part
            return xxt_part.web_course_list(self._cache, self.user) or []
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Red, f"拉取课程列表失败: {e}")
            return []

    def course_detail_stat(self, course_id: str) -> dict:
        """课程详情统计(作业x/y+考试x/y, 2026-10-13 进度页懒加载)"""
        if self._cache is None:
            err = self.login()
            if err:
                return {"supported": False}
        try:
            from logic.xuexitong import part as xxt_part
            return xxt_part.web_course_detail_stat(
                self._cache, self.user, str(course_id))
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      Red, f"课程详情统计失败: {e}")
            return {"supported": False}

    def _brush_loop(self):
        """后台刷课主循环"""
        try:
            from logic.xuexitong import part as xxt_part
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      "刷课引擎启动中(加载全局配置)...")
            setting = self._build_setting()
            users = [self.user]
            # 2026-09-24 修复双建池: 不再按 cx_node 复制 N 份 cache
            # (旧逻辑与引擎层重复建池 → cxNode=10 时 N×N=100 次登录风暴,
            #  cxNode=-1 时 range(-1) 为空导致一个线程都不起);
            # 登录池建立统一由引擎层 part._user_block 按 cx_node 分支处理
            caches = [self._cache]
            xxt_part.run_brush_operation(setting, users, caches)
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      "刷课引擎正常退出")
        except Exception as e:
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      BoldRed, f"刷课异常: {type(e).__name__}: {e}")
        finally:
            self.is_running = False
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      "刷课状态已复位(is_running=False)")

    def _build_setting(self) -> Setting:
        """构建默认 Setting（Web模式使用全局配置时可扩展）"""
        from web.service.user_service import load_web_setting
        return load_web_setting()
