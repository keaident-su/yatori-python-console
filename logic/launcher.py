# -*- coding: utf-8 -*-
"""
启动逻辑 - 对应 Go 项目的 logic/Lunch.go
包含：配置检查、IP代理检查、Web模式切换、并发刷课执行
"""
import os
import sys
import threading
from typing import List

import yaml

from config.config import (
    JSONDataForConfig, Setting, User, CoursesCustom,
    read_config, get_user_input, str_to_int
)
from utils.log import (
    log_init, log_print, string_to_log_level,
    INFO, BoldRed, Red, Yellow, Green, BoldGreen, Default
)
from utils import ip_proxy as proxy_utils
from utils.announcement import show_announcement


def file_exists(file_name: str) -> bool:
    """检查文件是否存在"""
    return os.path.isfile(file_name)


def lunch():
    """
    主启动逻辑 - 对应 Go 的 Lunch()
    1. 检查/生成配置文件
    2. 读取配置
    3. 初始化日志
    4. 配置校验
    5. IP 代理检查
    6. Web 模式判断
    7. 并发刷课
    """

    # 1. 检查 config.yaml 是否存在
    if not file_exists("./config.yaml"):
        log_print(INFO, BoldRed, """
程序未检测到config.yaml配置文件，

如果你用的配置文件生成器你确定你文件放对位置了？
以及请不要放个config（1）.yaml，config（2）.yaml这样子的的文件，要的是config.yaml。

如果使用的是控制台配置生成器的同学可以忽略此条信息。
""")
        _generate_config()

    # 2. 读取配置文件
    config_data = read_config("./config.yaml")

    # 3. 初始化日志配置
    bs = config_data.setting.basic_setting
    log_init(
        level=string_to_log_level(bs.log_level),
        log_file_sw=(bs.log_out_file_sw == 1),
        color_log=(bs.color_log == 1),
        log_dir="./assets/log"
    )

    # 4. 配置文件检查
    _config_json_check(config_data)

    # 5. 检查代理 IP
    _check_proxy_ip()

    # 6. Web 模式
    if config_data.setting.basic_setting.web_model == 1:
        _start_web_service()
    else:
        # 7. 并发刷课
        brush_block(config_data)

    log_print(INFO, Red, "Yatori --- ", "所有任务执行完毕")


