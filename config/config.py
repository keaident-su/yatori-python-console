# -*- coding: utf-8 -*-
"""
配置模块 - 对应 Go 项目的 Config.go
使用 dataclass 定义所有配置结构体，支持 YAML/JSON 读取
"""
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict

import yaml


# ============ 配置结构体定义 ============

@dataclass
class BasicSetting:
    """基础设置"""
    completion_tone: int = 1       # 是否开启刷完提示音，0关闭，1开启
    color_log: int = 1             # 是否为彩色日志
    log_out_file_sw: int = 1       # 是否输出日志文件
    log_level: str = "INFO"        # 日志等级
    log_model: int = 0             # 日志模式
    web_model: int = 0             # Web模式


@dataclass
class EmailInform:
    """邮件通知配置"""
    sw: int = 0
    smtp_host: str = ""
    smtp_port: int = 0
    user_name: str = ""
    password: str = ""


@dataclass
class AiSetting:
    """AI 设置"""
    ai_type: str = "TONGYI"
    ai_url: str = ""
    model: str = ""
    api_key: str = ""


@dataclass
class ApiQueSetting:
    """外部题库 API 设置"""
    url: str = "http://localhost:8083"


@dataclass
class Setting:
    """总设置"""
    basic_setting: BasicSetting = field(default_factory=BasicSetting)
    email_inform: EmailInform = field(default_factory=EmailInform)
    ai_setting: AiSetting = field(default_factory=AiSetting)
    api_que_setting: ApiQueSetting = field(default_factory=ApiQueSetting)


@dataclass
class CoursesSettings:
    """课程过滤设置"""
    name: str = ""
    include_exams: List[str] = field(default_factory=list)
    exclude_exams: List[str] = field(default_factory=list)


@dataclass
class CoursesCustom:
    """课程自定义设置"""
    study_time: str = ""
    cx_node: Optional[int] = 3              # 学习通多任务点数量
    cx_chapter_test_sw: Optional[int] = 1   # 学习通章测开关
    cx_work_sw: Optional[int] = 1           # 学习通作业开关
    cx_exam_sw: Optional[int] = 1           # 学习通考试开关
    shuffle_sw: int = 0                     # 是否打乱顺序
    video_model: int = 1                    # 观看视频模式
    auto_exam: int = 0                      # 是否自动考试
    exam_auto_submit: int = 0               # 是否自动提交试卷
    device_flag: str = ""                   # 设备特征码(学习通APP内获取, 用于考试客户端签名)
    exclude_courses: List[str] = field(default_factory=list)
    include_courses: List[str] = field(default_factory=list)
    courses_settings: List[CoursesSettings] = field(default_factory=list)


@dataclass
class User:
    """用户配置"""
    account_type: str = ""
    url: str = ""
    remark_name: str = ""
    account: str = ""
    password: str = ""
    is_proxy: int = 0
    inform_emails: List[str] = field(default_factory=list)
    courses_custom: CoursesCustom = field(default_factory=CoursesCustom)


@dataclass
class JSONDataForConfig:
    """配置文件根结构"""
    setting: Setting = field(default_factory=Setting)
    users: List[User] = field(default_factory=list)


# ============ 备注名管理 ============

_remark_names: Dict[str, str] = {}


def display_account(account: str) -> str:
    """获取账号的显示名称（优先使用备注名）"""
    return _remark_names.get(account, account)


def _register_remark_names(config: JSONDataForConfig):
    """注册备注名映射"""
    global _remark_names
    _remark_names = {}
    ambiguous_accounts: set = set()
    for user in config.users:
        remark_name = user.remark_name.strip()
        if user.account and remark_name:
            if user.account in _remark_names:
                if _remark_names[user.account] != remark_name:
                    del _remark_names[user.account]
                    ambiguous_accounts.add(user.account)
                    continue
            if user.account in ambiguous_accounts:
                continue
            _remark_names[user.account] = remark_name


# ============ 工具函数 ============

def cmp_course(course: str, course_list: List[str]) -> bool:
    """比较是否存在对应课程"""
    return course in course_list


def get_user_input(prompt: str) -> str:
    """获取用户输入"""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def str_to_int(s: str) -> int:
    """安全字符串转整数"""
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


# ============ 配置读取 ============

