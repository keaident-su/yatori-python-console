# -*- coding: utf-8 -*-
"""
安全微伴平台逻辑 - 移植自外部项目 AnQuanWeBan_sdk(WeBan) 并适配本工程架构

流程: 登录(验证码OCR自动识别) → 模拟官方首页 → 同步题库(试题回溯合并)
      → 按项目交替执行「课程学习 + 考试」→ 最终同步题库
依赖: nodriver(浏览器, 课程点选/考试无感验证码) / pyaes(登录加密) / opencv+onnx(登录验证码识别)
降级策略(Android/无浏览器/系统限制调起浏览器等场景):
      登录与课程学习照常(登录验证码用本地 OCR 模型, 无需浏览器);
      考试环节(需无感验证码)自动跳过; 个别课程完成时的点选验证码提示失败并跳过;
      手动配置 browserPath 或 cdpHost+cdpPort 时(如 Termux 连接外部调试浏览器)按实测结果处理
答题: 优先项目多答题源引擎(题库/本地缓存/AI), 其次 SDK 自带 answer.json 兜底, 最后随机/手动
"""
import os
import threading
from typing import Any, List

from config.config import User, Setting, JSONDataForConfig, display_account
from global_state.global_var import ACCOUNT_TYPE_STR
from logic.platform_common import (
    generic_filter_account, generic_user_block, get_simple_logger,
    send_user_event_notice, run_stats_bump,
)
from utils.log import log_print, INFO, Red, Yellow

PLATFORM_TYPE = "WEBAN"
_DISPLAY = ACCOUNT_TYPE_STR[PLATFORM_TYPE]

# 依赖延迟导入: 任何依赖缺失时仅对安全微伴平台生效(不影响其他平台启动)
try:
    from logic.weban.client import WeBanClient
    from logic.weban._deps import is_non_interactive as _is_non_interactive
    _DEPS_IMPORT_ERROR = ""
except ImportError as _e:  # pragma: no cover - 依赖缺失场景
    WeBanClient = None  # type: ignore[assignment]
    _is_non_interactive = lambda: False  # type: ignore[assignment]
    _DEPS_IMPORT_ERROR = str(_e)

# 多账号同步题库串行锁(对齐原 SDK main.py 的 sync_lock)
_sync_lock = threading.Lock()


class WebanUserCache:
    """安全微伴用户缓存 - 持有已登录客户端与配置用户"""
    __slots__ = ("client", "user", "account")

    def __init__(self, client: Any, user: User):
        self.client = client
        self.user = user
        self.account = user.account


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    """从配置中过滤出安全微伴账号"""
    return generic_filter_account(config_data, PLATFORM_TYPE)


def _resolve_browser_options(setting: Setting) -> dict:
    """解析全局浏览器/CDP设置(安全微伴验证码自动识别用)

    优先配置文件: basicSetting.browserPath / cdpHost / cdpPort;
    环境变量 YATORI_BROWSER_PATH 作为 browserPath 的兜底(Docker 场景)。
    """
    bs = getattr(setting, "basic_setting", None)
    browser_path = ""
    cdp_host = ""
    cdp_port = 0
    if bs is not None:
        browser_path = (getattr(bs, "browser_path", "") or "").strip()
        cdp_host = (getattr(bs, "cdp_host", "") or "").strip()
        try:
            cdp_port = int(getattr(bs, "cdp_port", 0) or 0)
        except (TypeError, ValueError):
            cdp_port = 0
    browser_path = browser_path or os.environ.get("YATORI_BROWSER_PATH", "").strip()
    return {
        "browser_path": browser_path or None,
        "cdp_host": cdp_host or None,
        "cdp_port": cdp_port or None,
    }


def _probe_browser(options: dict, log) -> tuple:
    """判定浏览器自动化能力: 返回 (是否可用, 原因说明)

    - Android/Termux 且未手动配置 browserPath/CDP: 直接判定不可用
      (Android 无桌面 Chromium, 避免无谓的昂贵探测);
    - 其余环境(含手动配置): 调用 check_browser_health 实测;
    - 系统限制调起浏览器(沙箱/安全软件拦截)由实测失败覆盖。
    """
    try:
        from logic.weban._deps import is_android
        if is_android() and not (options["browser_path"] or options["cdp_host"]):
            return False, ("Android 环境无桌面 Chromium, 浏览器验证码不可用"
                           "(可配置 cdpHost+cdpPort 连接外部调试浏览器以启用)")
    except ImportError:
        pass
    try:
        from logic.weban._deps import load_captcha_module
        resolved = load_captcha_module().check_browser_health(
            options["browser_path"], options["cdp_host"], options["cdp_port"])
        log.info(f"浏览器检测通过: {resolved}")
        return True, ""
    except Exception as e:
        return False, str(e)


