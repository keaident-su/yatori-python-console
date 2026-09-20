# -*- coding: utf-8 -*-
"""
通用平台逻辑模板 - 各平台共享的模式
为每个平台提供 filter_account, login, run_brush 的标准实现框架
"""
import json
import threading
from typing import List, Any

from config.config import User, Setting, JSONDataForConfig
from utils.log import log_print, INFO, Green, Red, Default, Purple, Yellow, BoldRed
from global_state.global_var import ACCOUNT_TYPE_STR
from utils.email_utils import send_mail
from utils.showdoc_utils import send_showdoc
from utils.notice import play_notice_sound


def generic_filter_account(config_data: JSONDataForConfig,
                           platform_type: str) -> List[User]:
    """通用账号过滤"""
    return [u for u in config_data.users if u.account_type == platform_type]


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

    # ============ 推送通知内容(邮件与ShowDoc共用, 可自行修改此处内容) ============
    notify_content = (f"账号：[{user.account}]<br>平台：[{platform_name}]<br>"
                      f"通知：所有课程已执行完毕")

    # 邮件通知 (开关: setting.emailInform.sw)
    if setting.email_inform.sw == 1 and len(user.inform_emails) > 0:
        send_mail(
            setting.email_inform.smtp_host,
            setting.email_inform.smtp_port,
            setting.email_inform.user_name,
            setting.email_inform.password,
            user.inform_emails,
            notify_content
        )

    # ShowDoc推送: 全局通道(全局开关+全局地址) + 用户通道(用户开关+用户地址列表)
    # 两条通道互相独立: 全局开关关闭不影响用户自身的开关
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
        send_showdoc(_target, "Yatori课程助手通知", notify_content)

    # 提示音
    if setting.basic_setting.completion_tone == 1:
        play_notice_sound()


_sound_lock = threading.Lock()
