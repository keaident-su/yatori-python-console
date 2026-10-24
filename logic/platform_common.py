# -*- coding: utf-8 -*-
"""
通用平台逻辑模板 - 各平台共享的模式
为每个平台提供 filter_account, login, run_brush 的标准实现框架
"""
import json
import time
import threading
from typing import List, Any

from config.config import User, Setting, JSONDataForConfig
from utils.log import (
    log_print, INFO, DEBUG, WARNING, ERROR,
    Green, Red, Default, Purple, Yellow, DarkGray, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR
from utils.email_utils import send_mail
from utils.showdoc_utils import send_showdoc
from utils.notice import play_notice_sound


def generic_filter_account(config_data: JSONDataForConfig,
                           platform_type: str) -> List[User]:
    """通用账号过滤"""
    return [u for u in config_data.users if u.account_type == platform_type]


# ============ 夜间休息(全平台公共, 2026-10-10) ============
# 历史: 原实现仅学习通 part.py 私有且只在启动阶段检查(中途到点不停) → 抽为公共函数,
# 各平台 _user_block(入口/课程循环/任务循环)均可调用, 到点即暂停等待, 到点自动恢复。

def in_rest_period(cc) -> bool:
    """判断当前是否处于夜间休息时段(支持跨天如23:00-06:00)

    未开启 rest_sw(默认0)或时间非法返回 False。全平台通用。
    """
    try:
        if int(getattr(cc, "rest_sw", 0) or 0) != 1:
            return False
        import datetime
        now = datetime.datetime.now().time()
        sh, sm = map(int, str(cc.rest_start).split(":"))
        eh, em = map(int, str(cc.rest_end).split(":"))
        start = datetime.time(sh, sm)
        end = datetime.time(eh, em)
        if start <= end:
            return start <= now < end
        # 跨天时段(如23:00-06:00): 当日>=start 或 次日<end
        return now >= start or now < end
    except Exception:
        return False


def rest_wait_if_needed(account: str, cc, platform_name: str,
                        stop_fn=None) -> bool:
    """若处于夜间休息时段则暂停等待到结束(全平台通用)

    :param account: 账号(用于日志)
    :param cc: 用户 courses_custom 配置(含 rest_sw/rest_start/rest_end)
    :param platform_name: 平台中文名(日志前缀)
    :param stop_fn: 可选停止回调(返回True则提前退出); 不传则无视
    :return: True=曾等待(或等待中被停止)
    """
    if not in_rest_period(cc):
        return False
    import datetime
    try:
        eh, em = map(int, str(cc.rest_end).split(":"))
    except Exception:
        return False
    now = datetime.datetime.now()
    end_dt = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end_dt <= now:
        end_dt += datetime.timedelta(days=1)
    wait_s = int((end_dt - now).total_seconds())
    # [V3.1.1] 夜间休息状态上报: 进度大屏/GUI 显示"夜间休息中 + 预计恢复时间"
    _RT = None
    try:
        from web.service import runtime_status as _RT
        _RT.update(account, stage="夜间休息",
                   resting=1,
                   restStart=str(getattr(cc, "rest_start", "") or ""),
                   restEnd=str(getattr(cc, "rest_end", "") or ""),
                   restResumeAt=int(end_dt.timestamp() * 1000),
                   restResumeHm=end_dt.strftime("%H:%M"))
    except Exception:
        _RT = None
    log_print(INFO, f"[{platform_name}]",
              "[", Green, account, Default, "] ",
              Yellow,
              f"夜间休息中({cc.rest_start}-{cc.rest_end})，"
              f"暂停等待约{wait_s/3600:.1f}小时后自动继续...")
    # 分段睡眠(每15秒检查停止回调, 支持Web端随时"停止刷课")
    _tick = 0
    while wait_s > 0:
        if stop_fn is not None:
            try:
                if stop_fn():
                    try:
                        if _RT:
                            _RT.update(account, resting=0, restResumeAt=0,
                                       restResumeHm="", stage="已停止")
                    except Exception:
                        pass
                    log_print(INFO, f"[{platform_name}]",
                              "[", Green, account, Default, "] ",
                              Yellow, "休息等待期间收到停止请求，已退出")
                    return True
            except Exception:
                pass
        chunk = min(15, wait_s)
        time.sleep(chunk)
        wait_s -= chunk
        _tick += 1
        # [V3.1.1] 每约60秒刷新一次恢复时间(保持状态新鲜)
        if _RT is not None and _tick % 4 == 0:
            try:
                _RT.update(account, resting=1,
                           restResumeAt=int(end_dt.timestamp() * 1000),
                           restResumeHm=end_dt.strftime("%H:%M"))
            except Exception:
                pass
    try:
        if _RT:
            _RT.update(account, resting=0, restResumeAt=0, restResumeHm="",
                       stage="夜间休息结束，恢复刷课")
    except Exception:
        pass
    log_print(INFO, f"[{platform_name}]",
              "[", Green, account, Default, "] ",
              Green, "夜间休息结束，恢复刷课")
    return True


def generic_user_block(setting: Setting, user: User,
                       platform_name: str, brush_func=None):
    """
    通用用户刷课块 - 对应各平台 userBlock
    :param setting: 全局设置
    :param user: 用户配置
    :param platform_name: 平台中文名
    :param brush_func: 实际刷课函数 callback(user, cache)
    """
    if brush_func:
        log_print(INFO, f"[{platform_name}]", "[", Green, user.account,
                  Default, "] ", Purple, "开始执行刷课任务...")
        brush_func(setting, user)
        log_print(INFO, f"[{platform_name}]", "[", Green, user.account,
                  Default, "] ", Purple, "所有待学习课程学习完毕")
        # 2026-10-20: 全部任务完成界面赞助提示(自动弹出微信赞赏码, 每进程仅一次; 全平台通用)
        try:
            from utils.sponsor import print_sponsor_banner
            print_sponsor_banner(popup_qr=True)
        except Exception:
            pass

    # ============ 推送通知内容(邮件与ShowDoc共用, 可自行修改此处内容) ============
    # 本次运行汇总(课程/作业/考试完成数, 由各平台事件点上报; 无统计时保持原文案)
    _st = run_stats_snapshot(platform_name, user.account)
    _extra = ""
    if _st:
        _parts = []
        if _st.get("course"):
            _parts.append(f"课程{_st['course']}个")
        if _st.get("work"):
            _parts.append(f"作业{_st['work']}个")
        if _st.get("exam"):
            _parts.append(f"考试{_st['exam']}个")
        if _parts:
            _extra = f"（本次完成：{'、'.join(_parts)}）"
    notify_content = (f"账号：[{user.account}]<br>平台：[{platform_name}]<br>"
                      f"通知：所有课程已执行完毕{_extra}")

    # 双通道发送(邮件+ShowDoc): 与按事件通知共用同一发送函数, 标题前缀取"通知开头名称"配置
    with _notice_send_lock:
        _send_notice_via_channels(setting, user, notify_content)

    # 提示音
    if setting.basic_setting.completion_tone == 1:
        play_notice_sound()


_sound_lock = threading.Lock()


# ============ 通知发送(整体通知与按事件通知共用) ============

# 通知发送锁: 多课程并发完成时避免发送交错/并发压力(发送本身很快, 串行化无感)
_notice_send_lock = threading.Lock()

# 本次运行的完成统计(课程/作业/考试), 供整体通知汇总; key=(平台, 账号)
_run_stats_lock = threading.Lock()
_run_stats: dict = {}


def run_stats_bump(platform_name: str, account: str, kind: str):
    """记录本次运行完成的课程/作业/考试数量(供整体通知汇总)

    :param kind: "course" / "work" / "exam"
    """
    with _run_stats_lock:
        _st = _run_stats.setdefault(
            (platform_name, account), {"course": 0, "work": 0, "exam": 0})
        _st[kind] = _st.get(kind, 0) + 1


def run_stats_snapshot(platform_name: str, account: str):
    """读取本次运行完成统计(无记录返回 None)"""
    with _run_stats_lock:
        _st = _run_stats.get((platform_name, account))
        return dict(_st) if _st else None


def _notice_prefix(setting: Setting) -> str:
    """读取"通知开头名称"配置(留空回退默认 "Yatori")"""
    return (getattr(setting.basic_setting, "notice_prefix", "") or "").strip() or "Yatori"


def _send_notice_via_channels(setting: Setting, user: User, content: str):
    """双通道发送通知(邮件 + ShowDoc), 供整体通知与按事件通知共用

    邮件: setting.emailInform.sw 开关 + 用户通知邮箱列表;
    ShowDoc: 全局通道(全局开关+全局地址) + 用户通道(用户开关+用户地址列表),
    两条通道互相独立, 全局开关关闭不影响用户自身的开关。
    标题前缀取"通知开头名称"配置(默认 Yatori)。
    """
    title = f"{_notice_prefix(setting)}课程助手"
    # 邮件通知 (开关: setting.emailInform.sw)
    if setting.email_inform.sw == 1 and len(user.inform_emails) > 0:
        send_mail(
            setting.email_inform.smtp_host,
            setting.email_inform.smtp_port,
            setting.email_inform.user_name,
            setting.email_inform.password,
            user.inform_emails,
            content,
            title=title,
        )
    # ShowDoc推送: 全局通道 + 用户通道
    _showdoc_targets: List[str] = []
    if setting.showdoc_inform.sw == 1:
        _g_url = (setting.showdoc_inform.url or "").strip()
        if _g_url:
            _showdoc_targets.append(_g_url)
    if user.showdoc_sw == 1:
        for _u_url in (user.showdoc_urls or []):
            _u_url = (_u_url or "").strip()
            if _u_url and _u_url not in _showdoc_targets:
                _showdoc_targets.append(_u_url)
    for _target in _showdoc_targets:
        send_showdoc(_target, f"{title}通知", content)


def send_user_event_notice(setting: Setting, user: User,
                           platform_name: str, content_line: str):
    """按事件实时通知(课程/作业/考试完成) - 邮件与ShowDoc双通道

    与"全部课程跑完后"的整体通知相互独立; 不播放提示音(提示音保持只在整体通知)。
    任何异常都不影响主流程(best-effort)。
    """
    try:
        content = (f"账号：[{user.account}]<br>平台：[{platform_name}]<br>"
                   f"通知：{content_line}")
        with _notice_send_lock:
            _send_notice_via_channels(setting, user, content)
    except Exception:
        pass


# ============ 轻量日志适配(供移植平台模块复用) ============

class SimpleLogger:
    """轻量日志适配器 - 将 logging/loguru 风格的调用转发到项目统一日志体系

    供从外部 SDK 移植的平台模块使用(智慧树/安全微伴等):
    - 支持 debug / info / success / warning / error / exception / critical;
    - 消息兼容 f-string(直接拼好)与 %-style(printf 参数)两种写法;
    - 构造时可带统一前缀(如 "[智慧树]"), 输出与其它平台日志风格一致。
    """

    def __init__(self, prefix: str = ""):
        self._prefix = prefix

    def _emit(self, level: str, color: str, msg, args: tuple):
        text = str(msg)
        if args:
            try:
                text = text % args
            except (TypeError, ValueError):
                text = " ".join([text, *[str(a) for a in args]])
        if self._prefix:
            log_print(level, color, self._prefix, " ", Default, text)
        else:
            log_print(level, color, text)

    def debug(self, msg, *args):
        """调试日志"""
        self._emit(DEBUG, DarkGray, msg, args)

    def info(self, msg, *args):
        """普通信息"""
        self._emit(INFO, Default, msg, args)

    def success(self, msg, *args):
        """成功信息(绿色)"""
        self._emit(INFO, Green, msg, args)

    def warning(self, msg, *args):
        """警告信息(黄色)"""
        self._emit(WARNING, Yellow, msg, args)

    def error(self, msg, *args):
        """错误信息(红色)"""
        self._emit(ERROR, Red, msg, args)

    def exception(self, msg, *args):
        """异常信息(红色, 与 error 相同的输出通道)"""
        self._emit(ERROR, Red, msg, args)

    def critical(self, msg, *args):
        """严重错误(加粗红色)"""
        self._emit(ERROR, BoldRed, msg, args)


def get_simple_logger(prefix: str = "") -> SimpleLogger:
    """获取带前缀的轻量日志适配器"""
    return SimpleLogger(prefix)


# ============ 用户身份信息保存(全平台公共, 2026-10-19) ============

def save_user_identity(user, school: str = "", name: str = "",
                       stu_no: str = "", log=None) -> None:
    """获取到的学校/姓名/学号 → 写入users表user_config_json + 日志展示
    (前端账号管理/进度页读取; 各平台登录成功后调用)
    """
    if not (school or name or stu_no):
        return
    uid_db = getattr(user, "uid", "") or ""
    if uid_db:
        try:
            from dao.database import get_session
            from dao import user_mapper
            sess = get_session()
            try:
                po = user_mapper.query_user(sess, uid=uid_db)
                if po:
                    cfg = po.user_config_turn_entity()
                    if school:
                        cfg["school"] = school
                    if name:
                        cfg["realName"] = name
                    if stu_no:
                        cfg["stuNo"] = stu_no
                    user_mapper.update_user(
                        sess, uid_db,
                        {"user_config_json": json.dumps(cfg, ensure_ascii=False)})
            finally:
                sess.close()
        except Exception:
            pass
    _info = f"{school} · {name}" if school else name
    if stu_no:
        _info += f" · 学号{stu_no}"
    if _info and log is not None:
        try:
            log(f"身份信息: {_info}")
        except Exception:
            pass
