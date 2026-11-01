# -*- coding: utf-8 -*-
"""
学习通 Activity - 对应 Go 项目的 web/activity/XueXiTongActivity.go
实现学习通平台的用户活动（登录/刷课/课程拉取）
"""
import re
import threading
import time
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
            # 2026-10-19: Cookie登录同样获取身份信息
            try:
                from logic.xuexitong import part as _xxt_part2
                _xxt_part2._save_user_profile(cache, self.user)
            except Exception:
                pass
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
            # 2026-10-19 修复: web模式登录链漏了身份信息保存
            # (V2.0.7首次验收发现: 仅part.user_login_operation有hook, web登录无)
            try:
                from logic.xuexitong import part as _xxt_part
                _xxt_part._save_user_profile(cache, self.user)
            except Exception:
                pass
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
            from logic.core import retake_scanner as _rt_scan
            _first_scan = True
            while self.is_running:
                xxt_part.run_brush_operation(setting, users, caches)
                if not self.is_running or not _rt_scan.has_scanner("XUEXITONG"):
                    break
                # [V3.2.3] 可重做巡检: 登录后立即一次, 之后每 1 小时一次(守护循环)
                try:
                    if _first_scan:
                        _rt_scan.run("XUEXITONG", caches[0], self.user,
                                     self._retake_log(), execute=True)
                        _first_scan = False
                    _left = _rt_scan.seconds_until_next(self.user.account)
                    while _left > 0 and self.is_running:
                        time.sleep(min(30, _left))
                        _left -= 30
                    if not self.is_running:
                        break
                    _rt_scan.run("XUEXITONG", caches[0], self.user,
                                 self._retake_log(), execute=True)
                except Exception as _rse:
                    log_print(INFO, "[", Green, self.user.account, Default,
                              "] ", Red, f"巡检异常: {str(_rse)[:100]}")
                    break
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      "刷课引擎正常退出")
        except Exception as e:
            _crashed = True
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      BoldRed, f"刷课异常: {type(e).__name__}: {e}")
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
            # 2026-10-22: 运行时状态收尾(前端实时条显示"已结束")
            try:
                from web.service import runtime_status as _rt_st
                _rt_st.finish(self.user.account)
            except Exception:
                pass
            log_print(INFO, "[", Green, self.user.account, Default, "] ",
                      "刷课状态已复位(is_running=False)")

    def _build_setting(self) -> Setting:
        """构建默认 Setting（Web模式使用全局配置时可扩展）"""
        from web.service.user_service import load_web_setting
        return load_web_setting()
