# -*- coding: utf-8 -*-
"""
配置模块 - 对应 Go 项目的 Config.go
使用 dataclass 定义所有配置结构体，支持 YAML/JSON 读取
"""
import json
import os
import re
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
    web_port: int = 8080           # Web模式监听端口(多开时被占用会自动顺延到空闲端口)
    ocr_image_question: int = 1    # 图片题目OCR识别开关(0关闭,1开启)
    notice_prefix: str = "Yatori"  # 通知开头名称(邮件主题/推送标题前缀, 留空则回退默认"Yatori")
    browser_path: str = ""        # 浏览器可执行文件路径(安全微伴验证码自动识别用; 留空自动检测Chrome/Chromium/Edge)
    cdp_host: str = ""            # CDP远程调试地址(安全微伴连接已有浏览器实例用, 可留空)
    cdp_port: int = 0              # CDP远程调试端口(0=不使用, 与cdpHost同时填写才生效)
    auto_open_browser: int = 1     # Web模式下启动后自动打开浏览器界面(0关闭,1开启)


@dataclass
class EmailInform:
    """邮件通知配置"""
    sw: int = 0
    smtp_host: str = ""
    smtp_port: int = 0
    user_name: str = ""
    password: str = ""


@dataclass
class ShowDocInform:
    """ShowDoc推送配置 - 与邮件通知并列的推送方案, 两者可独立开关、同时开启"""
    sw: int = 0                 # 是否开启ShowDoc推送(0关闭,1开启)
    url: str = ""               # ShowDoc专属推送地址(含token, 在 push.showdoc.com.cn 获取)


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
class AnswerSourceItemCfg:
    """答题源配置项(题库组/组内子项)
    自定义名称(name)用于调用顺序(order)排序
    """
    name: str = ""              # 自定义名称(二次命名/重命名)
    type: str = ""              # emmcy(言溪题库) / axe(AVXE题库) / ai(AI大模型)
    enable: int = 1             # 独立启停开关: 1启用 / 0禁用
    token: str = ""             # 密钥(token/APIKey), 仅需填写此项
    ai_type: str = ""           # AI类型(仅type=ai): DEEPSEEK/TONGYI/...
    model: str = ""             # AI模型(仅type=ai, 可留空用默认)
    url: str = ""               # 自定义接口地址(可留空, 题库/AI均有内置默认)
    items: List["AnswerSourceItemCfg"] = field(default_factory=list)  # 组内子项


@dataclass
class AnswerSetting:
    """多答题源设置(顺序依次调用、失败即回退)"""
    token_check: int = 1        # 启动时token自检开关: 1开启 / 0关闭
    local_cache_enable: int = 1  # 本地题库缓存开关: 1开启 / 0关闭
    local_cache_path: str = "questions_answers.json"  # 缓存文件(格式同题库json)
    order: List[str] = field(default_factory=list)     # 调用顺序(填自定义名称)
    sources: List[AnswerSourceItemCfg] = field(default_factory=list)  # 题库组列表