def _generate_config():
    """交互式生成配置文件"""
    set_config = JSONDataForConfig()

    # 基本设置默认值
    set_config.setting.basic_setting.completion_tone = 1
    set_config.setting.basic_setting.color_log = 1
    set_config.setting.basic_setting.log_out_file_sw = 1
    set_config.setting.basic_setting.log_level = "INFO"
    set_config.setting.basic_setting.log_model = 0
    set_config.setting.ai_setting.ai_type = "TONGYI"
    set_config.setting.api_que_setting.url = "http://localhost:8083"

    # 用户交互输入
    account_type = get_user_input("请输入平台类型 (如 YINGHUA)(全大写): ")
    url = get_user_input("请输入平台的URL链接 (可留空): ")
    account = get_user_input("请输入账号: ")
    password = get_user_input("请输入密码: ")
    video_model = get_user_input("请输入刷视频模式 (0-不刷, 1-普通模式, 2-暴力模式, 3-去红模式): ")
    auto_exam = get_user_input("是否自动考试? (0-不考试, 1-AI考试, 2-外部题库对接考试): ")
    exam_auto_submit = get_user_input("考完试是否自动提交试卷? (0-否, 1-是): ")
    include_courses = get_user_input("请输入需要包含的课程名称，多个用(英文逗号)分隔(可留空): ")
    exclude_courses = get_user_input("请输入需要排除的课程名称，多个用(英文逗号)分隔(可留空): ")

    def clean_string_slice(s: str) -> List[str]:
        if not s:
            return []
        return [p.strip() for p in s.split(",") if p.strip()]

    user = User(
        account_type=account_type,
        url=url,
        account=account,
        password=password,
        courses_custom=CoursesCustom(
            video_model=str_to_int(video_model),
            auto_exam=str_to_int(auto_exam),
            exam_auto_submit=str_to_int(exam_auto_submit),
            include_courses=clean_string_slice(include_courses),
            exclude_courses=clean_string_slice(exclude_courses),
        ),
    )
    set_config.users.append(user)

    # 写入 YAML 文件
    data = _config_to_yaml_dict(set_config)
    with open("./config.yaml", 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def _config_to_yaml_dict(config: JSONDataForConfig) -> dict:
    """将配置转为可 YAML 序列化的字典"""
    users = []
    for u in config.users:
        user_dict = {
            "accountType": u.account_type,
            "url": u.url,
            "account": u.account,
            "password": u.password,
            "coursesCustom": {
                "videoModel": u.courses_custom.video_model,
                "autoExam": u.courses_custom.auto_exam,
                "examAutoSubmit": u.courses_custom.exam_auto_submit,
                "includeCourses": u.courses_custom.include_courses,
                "excludeCourses": u.courses_custom.exclude_courses,
            }
        }
        users.append(user_dict)

    return {
        "setting": {
            "basicSetting": {
                "completionTone": config.setting.basic_setting.completion_tone,
                "colorLog": config.setting.basic_setting.color_log,
                "logOutFileSw": config.setting.basic_setting.log_out_file_sw,
                "logLevel": config.setting.basic_setting.log_level,
                "logModel": config.setting.basic_setting.log_model,
            },
            "aiSetting": {
                "aiType": config.setting.ai_setting.ai_type,
            },
            "apiQueSetting": {
                "url": config.setting.api_que_setting.url,
            },
        },
        "users": users,
    }


def _config_json_check(config_data: JSONDataForConfig):
    """配置文件检测检验"""
    if len(config_data.users) == 0:
        log_print(INFO, BoldRed, "请先在config文件中配置好相应账号")
        sys.exit(0)

    for i, user in enumerate(config_data.users):
        if user.account_type in ("YINGHUA", "HQKJ"):
            if not user.url.startswith("http"):
                log_print(INFO, BoldRed,
                          f"账号{user.account}未配置正确url，请先在config文件中配置好相应账号信息")
                sys.exit(0)
            # 截取基础 URL
            parts = user.url.split("/")
            if len(parts) >= 3:
                config_data.users[i].url = "/".join(parts[:3])

        if user.is_proxy == 1:
            proxy_utils.IS_PROXY_FLAG = True


def _check_proxy_ip():
    """检查代理 IP 可用性"""
    if not proxy_utils.IS_PROXY_FLAG:
        return

    log_print(INFO, Yellow, "正在开启IP池代理...")
    log_print(INFO, Yellow, "正在检查IP池IP可用性...")

    ip_list, err = proxy_utils.ip_files_reader("./ip.txt")
    if err:
        log_print(INFO, BoldRed, "IP代理池文件ip.txt读取失败，请确认文件格式或者内容是否正确")
        sys.exit(0)

    for ip in ip_list:
        passed, state, error = proxy_utils.check_proxy_ip(ip)
        if not passed:
            log_print(INFO, f" [{ip}] ", BoldRed,
                      f"该IP代理不可用，错误信息：{error}")
            continue
        log_print(INFO, f" [{ip}] ", Green, f"检测通过，状态：{state}")
        proxy_utils.IP_PROXY_POOL.append(ip)

    log_print(INFO, BoldGreen, "IP检查完毕")

    if len(proxy_utils.IP_PROXY_POOL) == 0:
        log_print(INFO, BoldRed,
                  "无可用IP代理池，若要继续使用请先检查IP代理池文件内的IP可用性，或者在配置文件关闭IP代理功能")
        sys.exit(0)


def _start_web_service():
    """启动 Web 服务"""
    from dao.database import sqlite_init
    from global_state import global_var

    # 初始化数据库
    sqlite_init()

    # 启动 FastAPI
    import uvicorn
    from web.server import create_app

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8080)


def brush_block(config_data: JSONDataForConfig):
    """
    刷课执行块 - 对应 Go 的 brushBlock()
    使用 threading 实现多平台并发
    """
    from logic.xuexitong import part as xxt
    from logic.yinghua import part as yinghua
    from logic.enaea import part as enaea
    from logic.cqie import part as cqie
    from logic.ketangx import part as ketangx
    from logic.icve import part as icve
    from logic.qingshuxuetang import part as qsxt
    from logic.welearn import part as welearn
    from logic.haiqikeji import part as hqkj

    # 统一登录模块
    platforms = [
        ("YINGHUA", yinghua),
        ("ENAEA", enaea),
        ("CQIE", cqie),
        ("XUEXITONG", xxt),
        ("KETANGX", ketangx),
        ("WELEARN", welearn),
        ("ICVE", icve),
        ("QSXT", qsxt),
        ("HQKJ", hqkj),
    ]

    platform_data = []
    for name, mod in platforms:
        accounts = mod.filter_account(config_data)
        caches = mod.user_login_operation(accounts)
        platform_data.append(
            (name, mod, config_data.setting, accounts, caches))

    # 统一刷课 - 并发执行
    threads = []
    for name, mod, setting, accounts, caches in platform_data:
        t = threading.Thread(
            target=mod.run_brush_operation,
            args=(setting, accounts, caches),
            daemon=True,
        )
        threads.append(t)
        t.start()

    # 等待所有平台完成
    for t in threads:
        t.join()
