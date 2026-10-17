# -*- coding: utf-8 -*-
"""
海旗科技平台逻辑 - 对应 Go 项目的 logic/haiqikeji/HqkjPart.go
普通模式（30秒间隔）+快速模式（并发提交100%）、作业/考试AI自动答题
"""
from utils.log import log_print, with_log_account, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import threading
import time
import concurrent.futures
from typing import List, Any, Optional

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.haiqikeji.models import HqkjUserCache, HqkjCourse, HqkjNode
from logic.haiqikeji import api as hqkj_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from logic.core import parallel as _par  # 动态并发取值(全速开关/档位/运行期微调)
from utils.log import (
    log_print, model_print, INFO, Green, Yellow, Red, Blue,
    Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "HQKJ"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


def _login_action(cache: HqkjUserCache) -> Optional[Exception]:
    body, _ = hqkj_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data and (data.get("code") == 200 or data.get("status") is True):
        uid = json_get(data, "data", "userId", default="")
        if uid:
            cache.user_id = str(uid)
        return None
    return Exception(f"登录失败: {data.get('msg', '未知错误') if data else '解析失败'}")


def user_login_operation(users: List[User]) -> List[HqkjUserCache]:
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = HqkjUserCache(
            pre_url=user.url,
            account=user.account,
            password=user.password,
        )
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
        t = threading.Thread(
            target=with_log_account(users[i].account, users[i].remark_name)(_user_block),
            args=(setting, users[i], cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def _user_block(setting: Setting, user: User, cache: HqkjUserCache):
    body, _ = hqkj_api.course_list_api(cache, retry=8)
    # 夜间休息检查(2026-10-10 修复): 入口级——休息时段内等待到点继续
    try:
        from logic.platform_common import rest_wait_if_needed as _pub_rest_wait
        _pub_rest_wait(user.account, user.courses_custom,
                       ACCOUNT_TYPE_STR[PLATFORM_TYPE])
    except Exception:
        pass
    data = safe_json_parse(body)
    courses = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                courses.append(HqkjCourse(
                    id=str(item.get("courseId", "")),
                    course_name=item.get("courseName", ""),
                ))

    cc = user.courses_custom
    for course in courses:
        # 夜间休息检查(2026-10-10 修复: 课程级——刷课中途到点即停,恢复后继续)
        try:
            from logic.platform_common import rest_wait_if_needed as _pub_rest_wait
            _pub_rest_wait(user.account, user.courses_custom,
                           ACCOUNT_TYPE_STR[PLATFORM_TYPE])
        except Exception:
            pass
        if cc.exclude_courses and cmp_course(course.course_name, cc.exclude_courses):
            continue
        if cc.include_courses and not cmp_course(course.course_name, cc.include_courses):
            continue
        _node_list_study(setting, user, cache, course)

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ", Purple, "所有待学习课程学习完毕")
    generic_user_block(
        setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], brush_func=None)


def _node_list_study(setting: Setting, user: User, cache: HqkjUserCache, course: HqkjCourse):
    body, _ = hqkj_api.node_list_api(cache, course.id, retry=8)
    data = safe_json_parse(body)
    nodes = []
    if data:
        for item in json_get(data, "data", "list", default=[]):
            if isinstance(item, dict):
                nodes.append(HqkjNode(
                    id=str(item.get("nodeId", "")),
                    node_name=item.get("name", ""),
                    progress=float(item.get("progress", 0)),
                    total_time=int(item.get("totalTime", 0)),
                    studied_time=int(item.get("studiedTime", 0)),
                    course_id=course.id,
                    video_id=str(item.get("videoId", "")),
                ))

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                f"正在学习课程：", Yellow, f"【{course.course_name}】")

    cc = user.courses_custom
    if cc.video_model == 1:
        # 普通模式：30秒间隔
        for node in nodes:
            _video_normal_mode(setting, user, cache, course, node)
    elif cc.video_model == 2:
        # 快速模式：并发提交100%（多核优化：并发数随CPU核心数动态扩展）
        with concurrent.futures.ThreadPoolExecutor(max_workers=_par.tuned_fast_video_workers()) as executor:
            futures = []
            for node in nodes:
                f = executor.submit(_video_fast_mode, setting,
                                    user, cache, course, node)
                futures.append(f)
            for f in concurrent.futures.as_completed(futures):
                pass

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Green, f"课程【{course.course_name}】 学习完毕")


def _video_normal_mode(setting: Setting, user: User, cache: HqkjUserCache,
                       course: HqkjCourse, node: HqkjNode):
    """普通模式：30秒间隔，StartStudy→SubmitStudyTime→EndStudy→验证"""
    if node.progress >= 100:
        return

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, f"正在学习：", Default,
                f"【{course.course_name}】【{node.node_name}】")

    # 开始学习
    hqkj_api.start_study_api(cache, node.video_id, course.id)

    current_time = node.studied_time
    while current_time < node.total_time:
        current_time += 30
        if current_time > node.total_time:
            current_time = node.total_time

        progress = int(current_time / node.total_time *
                       100) if node.total_time > 0 else 100
        body, _ = hqkj_api.submit_study_time_api(
            cache, node.video_id, course.id, current_time, progress, retry=8)

        resp_data = safe_json_parse(body)
        if resp_data:
            p = json_get(resp_data, "data", "progress", default=None)
            if p is not None:
                node.progress = float(p)

        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{course.course_name}】【{node.node_name}】 >>> ",
                    f"观看时间：{current_time}/{node.total_time} ",
                    f"进度：{progress}%")

        if current_time >= node.total_time:
            break
        time.sleep(30)

    # 结束学习
    hqkj_api.end_study_api(cache, node.video_id, course.id)
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              f"【{course.course_name}】【{node.node_name}】",
              Green, " 学习完毕")