@dataclass
class Setting:
    """总设置"""
    basic_setting: BasicSetting = field(default_factory=BasicSetting)
    email_inform: EmailInform = field(default_factory=EmailInform)
    showdoc_inform: ShowDocInform = field(default_factory=ShowDocInform)
    ai_setting: AiSetting = field(default_factory=AiSetting)
    api_que_setting: ApiQueSetting = field(default_factory=ApiQueSetting)
    answer_setting: AnswerSetting = field(default_factory=AnswerSetting)


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
    cx_exam_sw_again: Optional[int] = 0     # 学习通强制重考开关(1=支持重考的考试不管分数都必须重考, 0=仅分数<60时重考)
    shuffle_sw: int = 0                     # 是否打乱顺序
    video_model: int = 1                    # 观看视频模式
    auto_exam: int = 0                      # 是否自动考试
    exam_auto_submit: int = 0               # 是否自动提交试卷
    other_task_stay: int = 30               # 其它/文档类任务点处理后的停留秒数(知识结构/引导问题/单文字/PPT/文档文章等)
    add_study_sw: int = 0                   # 【学习通】增加学习次数/学习时长开关(课程任务点全部完成后执行; 0关1开)
    add_study_count: int = 0                # 【学习通】增加的学习次数(对齐yatori-free默认0=不增加; 上限400)
    add_study_video_minutes: int = 0        # 【学习通】增加的视频观看时长(分钟, 对齐yatori-free默认0=不增加; 上限4000)
    add_study_read_minutes: int = 0         # 【学习通】增加的阅读时长(分钟, 对齐yatori-free默认0=不增加; 上限4000)
    add_study_delay: int = 30               # 【学习通】学习记录上报间隔秒数(建议≥30; 参照chaoxing_tool默认30)
    brute_speed: float = 2.4                # 【学习公社】暴力模式倍速(最低2.4, 未填写默认2.4; 服务端单次封顶5分钟/25秒间隔, 有效上限12x)
    device_flag: str = ""                   # 设备特征码(学习通APP内获取, 用于考试客户端签名)
    # ===== 安全微伴(WEBAN) =====
    wb_tenant: str = ""                     # 【安全微伴】学校全称(必填, 需与登录页显示的学校名称完全一致)
    wb_user_id: str = ""                    # 【安全微伴】Token登录用户ID(可留空; 填写后password视为token)
    wb_study_mode: int = 1                  # 【安全微伴】学习模式: 0=不学习 1=正常学习 2=强制重新学习
    wb_exam_mode: int = 1                   # 【安全微伴】考试模式: 0=不考试 1=正常 2=追求满分 3=强制重考
    wb_random_answer: int = 1               # 【安全微伴】题库外题目随机作答: 1=随机(单选随机/多选全选) 0=终端手动输入
    wb_study_time: int = 20                 # 【安全微伴】每门课学习时长(秒, 随机追加0~10秒)
    wb_video_speed: float = 1.0             # 【安全微伴】视频课程倍速: 0=不按时长等待 1=原速等待 2=半速等待(视频时长/倍速)
    wb_exam_question_time: int = 3          # 【安全微伴】每道考试题答题等待时长(秒, 随机追加0~3秒)
    wb_exam_submit_match_rate: int = 90     # 【安全微伴】允许交卷的最低题库匹配率(%)
    wb_jupiter_fallback: int = 0            # 【安全微伴】未加载apicenext.js的课程是否补发翻页轨迹: 0=否 1=是(个别学校需要)
    wb_debug: int = 0                       # 【安全微伴】调试日志开关: 0关 1开
    # ===== 智慧树(ZHIHUISHU) =====
    zhs_speed: float = 1.5                  # 【智慧树】刷课速度倍率(默认1.5, 越大越快; 范围0.3~20)
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
    showdoc_sw: int = 0                     # 该用户独立的ShowDoc推送开关(0关,1开, 与全局通道互不影响)
    showdoc_urls: List[str] = field(default_factory=list)  # 该用户独立的ShowDoc推送地址列表(可多个)
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
        if isinstance(current, (BasicSetting, EmailInform, ShowDocInform,
                                AiSetting, ApiQueSetting, Setting, CoursesCustom)):
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
    bs.web_port = _safe_int(bs.web_port, 8080)
    bs.ocr_image_question = _safe_int(bs.ocr_image_question, 1)
    # 通知开头名称: 去除首尾空白, 空值回退默认"Yatori", 超长截断防御
    bs.notice_prefix = (str(bs.notice_prefix or "")).strip()[:30] or "Yatori"
    # 浏览器/CDP设置(安全微伴验证码用): 字符串去空白, 端口非负
    bs.browser_path = str(bs.browser_path or "").strip()
    bs.cdp_host = str(bs.cdp_host or "").strip()
    bs.cdp_port = max(0, _safe_int(bs.cdp_port, 0))
    bs.auto_open_browser = _safe_int(bs.auto_open_browser, 1)

    # ShowDoc推送 int 字段强制转换
    config.setting.showdoc_inform.sw = _safe_int(
        config.setting.showdoc_inform.sw, 0)

    # 多答题源设置 int 字段强制转换
    aset = config.setting.answer_setting
    aset.token_check = _safe_int(aset.token_check, 1)
    aset.local_cache_enable = _safe_int(aset.local_cache_enable, 1)
    if not (aset.local_cache_path or "").strip():
        aset.local_cache_path = "questions_answers.json"

    def _fix_source(src: AnswerSourceItemCfg):
        src.enable = _safe_int(src.enable, 1)
        for sub in src.items:
            _fix_source(sub)
    for _src in aset.sources:
        _fix_source(_src)

    for user in config.users:
        # User 层 int 字段
        user.is_proxy = _safe_int(user.is_proxy, 0)
        user.showdoc_sw = _safe_int(user.showdoc_sw, 0)

        # CoursesCustom 层 int/Optional[int] 字段
        cc = user.courses_custom
        cc.cx_node = _safe_int(cc.cx_node, 3) if cc.cx_node is not None else 3
        cc.cx_chapter_test_sw = _safe_int(
            cc.cx_chapter_test_sw, 1) if cc.cx_chapter_test_sw is not None else 1
        cc.cx_work_sw = _safe_int(
            cc.cx_work_sw, 1) if cc.cx_work_sw is not None else 1
        cc.cx_exam_sw = _safe_int(
            cc.cx_exam_sw, 1) if cc.cx_exam_sw is not None else 1
        cc.cx_exam_sw_again = _safe_int(
            cc.cx_exam_sw_again, 0) if cc.cx_exam_sw_again is not None else 0
        cc.shuffle_sw = _safe_int(cc.shuffle_sw, 0)
        cc.video_model = _safe_int(cc.video_model, 1)
        cc.auto_exam = _safe_int(cc.auto_exam, 0)
        cc.exam_auto_submit = _safe_int(cc.exam_auto_submit, 0)
        cc.other_task_stay = _safe_int(cc.other_task_stay, 30)
        cc.add_study_sw = _safe_int(cc.add_study_sw, 0)
        # 三指标边界对齐 yatori-free 界面限制(次数<=400, 时长<=4000分钟); 默认0=不增加
        cc.add_study_count = max(0, min(400, _safe_int(cc.add_study_count, 0)))
        cc.add_study_video_minutes = max(
            0, min(4000, _safe_int(cc.add_study_video_minutes, 0)))
        cc.add_study_read_minutes = max(
            0, min(4000, _safe_int(cc.add_study_read_minutes, 0)))
        cc.add_study_delay = max(30, _safe_int(cc.add_study_delay, 30))
        # 【学习公社】暴力模式倍速: 非法值默认2.4, 范围限制在 2.4 ~ 144
        try:
            cc.brute_speed = float(cc.brute_speed)
        except (ValueError, TypeError):
            cc.brute_speed = 2.4
        if cc.brute_speed != cc.brute_speed or cc.brute_speed <= 0:  # NaN防护
            cc.brute_speed = 2.4
        if cc.brute_speed < 2.4:
            cc.brute_speed = 2.4
        elif cc.brute_speed > 144:
            cc.brute_speed = 144.0

        # 【安全微伴】设置边界修正(向下兼容: 旧配置无这些字段时使用默认值)
        cc.wb_tenant = str(cc.wb_tenant or "").strip()
        cc.wb_user_id = str(cc.wb_user_id or "").strip()
        cc.wb_study_mode = max(0, min(2, _safe_int(cc.wb_study_mode, 1)))
        cc.wb_exam_mode = max(0, min(3, _safe_int(cc.wb_exam_mode, 1)))
        cc.wb_random_answer = 1 if _safe_int(cc.wb_random_answer, 1) != 0 else 0
        cc.wb_study_time = max(0, _safe_int(cc.wb_study_time, 20))
        try:
            cc.wb_video_speed = float(cc.wb_video_speed)
        except (ValueError, TypeError):
            cc.wb_video_speed = 1.0
        if cc.wb_video_speed != cc.wb_video_speed or cc.wb_video_speed < 0:  # NaN防护
            cc.wb_video_speed = 1.0
        if cc.wb_video_speed > 60:
            cc.wb_video_speed = 60.0
        cc.wb_exam_question_time = max(0, _safe_int(cc.wb_exam_question_time, 3))
        cc.wb_exam_submit_match_rate = max(0, min(100, _safe_int(cc.wb_exam_submit_match_rate, 90)))
        cc.wb_jupiter_fallback = 1 if _safe_int(cc.wb_jupiter_fallback, 0) != 0 else 0
        cc.wb_debug = 1 if _safe_int(cc.wb_debug, 0) != 0 else 0
        # 【智慧树】速度倍率: 非法值回退1.5, 范围 0.3 ~ 20
        try:
            cc.zhs_speed = float(cc.zhs_speed)
        except (ValueError, TypeError):
            cc.zhs_speed = 1.5
        if cc.zhs_speed != cc.zhs_speed or cc.zhs_speed <= 0:  # NaN/非正数防护
            cc.zhs_speed = 1.5
        if cc.zhs_speed < 0.3:
            cc.zhs_speed = 0.3
        elif cc.zhs_speed > 20:
            cc.zhs_speed = 20.0

        # 设备特征码检查: 学习通账号未配置deviceFlag时提示
        # (deviceFlag仅在 accountType=XUEXITONG 时生效)
        if (user.account_type or "").upper() == "XUEXITONG":
            flag = (getattr(cc, "device_flag", "") or "").strip()
            if not flag:
                from utils.log import log_print, INFO, Yellow, Default
                log_print(INFO, "[学习通]", "[", Yellow,
                          user.account or "", Default, "] ",
                          Yellow, "未配置deviceFlag(缺乏设备特征码，可能会无法完成某些课程的考试)，登录时将自动生成")


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
            showdoc_sw=_safe_int(u.get('showdocSw', u.get('showdoc_sw', 0))),
            showdoc_urls=u.get('showdocUrls', u.get('showdoc_urls', [])),
            courses_custom=cc,
        )
        users.append(user)
    return users


