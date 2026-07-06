# -*- coding: utf-8 -*-
"""
WeLearn平台逻辑 - 对应 Go 项目的 logic/welearn/WeLearnPart.go
两种模式：模式1累计学时（60秒间隔），模式2完成度
"""
from utils.log import log_print, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import random
import threading
import time
from typing import List, Any, Optional

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.welearn.models import WeLearnUserCache, WeLearnCourse, WeLearnNode
from logic.welearn import api as welearn_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, Green, Yellow, Red, Blue,
    Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "WELEARN"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


def _login_action(cache: WeLearnUserCache) -> Optional[Exception]:
    body, _ = welearn_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data and (data.get("code") == 200 or data.get("status") is True):
        cache.uid = str(json_get(data, "data", "uid", default=""))
        return None
    return Exception(f"登录失败: {data.get('msg', '未知错误') if data else '解析失败'}")


def user_login_operation(users: List[User]) -> List[WeLearnUserCache]:
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = WeLearnUserCache(account=user.account, password=user.password)
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


def _user_block(setting: Setting, user: User, cache: WeLearnUserCache):
    body, _ = welearn_api.course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    courses = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                courses.append(WeLearnCourse(
                    id=str(item.get("courseId", "")),
                    course_name=item.get("courseName", ""),
                    study_plan_id=str(item.get("studyPlanId", "")),
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


def _node_list_study(setting: Setting, user: User, cache: WeLearnUserCache, course: WeLearnCourse):
    body, _ = welearn_api.study_plan_api(cache, course.id, retry=8)
    data = safe_json_parse(body)
    nodes = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                nodes.append(WeLearnNode(
                    id=str(item.get("id", "")),
                    node_name=item.get("name", ""),
                    progress=float(item.get("progress", 0)),
                    total_time=int(item.get("totalTime", 0)),
                    studied_time=int(item.get("studiedTime", 0)),
                    course_id=course.id,
                    scorm_id=str(item.get("scormId", "")),
                ))

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                f"正在学习课程：", Yellow, f"【{course.course_name}】")

    cc = user.courses_custom
    for node in nodes:
        if cc.video_model == 1:
            _video_time_mode(setting, user, cache, course, node)
        elif cc.video_model == 2:
            _video_progress_mode(setting, user, cache, course, node)

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Green, f"课程【{course.course_name}】 学习完毕")


def _video_time_mode(setting: Setting, user: User, cache: WeLearnUserCache,
                     course: WeLearnCourse, node: WeLearnNode):
    """模式1：累计学时（60秒间隔）"""
    if node.progress >= 100:
        return
    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, "正在学习：", Default, f"【{course.course_name}】【{node.node_name}】")

    # 解析 study_time 配置（范围格式 "60-120"）
    cc = user.courses_custom
    min_time, max_time = 60, 60
    if cc.study_time and "-" in cc.study_time:
        parts = cc.study_time.split("-")
        try:
            min_time = int(parts[0])
            max_time = int(parts[1])
        except (ValueError, IndexError):
            pass

    while node.progress < 100:
        study_time = random.randint(min_time, max_time)
        welearn_api.keep_point_session_api(cache, node.scorm_id, study_time)
        body, _ = welearn_api.submit_study_plan_api(
            cache, node.scorm_id, 100, study_time)
        resp_data = safe_json_parse(body)
        if resp_data:
            p = json_get(resp_data, "data", "progress", default=None)
            if p is not None:
                node.progress = float(p)

        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{course.course_name}】【{node.node_name}】 >>> ",
                    f"提交学时：{study_time}秒 进度：{node.progress:.2f}%")
        if node.progress >= 100:
            break
        time.sleep(60)


def _video_progress_mode(setting: Setting, user: User, cache: WeLearnUserCache,
                         course: WeLearnCourse, node: WeLearnNode):
    """模式2：完成度模式（直接提交100%）"""
    if node.progress >= 100:
        return
    body, _ = welearn_api.submit_study_plan_api(
        cache, node.scorm_id, 100, node.total_time)
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              f"【{course.course_name}】【{node.node_name}】",
              Green, " 完成度模式提交完毕")


"""
WeLearn平台逻辑 - 对应 Go 项目的 logic/welearn/WeLearnPart.go
"""

PLATFORM_TYPE = "WELEARN"


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