def user_login_operation(users: List[User]) -> List[WebanUserCache]:
    """批量登录(单账号失败仅跳过, 不影响其他账号与其他平台)

    登录验证码使用本地 OCR 模型(cv2+onnx), 不需要浏览器。
    """
    if WeBanClient is None:
        if users:
            log_print(INFO, f"[{_DISPLAY}]", Red,
                      f" 缺少依赖, 安全微伴功能不可用: {_DEPS_IMPORT_ERROR}")
            log_print(INFO, f"[{_DISPLAY}]", Yellow,
                      " 请执行: pip install -r requirements.txt (需要 nodriver / pyaes 等)")
        return []

    user_caches: List[WebanUserCache] = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cc = user.courses_custom
        log = get_simple_logger(f"[{_DISPLAY}][{display_account(user.account)}]")
        tenant = (cc.wb_tenant or "").strip()
        if not tenant:
            log.error("未配置学校全称(wbTenant), 请在配置文件生成器中填写后重试, 已跳过")
            continue
        try:
            common_kw = dict(
                log=log,
                debug=bool(cc.wb_debug),
                ai_config=None,  # 答题统一走项目多答题源引擎, 不使用 SDK 内置 AI
                video_speed=float(cc.wb_video_speed),
                jupiter_fallback=bool(cc.wb_jupiter_fallback),
            )
            if cc.wb_user_id:
                # Token 登录(密码栏填 token)
                client = WeBanClient(
                    tenant, user={"userId": cc.wb_user_id, "token": user.password},
                    **common_kw)
            else:
                # 密码登录(密码留空时默认与账号相同, 对齐原 SDK)
                client = WeBanClient(
                    tenant, user.account, user.password or user.account, **common_kw)
        except Exception as e:
            log.error(f"初始化失败: {e}")
            continue

        if not client.login():
            log.error("登录失败(账号/密码错误或验证码识别失败), 已跳过该账号")
            continue
        log.success("登录成功")
        try:
            client.simulate_home_page()
        except Exception as e:
            log.warning(f"模拟首页异常(不影响学习): {e}")
        user_caches.append(WebanUserCache(client=client, user=user))
    return user_caches


def run_brush_operation(setting: Setting, users: List[User], user_caches: List[Any]):
    """执行刷课(每账号一个线程并发)"""
    threads = []
    for cache in user_caches:
        t = threading.Thread(target=_user_block, args=(setting, cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def _user_block(setting: Setting, cache: WebanUserCache):
    """单账号完整流程: 浏览器能力判定(分级降级) → 题库同步 → 学习(+考试) → 最终同步 → 整体通知"""
    user = cache.user
    client = cache.client
    cc = user.courses_custom
    log = get_simple_logger(f"[{_DISPLAY}][{display_account(user.account)}]")

    # 注入全局浏览器/CDP设置并重置验证码处理器(登录阶段未传)
    browser_opts = _resolve_browser_options(setting)
    client.browser_path = browser_opts["browser_path"]
    client.cdp_host = browser_opts["cdp_host"]
    client.cdp_port = browser_opts["cdp_port"]
    client._captcha_handler = None

    # 浏览器能力分级降级: 不可用时仅停用浏览器相关环节, 不再跳过整个账号
    browser_usable, browser_reason = _probe_browser(browser_opts, log)
    if not browser_usable:
        client.browser_disabled = True
        log.warning(f"浏览器验证码不可用: {browser_reason}")
        log.warning("降级模式: 登录/课程学习照常执行; 考试环节已自动跳过; "
                    "个别课程完成时的点选验证码将提示失败并跳过")

    # 事件通知回调(课程/考试完成实时推送, 与项目其他平台一致)
    def _on_event(kind: str, line: str):
        try:
            if kind in ("course", "exam"):
                run_stats_bump(_DISPLAY, user.account, kind)
            send_user_event_notice(setting, user, _DISPLAY, line)
        except Exception:
            pass

    client.on_event = _on_event

    # 题库同步(试题回溯合并; 多账号串行)
    try:
        with _sync_lock:
            client.sync_answers()
    except Exception as e:
        log.warning(f"题库同步异常(不影响学习): {e}")

    # 学习+考试(按项目交替; 浏览器不可用时跳过考试环节)
    study_mode = {0: "false", 1: "true", 2: "force"}.get(int(cc.wb_study_mode), "true")
    exam_mode = {0: "false", 1: "true", 2: "perfect", 3: "force"}.get(int(cc.wb_exam_mode), "true")
    if not browser_usable and exam_mode != "false":
        log.info("考试需要浏览器无感验证码, 降级模式下已自动跳过考试环节")
        exam_mode = "false"
    client.exam_mode = exam_mode
    try:
        client.run_project_cycle(
            study_time=f"{max(0, int(cc.wb_study_time))},10",
            study_mode=study_mode,
            exam_mode=exam_mode,
            random_answer=bool(cc.wb_random_answer) or _is_non_interactive(),
            exam_question_time=f"{max(0, int(cc.wb_exam_question_time))},3",
            exam_submit_match_rate=int(cc.wb_exam_submit_match_rate),
        )
    except PermissionError as e:
        log.error(f"Token失效或账号被锁定: {e}")
    except Exception as e:
        log.error(f"执行异常: {e}")

    # 最终同步
    try:
        with _sync_lock:
            client.sync_answers()
    except Exception:
        pass

    log.success("所有待学习课程执行完毕")
    generic_user_block(setting, user, _DISPLAY, brush_func=None)