_ANSWER_TYPE_ALIAS = {
    "emmcy": "emmcy", "yanxi": "emmcy", "yanxi_tiku": "emmcy", "言溪": "emmcy",
    "axe": "axe", "avxe": "axe", "axe_tiku": "axe",
    "n1": "n1", "n1_tiku": "n1", "n1题库": "n1",
    "n1screch": "n1", "n1screch_tiku": "n1",
    "ze": "ze", "ze_tiku": "ze", "zerror": "ze", "ze题库": "ze",
    "every": "every", "everyapi": "every", "every_api": "every",
    "every_tiku": "every", "everyapi_tiku": "every",
    "ai": "ai", "ai_model": "ai", "model": "ai",
    "local": "local", "local_json": "local", "cache": "local",
    "本地题库缓存": "local",
}


def _parse_answer_source_item(data, default_type: str = "") -> AnswerSourceItemCfg:
    """解析单个答题源配置(支持 snake_case/camelCase 键名)"""
    item = AnswerSourceItemCfg()
    if not isinstance(data, dict):
        return item

    def _pick(*keys):
        for k in keys:
            if k in data and data[k] is not None:
                return data[k]
        return None

    name = _pick("name", "remarkName", "remark_name", "title")
    item.name = str(name).strip() if name is not None else ""

    s_type = _pick("type", "sourceType", "source_type", "tikuType", "tiku_type")
    if s_type is not None:
        raw_type = str(s_type).strip()
        item.type = _ANSWER_TYPE_ALIAS.get(raw_type.lower(), raw_type)
    else:
        item.type = default_type

    enable = _pick("enable", "sw", "use", "open")
    item.enable = _safe_int(enable, 1) if enable is not None else 1

    token = _pick("token", "apiKey", "api_key", "key", "secret")
    item.token = str(token).strip() if token is not None else ""

    ai_type = _pick("aiType", "ai_type", "modelType", "model_type")
    item.ai_type = str(ai_type).strip() if ai_type is not None else ""

    model = _pick("model", "aiModel", "ai_model")
    if model is not None and str(model).strip() != str(ai_type).strip():
        item.model = str(model).strip()

    url = _pick("url", "baseUrl", "base_url", "apiUrl", "api_url",
               "path", "file", "filePath", "file_path")
    item.url = str(url).strip() if url is not None else ""

    items = _pick("items", "children", "subItems", "sub_items",
                  "subSources", "sub_sources")
    if isinstance(items, list):
        for sub in items:
            item.items.append(
                _parse_answer_source_item(sub, default_type=item.type))
    return item


