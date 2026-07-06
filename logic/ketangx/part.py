# -*- coding: utf-8 -*-
"""
码上研训平台逻辑 - 对应 Go 项目的 logic/ketangx/KetangxPart.go
秒刷 CompleteVideoAction
"""
from utils.log import log_print, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import threading
from typing import List, Any, Optional

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.ketangx.models import KetangxUserCache, KetangxCourse, KetangxNode
from logic.ketangx import api as ketangx_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, DEBUG,
    Green, Yellow, Red, Blue, Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "KETANGX"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


def _login_action(cache: KetangxUserCache) -> Optional[Exception]:
    body, _ = ketangx_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data and (data.get("code") == 200 or data.get("Success") is True):
        return None
    return Exception(f"登录失败: {data.get('msg', data.get('Message', '未知错误')) if data else '解析失败'}")


def user_login_operation(users: List[User]) -> List[KetangxUserCache]:
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = KetangxUserCache(account=user.account, password=user.password)
        err = _login_action(cache)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, user.account, Default, "] ", Red, str(err))
            raise SystemExit(str(err))
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


def _user_block(setting: Setting, user: User, cache: KetangxUserCache):
    body, _ = ketangx_api.course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    courses = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                courses.append(KetangxCourse(
                    id=str(item.get("courseId", "")),
                    title=item.get("title", ""),
                ))

    video_threads = []
    for course in courses:
        cc = user.courses_custom
        if cc.exclude_courses and cmp_course(course.title, cc.exclude_courses):
            continue
        if cc.include_courses and not cmp_course(course.title, cc.include_courses):
            continue
        t = threading.Thread(target=_node_list_study, args=(
            setting, user, cache, course), daemon=True)
        video_threads.append(t)
        t.start()
    for t in video_threads:
        t.join()

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ", Purple, "所有待学习课程学习完毕")
    generic_user_block(
        setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], brush_func=None)


def _node_list_study(setting: Setting, user: User, cache: KetangxUserCache, course: KetangxCourse):
    body, _ = ketangx_api.node_list_api(cache, course.id, retry=8)
    data = safe_json_parse(body)
    nodes = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                nodes.append(KetangxNode(
                    id=str(item.get("nodeId", item.get("id", ""))),
                    title=item.get("title", ""),
                    type=item.get("type", ""),
                    is_complete=bool(item.get("isComplete", False)),
                    course_id=course.id,
                ))

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                f"正在学习课程：", Yellow, f"【{course.title}】")

    for node in nodes:
        _video_action(setting, user, cache, course, node)

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Green, f"课程【{course.title}】 学习完毕")


def _video_action(setting: Setting, user: User, cache: KetangxUserCache,
                  course: KetangxCourse, node: KetangxNode):
    if user.courses_custom.video_model == 0:
        return
    if node.is_complete:
        return

    body, _ = ketangx_api.complete_video_action_api(
        cache, node.id, course.id, retry=8)
    data = safe_json_parse(body)
    if data and data.get("Success") is True:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  f"【{course.title}】 【{node.title}】",
                  f"结点类型: <{Yellow}{node.type}{Default}> ",
                  Green, "学习完毕")
    else:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  f"【{course.title}】 【{node.title}】",
                  BoldRed, f"结点类型: <{node.type}> 学习异常：{body}")


"""
码上研训平台逻辑 - 对应 Go 项目的 logic/ketangx/KetangxPart.go
"""

PLATFORM_TYPE = "KETANGX"


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
