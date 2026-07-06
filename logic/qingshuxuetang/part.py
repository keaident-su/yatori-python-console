# -*- coding: utf-8 -*-
"""
青书学堂平台逻辑 - 对应 Go 项目的 logic/qingshuxuetang/QsxtPart.go
课件视频+课程资料双轨道，60秒间隔提交，作业自动完成
"""
from utils.log import log_print, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import threading
import time
from typing import List, Any, Optional

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.qingshuxuetang.models import QsxtUserCache, QsxtCourse, QsxtNode
from logic.qingshuxuetang import api as qsxt_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, Green, Yellow, Red, Blue,
    Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "QSXT"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


def _login_action(cache: QsxtUserCache) -> Optional[Exception]:
    body, _ = qsxt_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data and (data.get("code") == 200 or data.get("status") is True):
        return None
    return Exception(f"登录失败: {data.get('msg', '未知错误') if data else '解析失败'}")


def user_login_operation(users: List[User]) -> List[QsxtUserCache]:
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = QsxtUserCache(account=user.account, password=user.password)
        err = _login_action(cache)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, user.account, Default, "] ", Red, str(err))
            raise SystemExit(str(err))
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[" + cache.account + "] ", Green, "登录成功")
        user_caches.append(cache)
    return user_caches


def run_brush_operation(setting: Setting, users: List[User], user_caches: List[Any]):
    threads = []
    for i, cache in enumerate(user_caches):
        if i >= len(users):
            break
        t = threading.Thread(target=_user_block, args=(
            setting, users[i], cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def _user_block(setting: Setting, user: User, cache: QsxtUserCache):
    body, _ = qsxt_api.course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    courses = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                courses.append(QsxtCourse(
                    id=str(item.get("courseId", "")),
                    course_name=item.get("courseName", ""),
                ))

    cc = user.courses_custom
    for course in courses:
        if cc.exclude_courses and cmp_course(course.course_name, cc.exclude_courses):
            continue
        if cc.include_courses and not cmp_course(course.course_name, cc.include_courses):
            continue
        _node_list_study(setting, user, cache, course)

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ", Purple, "所有待学习课程学习完毕")
    generic_user_block(
        setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], brush_func=None)


def _node_list_study(setting: Setting, user: User, cache: QsxtUserCache, course: QsxtCourse):
    body, _ = qsxt_api.node_list_api(cache, course.id, retry=8)
    data = safe_json_parse(body)
    nodes = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                nodes.append(QsxtNode(
                    id=str(item.get("nodeId", "")),
                    node_name=item.get("name", ""),
                    node_type=item.get("type", "video"),
                    progress=float(item.get("progress", 0)),
                    total_time=int(item.get("totalTime", 0)),
                    studied_time=int(item.get("studiedTime", 0)),
                    course_id=course.id,
                    chapter_id=str(item.get("chapterId", "")),
                ))

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                f"正在学习课程：", Yellow, f"【{course.course_name}】")

    for node in nodes:
        _video_action(setting, user, cache, course, node)

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Green, f"课程【{course.course_name}】 学习完毕")


def _video_action(setting: Setting, user: User, cache: QsxtUserCache,
                  course: QsxtCourse, node: QsxtNode):
    if user.courses_custom.video_model == 0:
        return
    if node.progress >= 100:
        return

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, f"正在学习：", Default,
                f"【{course.course_name}】【{node.node_name}】")

    # 开始学习
    qsxt_api.start_study_time_api(cache, node.id, course.id)

    current_time = node.studied_time
    while current_time < node.total_time:
        current_time += 60
        if current_time > node.total_time:
            current_time = node.total_time

        is_finish = current_time >= node.total_time
        body, _ = qsxt_api.submit_study_time_api(
            cache, node.id, course.id, current_time, is_finish, retry=8)

        resp_data = safe_json_parse(body)
        if resp_data:
            p = json_get(resp_data, "data", "progress", default=None)
            if p is not None:
                node.progress = float(p)

        progress_pct = (current_time / node.total_time *
                        100) if node.total_time > 0 else 0
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{course.course_name}】【{node.node_name}】 >>> ",
                    f"观看时间：{current_time}/{node.total_time} ",
                    f"进度：{progress_pct:.2f}%")

        if is_finish:
            break
        time.sleep(60)

    # 最终提交
    qsxt_api.submit_study_time_api(
        cache, node.id, course.id, node.total_time, True)
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              f"【{course.course_name}】【{node.node_name}】",
              Green, " 学习完毕")


"""
青书学堂平台逻辑 - 对应 Go 项目的 logic/qingshuxuetang/QsxtPart.go
"""

PLATFORM_TYPE = "QSXT"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


def user_login_operation(users: List[User]) -> List[Any]:
    user_caches = []
    for user in users:
        if user.account_type == PLATFORM_TYPE:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, user.account, Default, "] ", Yellow, "登录功能待实现")
            user_caches.append({"user": user, "cache": None})
    return user_caches


def run_brush_operation(setting: Setting, users: List[User], user_caches: List[Any]):
    threads = []
    for i, cache_item in enumerate(user_caches):
        t = threading.Thread(target=generic_user_block, args=(
            setting, users[i], ACCOUNT_TYPE_STR[PLATFORM_TYPE]), kwargs={"brush_func": None}, daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