def _parse_answer_setting(data) -> AnswerSetting:
    """解析多答题源设置(支持 order 为字符串或列表, sources/groups 双键名)"""
    ans = AnswerSetting()
    if not isinstance(data, dict):
        return ans

    ans.token_check = _safe_int(data.get("tokenCheck", data.get("token_check", 1)), 1)
    ans.local_cache_enable = _safe_int(
        data.get("localCacheEnable", data.get("local_cache_enable", 1)), 1)
    path = data.get("localCachePath", data.get("local_cache_path", ""))
    if isinstance(path, str) and path.strip():
        ans.local_cache_path = path.strip()

    order = data.get("order", data.get("priority", None))
    if isinstance(order, str):
        ans.order = [p.strip() for p in re.split(r'[,，;；\n]+', order) if p.strip()]
    elif isinstance(order, list):
        ans.order = [str(p).strip() for p in order if str(p or "").strip()]

    sources = data.get("sources", data.get("groups", data.get("banks", [])))
    if isinstance(sources, list):
        for s in sources:
            ans.sources.append(_parse_answer_source_item(s))
    return ans


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

    sd_data = setting_data.get(
        'showdocInform', setting_data.get('showdoc_inform', {}))
    if isinstance(sd_data, dict):
        _apply_yaml_mapping(sd_data, setting.showdoc_inform)

    ai_data = setting_data.get('aiSetting', setting_data.get('ai_setting', {}))
    if isinstance(ai_data, dict):
        _apply_yaml_mapping(ai_data, setting.ai_setting)

    aq_data = setting_data.get(
        'apiQueSetting', setting_data.get('api_que_setting', {}))
    if isinstance(aq_data, dict):
        _apply_yaml_mapping(aq_data, setting.api_que_setting)

    ans_data = setting_data.get(
        'answerSetting', setting_data.get('answer_setting', {}))
    setting.answer_setting = _parse_answer_setting(ans_data)

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
    """读取 LOGO 文本（兼容 PyInstaller 打包环境）"""
    if getattr(sys, "frozen", False):
        # 打包后 logo.txt 作为数据文件内置于 sys._MEIPASS/config/logo.txt
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        logo_path = Path(base) / "config" / "logo.txt"
    else:
        logo_path = Path(__file__).parent / "logo.txt"
    if logo_path.exists():
        return logo_path.read_text(encoding='utf-8')
    return ""
