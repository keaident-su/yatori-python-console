# -*- coding: utf-8 -*-
"""
重庆工程学院平台逻辑 - 对应 Go 项目的 logic/cqie/CqiePart.go
完整实现：登录、课程列表、视频列表、普通+秒刷暴力模式
"""
from utils.log import log_print, with_log_account, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import threading
import time
from datetime import datetime
from typing import List, Any, Optional

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.cqie.models import CqieUserCache, CqieCourse, CqieVideo
from logic.cqie import api as cqie_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, DEBUG,
    Green, Yellow, Red, Blue, Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "CQIE"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


def _cqie_login_action(cache: CqieUserCache) -> Optional[Exception]:
    body, resp = cqie_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data is None:
        return Exception("登录响应解析失败")
    if data.get("code") == 200 or data.get("status") == True:
        sid = json_get(data, "data", "studyId", default="")
        if sid:
            cache.study_id = str(sid)
        return None
    return Exception(f"登录失败: {data.get('msg', '未知错误')}")


def user_login_operation(users: List[User]) -> List[CqieUserCache]:
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = CqieUserCache(account=user.account, password=user.password)
        err = _cqie_login_action(cache)
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
        t = threading.Thread(
            target=with_log_account(users[i].account, users[i].remark_name)(_user_block),
            args=(setting, users[i], cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def _user_block(setting: Setting, user: User, cache: CqieUserCache):
    course_body, _ = cqie_api.course_list_api(cache, retry=8)
    # 夜间休息检查(2026-10-10 修复): 入口级——休息时段内等待到点继续
    try:
        from logic.platform_common import rest_wait_if_needed as _pub_rest_wait
        _pub_rest_wait(user.account, user.courses_custom,
                       ACCOUNT_TYPE_STR[PLATFORM_TYPE])
    except Exception:
        pass
    course_data = safe_json_parse(course_body)
    courses = []
    if course_data:
        for item in json_get(course_data, "data", "list", default=[]):
            if isinstance(item, dict):
                courses.append(CqieCourse(
                    course_id=str(item.get("courseId", "")),
                    course_name=item.get("courseName", ""),
                ))

    video_threads = []
    for course in courses:
        # 夜间休息检查(2026-10-10 修复: 课程级——刷课中途到点即停,恢复后继续)
        try:
            from logic.platform_common import rest_wait_if_needed as _pub_rest_wait
            _pub_rest_wait(user.account, user.courses_custom,
                           ACCOUNT_TYPE_STR[PLATFORM_TYPE])
        except Exception:
            pass
        cc = user.courses_custom
        if cc.exclude_courses and cmp_course(course.course_name, cc.exclude_courses):
            continue
        if cc.include_courses and not cmp_course(course.course_name, cc.include_courses):
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


def _node_list_study(setting: Setting, user: User, cache: CqieUserCache, course: CqieCourse):
    vid_body, _ = cqie_api.video_list_api(cache, course.course_id, retry=8)
    vid_data = safe_json_parse(vid_body)
    videos = []
    if vid_data:
        for item in json_get(vid_data, "data", "list", default=[]):
            if isinstance(item, dict):
                videos.append(CqieVideo(
                    id=str(item.get("videoId", "")),
                    video_name=item.get("videoName", ""),
                    time_length=int(item.get("timeLength", 0)),
                    study_time=int(item.get("studyTime", 0)),
                    study_id=str(item.get("studyId", "")),
                ))

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                f"正在学习课程：", Yellow, f"【{course.course_name}】")

    cc = user.courses_custom
    for video in videos:
        if cc.video_model == 1:
            _video_action(setting, user, cache, video)
        elif cc.video_model == 2:
            _video_action_second_brush(setting, user, cache, video)

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Green, f"课程【{course.course_name}】 学习完毕")


def _video_action(setting: Setting, user: User, cache: CqieUserCache, node: CqieVideo):
    """普通模式"""
    if user.courses_custom.video_model == 0:
        return
    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, "正在学习视频：", Default, f"【{node.video_name}】")

    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_pos = node.study_time
    stop_pos = node.study_time
    max_pos = node.study_time

    # 先保存学习点
    save_body, _ = cqie_api.save_video_study_time_api(
        cache, node.id, start_pos, stop_pos)
    save_data = safe_json_parse(save_body)
    if save_data:
        sid = json_get(save_data, "data", "studyId", default="")
        if sid:
            node.study_id = str(sid)

    while True:
        if max_pos >= node.time_length + 3:
            break
        if stop_pos >= max_pos:
            max_pos = start_pos + 3

        sub_body, _ = cqie_api.submit_study_time_api(
            cache, node.id, node.study_id, now_time, start_pos, stop_pos, max_pos)
        sub_data = safe_json_parse(sub_body)
        if sub_data:
            new_study = json_get(sub_data, "data", "studyTime", default=None)
            if new_study is not None:
                node.study_time = int(new_study)

        progress = (node.study_time / node.time_length *
                    100) if node.time_length > 0 else 0
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{node.video_name}】 >>> 提交状态：成功 观看进度：{progress:.2f}%")
        start_pos += 3
        stop_pos += 3
        time.sleep(3)

    # 最后保存
    cqie_api.save_video_study_time_api(cache, node.id, start_pos, stop_pos)
    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, f"视频：【{node.video_name}】 ", Green, "学习完毕")


def _video_action_second_brush(setting: Setting, user: User, cache: CqieUserCache, node: CqieVideo):
    """秒刷暴力模式"""
    if user.courses_custom.video_model == 0:
        return
    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_pos = node.study_time
    stop_pos = node.study_time

    save_body, _ = cqie_api.save_video_study_time_api(
        cache, node.id, start_pos, stop_pos)
    save_data = safe_json_parse(save_body)
    if save_data:
        sid = json_get(save_data, "data", "studyId", default="")
        if sid:
            node.study_id = str(sid)

    max_pos = start_pos
    cqie_api.submit_study_time_api(
        cache, node.id, node.study_id, now_time, start_pos, stop_pos, max_pos)
    cqie_api.save_video_study_time_api(cache, node.id, start_pos, stop_pos)

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, f"视频：【{node.video_name}】 ", Green, "学习完毕")


"""
重庆工程学院平台逻辑 - 对应 Go 项目的 logic/cqie/CqiePart.go
"""

PLATFORM_TYPE = "CQIE"


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


def web_course_list(cache: CqieUserCache, user: User) -> List[dict]:
    """Web端课程列表+总进度(按视频节点完成度统计)"""
    body, _ = cqie_api.course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    result = []
    for item in _web_iter_list(data):
        if not isinstance(item, dict):
            continue
        cid = str(item.get("courseId", ""))
        fin, total, has = 0, 0, False
        try:
            vbody, _ = cqie_api.video_list_api(cache, cid, retry=3)
            vdata = safe_json_parse(vbody)
            for n in _web_iter_list(vdata):
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
            "courseName": item.get("courseName", ""),
            "teacher": "",
            "jobFinishCount": fin,
            "jobCount": total,
            "jobRate": rate,
            "hasProgress": has,
            "statusText": ("已完成" if (total and fin >= total)
                           else ("进行中" if has else "")),
        })
    return result