def _safe_int(value, default=0) -> int:
    """安全的整数转换"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _apply_yaml_mapping(data: dict, target):
    """递归将 dict 映射到 dataclass 实例，含类型自动转换"""
    if not isinstance(data, dict):
        return target

    import re

    # 构建归一化查找表：去除下划线并全小写 → 实际字段名
    _norm_map = {}
    for attr in dir(target):
        if attr.startswith('_'):
            continue
        _norm_map[attr.replace('_', '').lower()] = attr

    for key, value in data.items():
        # 解析字段名：支持 snake_case / camelCase / 连续大写（如 SMTPHost）
        attr_name = key
        if not hasattr(target, attr_name):
            snake = re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()
            if hasattr(target, snake):
                attr_name = snake
            else:
                # 归一化查找（解决 SMTPHost → smtp_host 等连续大写问题）
                norm_key = key.replace('_', '').lower()
                if norm_key in _norm_map:
                    attr_name = _norm_map[norm_key]
                else:
                    continue
        current = getattr(target, attr_name, None)
        if isinstance(current, (BasicSetting, EmailInform, AiSetting,
                                ApiQueSetting, Setting, CoursesCustom)):
            _apply_yaml_mapping(value, current)
        elif isinstance(current, list) and isinstance(value, list):
            # 处理列表字段
            new_list = []
            for item in value:
                if isinstance(item, dict) and hasattr(current, '__class__'):
                    new_list.append(item)
                else:
                    new_list.append(item)
            setattr(target, attr_name, new_list)
        else:
            # 类型自动转换：int 字段强制转 int，str 字段强制转 str
            if isinstance(current, int) and not isinstance(value, int):
                setattr(target, attr_name, _safe_int(value, current))
            elif isinstance(current, str) and not isinstance(value, str):
                setattr(target, attr_name, str(value))
            else:
                setattr(target, attr_name, value)
    return target


def _default_value(config: JSONDataForConfig):
    """设置默认值并确保所有整数字段类型正确"""
    # 基本设置 int 字段强制转换
    bs = config.setting.basic_setting
    bs.completion_tone = _safe_int(bs.completion_tone, 1)
    bs.color_log = _safe_int(bs.color_log, 1)
    bs.log_out_file_sw = _safe_int(bs.log_out_file_sw, 1)
    bs.log_model = _safe_int(bs.log_model, 0)
    bs.web_model = _safe_int(bs.web_model, 0)

    for user in config.users:
        # User 层 int 字段
        user.is_proxy = _safe_int(user.is_proxy, 0)

        # CoursesCustom 层 int/Optional[int] 字段
        cc = user.courses_custom
        cc.cx_node = _safe_int(cc.cx_node, 3) if cc.cx_node is not None else 3
        cc.cx_chapter_test_sw = _safe_int(
            cc.cx_chapter_test_sw, 1) if cc.cx_chapter_test_sw is not None else 1
        cc.cx_work_sw = _safe_int(
            cc.cx_work_sw, 1) if cc.cx_work_sw is not None else 1
        cc.cx_exam_sw = _safe_int(
            cc.cx_exam_sw, 1) if cc.cx_exam_sw is not None else 1
        cc.shuffle_sw = _safe_int(cc.shuffle_sw, 0)
        cc.video_model = _safe_int(cc.video_model, 1)
        cc.auto_exam = _safe_int(cc.auto_exam, 0)
        cc.exam_auto_submit = _safe_int(cc.exam_auto_submit, 0)


def _parse_user_list(users_data: list) -> List[User]:
    """解析用户列表"""
    users = []
    if not users_data:
        return users
    for u in users_data:
        if not isinstance(u, dict):
            continue
        cc_data = u.get('coursesCustom', u.get('courses_custom', {}))
        cc = CoursesCustom()
        if isinstance(cc_data, dict):
            _apply_yaml_mapping(cc_data, cc)

        user = User(
            account_type=u.get('accountType', u.get('account_type', '')),
            url=u.get('url', u.get('URL', '')),
            remark_name=u.get('remarkName', u.get('remark_name', '')),
            account=u.get('account', ''),
            password=u.get('password', ''),
            is_proxy=_safe_int(u.get('isProxy', u.get('is_proxy', 0))),
            inform_emails=u.get('informEmails', u.get('inform_emails', [])),
            courses_custom=cc,
        )
        users.append(user)
    return users


def _parse_setting(setting_data: dict) -> Setting:
    """解析 Setting"""
    setting = Setting()
    if not isinstance(setting_data, dict):
        return setting

    bs_data = setting_data.get(
        'basicSetting', setting_data.get('basic_setting', {}))
    if isinstance(bs_data, dict):
        _apply_yaml_mapping(bs_data, setting.basic_setting)

    ei_data = setting_data.get(
        'emailInform', setting_data.get('email_inform', {}))
    if isinstance(ei_data, dict):
        _apply_yaml_mapping(ei_data, setting.email_inform)

    ai_data = setting_data.get('aiSetting', setting_data.get('ai_setting', {}))
    if isinstance(ai_data, dict):
        _apply_yaml_mapping(ai_data, setting.ai_setting)

    aq_data = setting_data.get(
        'apiQueSetting', setting_data.get('api_que_setting', {}))
    if isinstance(aq_data, dict):
        _apply_yaml_mapping(aq_data, setting.api_que_setting)

    return setting


def read_json_config(file_path: str) -> JSONDataForConfig:
    """读取 JSON 配置文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    config = JSONDataForConfig()
    config.setting = _parse_setting(data.get('setting', {}))
    config.users = _parse_user_list(data.get('users', []))
    _default_value(config)
    _register_remark_names(config)
    return config


def read_config(file_path: str = "./config.yaml") -> JSONDataForConfig:
    """自动识别读取配置文件（YAML）"""
    if not os.path.exists(file_path):
        from utils.log import log_print, INFO, BoldRed
        log_print(INFO, BoldRed, "找不到配置文件或配置文件内容书写错误")
        sys.exit(1)

    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}

    config = JSONDataForConfig()
    config.setting = _parse_setting(data.get('setting', {}))
    config.users = _parse_user_list(data.get('users', []))
    _default_value(config)
    _register_remark_names(config)
    return config


def read_logo() -> str:
    """读取 LOGO 文本"""
    logo_path = Path(__file__).parent / "logo.txt"
    if logo_path.exists():
        return logo_path.read_text(encoding='utf-8')
    return ""
