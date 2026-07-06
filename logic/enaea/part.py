# -*- coding: utf-8 -*-
"""
学习公社平台逻辑 - 对应 Go 项目的 logic/enaea/EnaeaPart.go
完整实现：登录、项目→课程→视频三层结构、25秒提交间隔
"""
from utils.log import log_print, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import threading
import time
import json
from typing import List, Any, Optional

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.enaea.models import EnaeaUserCache, EnaeaProject, EnaeaCourse, EnaeaVideo
from logic.enaea import api as enaea_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, DEBUG,
    Green, Yellow, Red, Blue, Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "ENAEA"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


# ============ 登录 ============

def _enaea_login_action(cache: EnaeaUserCache) -> Optional[Exception]:
    """登录聚合"""
    body, resp = enaea_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data is None:
        return Exception("登录响应解析失败")
    if data.get("status") == True or data.get("code") == 0:
        # 保存 session
        if resp and hasattr(resp, 'cookies'):
            for name, value in resp.cookies.items():
                cache.session_id = value
        return None
    msg = data.get("msg", data.get("message", "未知错误"))
    return Exception(f"登录失败: {msg}")


def _login_timeout_afresh(cache: EnaeaUserCache, err):
    """失效重登"""
    err_str = str(err) if err else ""
    if "失效" not in err_str and "timeout" not in err_str.lower() and "unauthorized" not in err_str.lower():
        return
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              BoldRed, "检测到会话失效，正在重新登录...")
    e = _enaea_login_action(cache)
    if e:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  BoldRed, f"重登失败: {e}")


def user_login_operation(users: List[User]) -> List[EnaeaUserCache]:
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = EnaeaUserCache(account=user.account, password=user.password)
        err = _enaea_login_action(cache)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, user.account, Default, "] ",
                      Red, str(err))
            raise SystemExit(str(err))
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[" + cache.account + "] ", Green, "登录成功")
        user_caches.append(cache)
    return user_caches


# ============ 刷课 ============

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


def _user_block(setting: Setting, user: User, cache: EnaeaUserCache):
    """项目→课程→视频三层刷课"""
    # 拉取项目列表
    proj_body, _ = enaea_api.project_list_api(cache, retry=8)
    proj_data = safe_json_parse(proj_body)
    projects = []
    if proj_data:
        for item in json_get(proj_data, "data", "list", default=[]):
            if isinstance(item, dict):
                projects.append(EnaeaProject(
                    circle_id=str(item.get("circleId", "")),
                    cluster_name=item.get("clusterName", ""),
                ))

    cc = user.courses_custom
    # 解析课程过滤规则（支持 "项目名-->课程名" 格式）
    exclude_projects, include_projects = [], []
    exclude_courses_sub, include_courses_sub = [], []
    for c in cc.exclude_courses:
        parts = c.split("-->")
        exclude_projects.append(parts[0])
        if len(parts) >= 2:
            exclude_courses_sub.append(parts[0])
    for c in cc.include_courses:
        parts = c.split("-->")
        include_projects.append(parts[0])
        if len(parts) >= 2:
            include_courses_sub.append(parts[1])

    for project in projects:
        if exclude_projects and cmp_course(project.cluster_name, exclude_projects):
            continue
        if include_projects and not cmp_course(project.cluster_name, include_projects):
            continue

        # 拉取课程列表
        course_body, _ = enaea_api.course_list_api(
            cache, project.circle_id, retry=8)
        course_data = safe_json_parse(course_body)
        courses = []
        if course_data:
            for item in json_get(course_data, "data", "list", default=[]):
                if isinstance(item, dict):
                    courses.append(EnaeaCourse(
                        id=str(item.get("courseId", "")),
                        title_tag=item.get("titleTag", ""),
                        course_title=item.get("courseTitle", ""),
                        course_id=str(item.get("courseId", "")),
                        circle_id=project.circle_id,
                    ))

        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  Purple, f"正在学习项目 【{project.cluster_name}】")

        for course in courses:
            if exclude_courses_sub and cmp_course(course.title_tag, exclude_courses_sub):
                continue
            if include_courses_sub and not cmp_course(course.title_tag, include_courses_sub):
                continue
            _node_list_study(setting, user, cache, course)

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              Purple, "所有待学习课程学习完毕")
    generic_user_block(
        setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], brush_func=None)


def _node_list_study(setting: Setting, user: User, cache: EnaeaUserCache, course: EnaeaCourse):
    """课程节点学习"""
    vid_body, _ = enaea_api.video_list_api(cache, course.course_id, retry=8)
    vid_data = safe_json_parse(vid_body)
    videos = []
    if vid_data:
        for item in json_get(vid_data, "data", "contentList", default=[]):
            if isinstance(item, dict):
                videos.append(EnaeaVideo(
                    id=str(item.get("contentId", "")),
                    title_tag=course.title_tag,
                    course_name=course.course_title,
                    course_content_str=item.get("contentTitle", ""),
                    study_progress=float(item.get("studyProgress", 0)),
                    course_id=course.course_id,
                    content_id=str(item.get("contentId", "")),
                    cc_video_id=str(item.get("ccVideoId", "")),
                ))

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                f"正在学习课程：", Yellow, f"【{course.title_tag}】【{course.course_title}】")

    for video in videos:
        _video_action(setting, user, cache, video)

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Green, f"课程 【{course.title_tag}】【{course.course_title}】 学习完毕")


def _video_action(setting: Setting, user: User, cache: EnaeaUserCache, node: EnaeaVideo):
    """刷视频"""
    cc = user.courses_custom
    if cc.video_model == 0:
        return

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, "正在学习视频：", Default,
                f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】 ")

    # CC视频统计初始化
    if node.cc_video_id:
        enaea_api.statistic_tic_cc_video_api(
            cache, node.cc_video_id, node.content_id, node.course_id)

    while True:
        if node.study_progress >= 100:
            model_print(setting.basic_setting.log_model == 0,
                        INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                        "[", Green, cache.account, Default, "] ",
                        f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】",
                        Blue, " 学习完毕")
            break

        if cc.video_model == 1:
            study_time = int(time.time() * 1000)
            is_finish = 0
        else:
            study_time = 60
            is_finish = 1

        body, _ = enaea_api.submit_study_time_api(
            cache, node.content_id, node.course_id, study_time, is_finish, retry=8)

        # 更新进度
        resp_data = safe_json_parse(body)
        if resp_data:
            progress = json_get(resp_data, "data",
                                "studyProgress", default=None)
            if progress is not None:
                node.study_progress = float(progress)

        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】 >>> ",
                    f"提交状态：成功 ", f"观看进度：{node.study_progress:.2f}%")

        time.sleep(25)
        if node.study_progress >= 100:
            break


"""
学习公社平台逻辑 - 对应 Go 项目的 logic/enaea/EnaeaPart.go
"""

PLATFORM_TYPE = "ENAEA"


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
