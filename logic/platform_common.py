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

    # 邮件通知
    if setting.email_inform.sw == 1 and len(user.inform_emails) > 0:
        send_mail(
            setting.email_inform.smtp_host,
            setting.email_inform.smtp_port,
            setting.email_inform.user_name,
            setting.email_inform.password,
            user.inform_emails,
            f"账号：[{user.account}]<br>平台：[{platform_name}]<br>通知：所有课程已执行完毕"
        )

    # 提示音
    if setting.basic_setting.completion_tone == 1:
        play_notice_sound()


_sound_lock = threading.Lock()