def _video_fast_mode(setting: Setting, user: User, cache: HqkjUserCache,
                     course: HqkjCourse, node: HqkjNode):
    """快速模式：并发提交100%进度"""
    if node.progress >= 100:
        return

    # 直接提交100%
    hqkj_api.start_study_api(cache, node.video_id, course.id)
    hqkj_api.submit_study_time_api(
        cache, node.video_id, course.id, node.total_time, 100, retry=8)
    hqkj_api.end_study_api(cache, node.video_id, course.id)

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              f"【{course.course_name}】【{node.node_name}】",
              Green, " 快速模式提交完毕")


"""
海旗科技平台逻辑 - 对应 Go 项目的 logic/haiqikeji/HqkjPart.go
"""

PLATFORM_TYPE = "HQKJ"


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

def web_course_list(cache: HqkjUserCache, user: User) -> List[dict]:
    """Web端课程列表+总进度(按节点 progress>=100 统计任务点完成数)"""
    body, _ = hqkj_api.course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    result = []
    if not data:
        return result
    for item in json_get(data, "data", "list", default=[]):
        if not isinstance(item, dict):
            continue
        cid = str(item.get("courseId", ""))
        cname = item.get("courseName", "")
        fin, total, has = 0, 0, False
        try:
            nbody, _ = hqkj_api.node_list_api(cache, cid, retry=3)
            ndata = safe_json_parse(nbody)
            for n in json_get(ndata or {}, "data", "list", default=[]):
                if not isinstance(n, dict):
                    continue
                total += 1
                has = True
                if float(n.get("progress", 0) or 0) >= 100:
                    fin += 1
        except Exception:
            pass
        rate = round(fin / total * 100, 1) if total else 0.0
        result.append({
            "courseId": cid,
            "courseName": cname,
            "teacher": "",
            "jobFinishCount": fin,
            "jobCount": total,
            "jobRate": rate,
            "hasProgress": has,
            "statusText": ("已完成" if (total and fin >= total)
                           else ("进行中" if has else "")),
        })
    return result

# ============ Web端课程详情统计(作业/考试清单, 2026-10-17) ============
def web_course_detail_stat(cache, user, course_id: str) -> dict:
    """海旗: work_list_api + exam_list_api 统计"""
    work_items, exam_items = [], []
    work_fin = work_all = None
    exam_fin = exam_all = None
    try:
        wbody, _ = hqkj_api.work_list_api(cache, str(course_id), retry=3)
        wdata = safe_json_parse(wbody) or {}
        wlst = json_get(wdata, "data", "list", default=[]) or []
        if isinstance(wlst, list):
            work_all = len(wlst)
            work_fin = 0
            for w in wlst:
                if not isinstance(w, dict):
                    continue
                _st = str(w.get("status") or w.get("state") or "")
                _done = _st in ("2", "已完成", "已批阅") or w.get("finish") in (1, True)
                if _done:
                    work_fin += 1
                work_items.append({
                    "name": str(w.get("workName") or w.get("name") or w.get("title") or "作业")[:80],
                    "status": "已完成" if _done else "未完成",
                    "deadline": str(w.get("endTime") or w.get("deadline") or ""),
                    "ongoing": (not _done), "score": w.get("score")})
    except Exception:
        pass
    try:
        ebody, _ = hqkj_api.exam_list_api(cache, str(course_id), retry=3)
        edata = safe_json_parse(ebody) or {}
        elst = json_get(edata, "data", "list", default=[]) or []
        if isinstance(elst, list):
            exam_all = len(elst)
            exam_fin = 0
            for e in elst:
                if not isinstance(e, dict):
                    continue
                _st = str(e.get("status") or e.get("state") or "")
                _done = _st in ("2", "已完成", "已参加")
                if _done:
                    exam_fin += 1
                exam_items.append({
                    "name": str(e.get("examName") or e.get("name") or e.get("title") or "考试")[:80],
                    "status": "已完成" if _done else "未参加",
                    "deadline": str(e.get("endTime") or e.get("startTime") or ""),
                    "ongoing": (not _done), "score": e.get("score")})
    except Exception:
        pass
    return {"supported": True,
            "workFinish": work_fin, "workCount": work_all,
            "examFinish": exam_fin, "examCount": exam_all,
            "workList": work_items, "examList": exam_items,
            "workOngoing": sum(1 for w in work_items if w["ongoing"]),
            "examOngoing": sum(1 for e in exam_items if e["ongoing"])}
