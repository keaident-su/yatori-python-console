# -*- coding: utf-8 -*-
"""
青书学堂平台逻辑 - 对应 Go 项目的 logic/qingshuxuetang/QsxtPart.go
课件视频+课程资料双轨道，60秒间隔提交，作业自动完成
"""
from utils.log import log_print, with_log_account, INFO, Green, Yellow, Default
from config.config import User, Setting, JSONDataForConfig
from typing import List, Any
import threading
import time
from random import uniform  # 2026-10-16: 拟人答题节奏(替代固定sleep)
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


def _app_login_try(cache: QsxtUserCache):
    """尝试青书App登录(为作业链备token; 失败静默, 网页链不受影响)"""
    try:
        body, _ = qsxt_api.app_login_api(cache, retry=3)
        if cache.token:
            return True
    except Exception:
        pass
    return False


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
        t = threading.Thread(
            target=with_log_account(
                users[i].account, users[i].remark_name)(_user_block),
            args=(setting, users[i], cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def _user_block(setting: Setting, user: User, cache: QsxtUserCache):
    _app_login_try(cache)  # 2026-10-15: 尝试App登录备作业链token(失败静默)
    body, _ = qsxt_api.course_list_api(cache, retry=8)
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
                courses.append(QsxtCourse(
                    id=str(item.get("courseId", "")),
                    course_name=item.get("courseName", ""),
                    school_id=str(item.get("schoolId", "")
                                  or item.get("school_id", "")),
                    class_id=str(item.get("classId", "")
                                 or item.get("class_id", "")),
                    period_id=str(item.get("periodId", "")
                                  or item.get("semesterId", "")),
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

    # 2026-10-15: 作业处理(App链: solution优先+多源桥兜底)
    _work_action(setting, user, cache, course)


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


def web_course_list(cache: QsxtUserCache, user: User) -> List[dict]:
    """Web端课程列表+总进度(按节点完成度统计)"""
    body, _ = qsxt_api.course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    result = []
    for item in _web_iter_list(data):
        if not isinstance(item, dict):
            continue
        cid = str(item.get("courseId", "") or item.get("id", ""))
        fin, total, has = 0, 0, False
        try:
            nbody, _ = qsxt_api.node_list_api(cache, cid, retry=3)
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

# ============ 作业处理 (2026-10-15 App链, 对齐Go版独有实现) ============


def _work_action(setting: Setting, user: User, cache: QsxtUserCache, course: QsxtCourse):
    """青书作业: 拉列表->逐卷拉题(solution优先/多源桥兜底)->逐题提交->整卷提交->缓存"""
    cc = user.courses_custom
    if getattr(cc, "auto_exam", 0) == 0:
        return
    if not (course.school_id and course.class_id and course.period_id):
        return  # 参数不全(网页课程数据缺App参数时跳过)
    import json as _json
    from logic.core.answer_bridge import bridge_answer_one, bridge_cache_results
    _QT = {"1": "single_choice", "2": "multiple_choice", "3": "judge",
           "4": "fill", "5": "short"}
    # 2026-10-16: 拟人节奏(0关/1标准/2谨慎)
    _qs_pace = int(getattr(cc, "qs_exam_pace", 1) or 0)
    try:
        list_body, _ = qsxt_api.pull_work_list_app_api(
            cache, course.period_id, course.class_id, course.school_id, course.id)
        ldata = safe_json_parse(list_body)
        rows = []
        if ldata:
            rows = json_get(ldata, "data", "rows", default=[]) or []
        for wk in rows:
            if not isinstance(wk, dict):
                continue
            _st = wk.get("answerStatus")
            if _st == 2:
                continue  # 已完成的跳过
            quiz_id = str(wk.get("id", ""))
            wk_title = str(wk.get("title", ""))[:20]
            if not quiz_id:
                continue
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, cache.account, Default, "] ",
                      f"【{course.course_name}】", Yellow, f"作业 [{wk_title}] 开始答题...")
            try:
                q_body, _ = qsxt_api.pull_work_question_list_api(
                    cache, course.class_id, quiz_id, course.school_id, course.id)
                qdata = safe_json_parse(q_body)
                questions = []
                if qdata:
                    questions = json_get(
                        qdata, "data", "studentQuestions", default=[]) or []
                _results = []
                _answers_arr = []
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    qid = str(q.get("questionId", ""))
                    sol = str(q.get("solution", "") or "").strip()
                    q_type = str(q.get("questionType", ""))
                    q_text = str(q.get("content", "")
                                 or q.get("title", "") or "")
                    opts = q.get("options") or []
                    _src = "平台solution"
                    if not sol:
                        # 平台无答案 -> 多源桥
                        _ans, _src = bridge_answer_one(
                            q_text, options=(
                                opts if isinstance(opts, list) else None),
                            q_type=_QT.get(q_type, ""))
                        sol = _ans or ""
                    if not qid or not sol:
                        continue
                    # 逐题提交
                    try:
                        qsxt_api.submit_answer_api(
                            cache, sol, qid, quiz_id, course.school_id)
                    except Exception:
                        pass
                    _answers_arr.append({"answer": sol, "questionId": qid,
                                         "score": float(q.get("score", 0) or 0),
                                         "timeSpend": 0})
                    _results.append({"q_text": q_text, "answer": sol,
                                     "src": _src, "q_type": _QT.get(q_type, "")})
                    # 2026-10-16: 拟人答题节奏(0关/1标准/2谨慎)
                    if _qs_pace >= 2:
                        time.sleep(uniform(1.2, 3.5))
                    elif _qs_pace >= 1:
                        time.sleep(uniform(0.8, 2.5))
                    else:
                        time.sleep(0.6)
                # 整卷提交(action=1)
                if _answers_arr:
                    _payload = _json.dumps({
                        "action": 1,
                        "classId": int(course.class_id) if course.class_id.isdigit() else course.class_id,
                        "courseId": course.id,
                        "issForceSubmit": False,
                        "quizId": quiz_id,
                        "schoolId": course.school_id,
                        "timeSpend": int(wk.get("totalTime", 0) or 0) // 5,
                        "studentAnswers": _answers_arr,
                    }, ensure_ascii=False)
                    qsxt_api.save_answer_api(cache, _payload)
                    _n = bridge_cache_results(_results)
                    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                              "[", Green, cache.account, Default, "] ",
                              Green, f"作业 [{wk_title}] 完成({len(_answers_arr)}题, 缓存{_n}条)")
            except Exception as e:
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, cache.account, Default, "] ",
                          Red, f"作业 [{wk_title}] 异常: {str(e)[:80]}")
    except Exception as e:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  Red, f"作业处理异常: {str(e)[:80]}")

