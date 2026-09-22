# -*- coding: utf-8 -*-
"""
智慧职教平台逻辑 - 对应 Go 项目的 logic/icve/IcvePart.go
Cookie/密码双登录，资源库课程，秒刷SubmitZYKStudyTimeAction
"""
from utils.log import log_print, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import threading
from typing import List, Any, Optional

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.icve.models import IcveUserCache, IcveCourse, IcveNode
from logic.icve import api as icve_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, Green, Yellow, Red, Blue,
    Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "ICVE"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


def _login_action(cache: IcveUserCache) -> Optional[Exception]:
    # 密码长度>=50认为是Cookie登录
    if len(cache.password) >= 50:
        cache.is_cookie_login = True
        cache.cookie_str = cache.password
        return None
    body, _ = icve_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data and (data.get("code") == 200 or data.get("status") is True):
        return None
    return Exception(f"登录失败: {data.get('msg', '未知错误') if data else '解析失败'}")


def user_login_operation(users: List[User]) -> List[IcveUserCache]:
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = IcveUserCache(account=user.account, password=user.password)
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


def _user_block(setting: Setting, user: User, cache: IcveUserCache):
    body, _ = icve_api.zyk_course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    courses = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                courses.append(IcveCourse(
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


def _node_list_study(setting: Setting, user: User, cache: IcveUserCache, course: IcveCourse):
    body, _ = icve_api.zyk_node_list_api(cache, course.id, retry=8)
    data = safe_json_parse(body)
    nodes = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                nodes.append(IcveNode(
                    id=str(item.get("id", "")),
                    node_name=item.get("name", ""),
                    progress=float(item.get("progress", 0)),
                    total_time=int(item.get("totalTime", 0)),
                    course_id=course.id,
                    audio_video_id=str(item.get("audioVideoId", "")),
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


def _video_action(setting: Setting, user: User, cache: IcveUserCache,
                  course: IcveCourse, node: IcveNode):
    """秒刷模式"""
    if user.courses_custom.video_model == 0:
        return
    if node.progress >= 100:
        return
    body, _ = icve_api.submit_zyk_study_time_api(
        cache, node.audio_video_id, node.total_time, course.id, retry=8)
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              f"【{course.course_name}】【{node.node_name}】",
              Green, " 秒刷提交完毕")


"""
智慧职教平台逻辑 - 对应 Go 项目的 logic/icve/IcvePart.go
"""

PLATFORM_TYPE = "ICVE"


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


# ============ Web 端课程查询(供前端控制台"课程"按钮) ============

def _web_iter_list(data):
    """兼容 data.list / list / data(数组) 多种列表结构"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    node = data.get("data")
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        inner = node.get("list")
        if isinstance(inner, list):
            return inner
    inner = data.get("list")
    return inner if isinstance(inner, list) else []


def _web_node_progress(item: dict) -> float:
    """兼容多平台的节点完成度字段(0-100)"""
    for k in ("progress", "studyProgress", "completeRate", "schedule"):
        try:
            v = float(item.get(k, 0) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    if item.get("finished") in (1, True, "1"):
        return 100.0
    if item.get("completeStatus") in (1, "1", "finished"):
        return 100.0
    return 0.0


def web_course_list(cache: IcveUserCache, user: User) -> List[dict]:
    """Web端课程列表+总进度(按节点完成度统计)"""
    body, _ = icve_api.zyk_course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    result = []
    for item in _web_iter_list(data):
        if not isinstance(item, dict):
            continue
        cid = str(item.get("courseId", "") or item.get("id", ""))
        fin, total, has = 0, 0, False
        try:
            nbody, _ = icve_api.zyk_node_list_api(cache, cid, retry=3)
            ndata = safe_json_parse(nbody)
            for n in _web_iter_list(ndata):
                if not isinstance(n, dict):
                    continue
                total += 1
                has = True
                if _web_node_progress(n) >= 100:
                    fin += 1
        except Exception:
            pass
        rate = round(fin / total * 100, 1) if total else 0.0
        result.append({
            "courseId": cid,
            "courseName": item.get("courseName", "") or item.get("name", ""),
            "teacher": "",
            "jobFinishCount": fin,
            "jobCount": total,
            "jobRate": rate,
            "hasProgress": has,
            "statusText": ("已完成" if (total and fin >= total)
                           else ("进行中" if has else "")),
        })
    return result