# ============ Web端课程详情统计(作业清单, 2026-10-17) ============
def web_course_detail_stat(cache, user, course_id: str) -> dict:
    """青书: work_list_api 统计(该平台无独立考试列表->exam置空)"""
    work_items = []
    work_fin = work_all = None
    try:
        wbody, _ = qsxt_api.work_list_api(cache, str(course_id), retry=3)
        wdata = safe_json_parse(wbody) or {}
        wlst = _web_iter_list(wdata)
        if isinstance(wlst, list):
            work_all = len(wlst)
            work_fin = 0
            for w in wlst:
                if not isinstance(w, dict):
                    continue
                _st = w.get("answerStatus")
                _done = _st == 2
                if _done:
                    work_fin += 1
                work_items.append({
                    "name": str(w.get("title") or w.get("name") or "作业")[:80],
                    "status": "已完成" if _done else "未完成",
                    "deadline": str(w.get("endTime") or w.get("deadline") or ""),
                    "ongoing": (not _done), "score": w.get("score")})
    except Exception:
        pass
    return {"supported": True,
            "workFinish": work_fin, "workCount": work_all,
            "examFinish": None, "examCount": None,
            "workList": work_items, "examList": [],
            "workOngoing": sum(1 for w in work_items if w["ongoing"]),
            "examOngoing": 0}
