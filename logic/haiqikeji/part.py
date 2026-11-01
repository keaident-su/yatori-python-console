# -*- coding: utf-8 -*-
"""
海旗科技平台逻辑 - 对应 Go 项目的 logic/haiqikeji/HqkjPart.go
普通模式（30秒间隔）+快速模式（并发提交100%）、作业/考试AI自动答题
"""
import re as _re
from utils.log import log_print, with_log_account, INFO, Green, Yellow, Default
from config.config import course_allowed  # [V3.1.3]
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
    # [V3.2.0] 对齐 core HqkjLoginAction: 先 selectdomain 拿 schoolId(登录 URL 需带)
    try:
        _sd_body, _ = hqkj_api.selectdomain_api(cache, retry=5)
        _sd = safe_json_parse(_sd_body or "")
        _sid = json_get(_sd, "data", "id", default="") if _sd else ""
        if _sid:
            cache.school_id = str(_sid)
    except Exception:
        pass
    body, _ = hqkj_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if not (data and (data.get("code") == 200 or data.get("status") is True)):
        return Exception(f"登录失败: {data.get('msg', '未知错误') if data else '解析失败'}")
    # [V3.2.0] 对齐 core: 登录响应 data 即 Token(字符串); 兼容旧结构(data.userId)
    _d = data.get("data")
    if isinstance(_d, str) and _d.strip():
        cache.token = _d.strip()
    elif isinstance(_d, dict):
        cache.token = str(_d.get("token") or _d.get("data") or "")
        if _d.get("userId"):
            cache.user_id = str(_d.get("userId"))
    # user_id: 优先个人中心接口(core 同源: yee_student_info 的 data.id)
    if cache.token:
        try:
            _si_body, _ = hqkj_api.student_info_api(cache, retry=3)
            _si = safe_json_parse(_si_body or "")
            _uid = json_get(_si, "data", "id", default="") if _si else ""
            if _uid:
                cache.user_id = str(_uid)
        except Exception:
            pass
    if not cache.user_id:
        uid = json_get(data, "data", "userId", default="")
        if uid:
            cache.user_id = str(uid)
    return None


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
            target=with_log_account(
                users[i].account, users[i].remark_name)(_user_block),
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
        if not course_allowed(cc, course.course_name):
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

    # [V3.2.0] 作业/考试自动写题(对齐 core HqkjWorkExamAction; hqkjWorkSw 开关/autoExam 控制)
    try:
        _work_exam_answer_flow(setting, user, cache, course, nodes)
    except Exception as _we:
        model_print(True, INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    Red, f"写题流程异常: {str(_we)[:80]}")


# ==================== [V3.2.0] 作业/考试自动写题 (对齐 core aggregation/haiqikeji/HqkjWorkExamAction.go) ====================

_HQKJ_HTML_RE = _re.compile(r"<[^>]+>")
_HQKJ_TYPE_MAP = {1: "single_choice", 2: "multiple_choice", 3: "judge",
                  4: "fill", 5: "short"}


def _hqkj_strip_html(s) -> str:
    if not s:
        return ""
    x = _HQKJ_HTML_RE.sub("", str(s))
    x = x.replace("&nbsp;", " ").replace("\ufeff", "")
    return x.strip()


def _hqkj_quiz_completed(q: dict) -> bool:
    st = int(q.get("status") or 0)
    if st in (2, 3):
        return True
    if st == 1:
        return False
    return int(q.get("frequency") or 0) > 0


def _hqkj_parse_quiz_list(body, arr_key: str, id_key: str) -> list:
    d = safe_json_parse(body or "") or {}
    arr = json_get(d, "data", arr_key, default=[]) or []
    out = []
    for it in (arr if isinstance(arr, list) else []):
        if not isinstance(it, dict):
            continue
        qid = it.get(id_key)
        if qid in (None, "", 0):
            continue
        status = it.get("examStatus", it.get("workStatus", 0))
        out.append({"id": str(qid), "title": str(it.get("title") or ""),
                    "frequency": int(it.get("frequency") or 0),
                    "status": int(status or 0),
                    "score": float(it.get("score") or 0)})
    return out


def _hqkj_parse_records(body) -> list:
    d = safe_json_parse(body or "") or {}
    recs = []
    for key in ("workDetail", "examDetail"):
        arr = json_get(d, "data", key, default=[]) or []
        if not isinstance(arr, list):
            continue
        for it in arr:
            if not isinstance(it, dict):
                continue
            rid = it.get("id")
            if rid in (None, "", 0):
                continue
            recs.append({"id": str(rid),
                         "paper_id": str(it.get("paperId") or ""),
                         "class_id": str(it.get("classId") or "")})
    return recs


def _hqkj_parse_topics(body) -> list:
    d = safe_json_parse(body or "") or {}
    arr = None
    for key in ("workTopics", "examTopics", "workResult"):
        v = json_get(d, "data", key, default=None)
        if isinstance(v, list) and v:
            arr = v
            break
    if arr is None:
        return []
    topics = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        tid = it.get("id", it.get("topicId"))
        if tid in (None, "", 0):
            continue
        opts, idxs, correct = [], [], []
        _os = it.get("option")
        for o in (_os if isinstance(_os, list) else []):
            if not isinstance(o, dict):
                continue
            opts.append(_hqkj_strip_html(o.get("answer") or ""))
            _idx = str(o.get("idx") or "")
            idxs.append(_idx)
            try:
                if float(o.get("scale") or 0) >= 100 and _idx:
                    correct.append(_idx)
            except Exception:
                pass
        topics.append({"topic_id": str(tid),
                       "record_id": str(it.get("recordId") or ""),
                       "type": int(it.get("type") or 1),
                       "content": _hqkj_strip_html(
                           it.get("topic") or it.get("content") or ""),
                       "options": opts, "option_idx": idxs,
                       "correct": correct})
    return topics


def _hqkj_match_option(content: str, options: list, idxs: list) -> str:
    from difflib import SequenceMatcher
    best, best_score = 0, -1.0
    for i, opt in enumerate(options):
        try:
            s = SequenceMatcher(None, str(opt), str(content)).ratio()
        except Exception:
            continue
        if s > best_score:
            best, best_score = i, s
    return idxs[best] if best < len(idxs) else ""


def _hqkj_answers_for(topic: dict):
    """答案来源: 内置标答(scale>=100)优先, 否则多源答题 bridge; 返回 (答案列表, 来源)"""
    qt = _HQKJ_TYPE_MAP.get(topic["type"], "single_choice")
    if topic["correct"]:
        if qt in ("single_choice", "judge"):
            return [topic["correct"][0]], "内置标答"
        seen, ans = set(), []
        for a in topic["correct"]:
            if a and a not in seen:
                seen.add(a)
                ans.append(a)
        return ans, "内置标答"
    if not topic["content"]:
        return [], "无题面"
    text = ""
    try:
        from logic.core.answer_bridge import bridge_answer_one
        text, _src = bridge_answer_one(topic["content"],
                                       options=topic["options"], q_type=qt)
    except Exception:
        text = ""
    answers = []
    if qt in ("single_choice", "judge"):
        idx = (_hqkj_match_option(str(text), topic["options"],
                                  topic["option_idx"])
               if topic["options"] else "")
        if idx:
            answers = [idx]
    elif qt == "multiple_choice":
        for p in [x for x in _re.split(r"[、,，;；\s]+", str(text)) if x.strip()]:
            idx = _hqkj_match_option(p, topic["options"], topic["option_idx"])
            if idx and idx not in answers:
                answers.append(idx)
    else:
        answers = [str(text)]
    return answers, "多源答题"


def _hqkj_answer_one(cache, course, quiz: dict, kind: str, cc, log_f) -> tuple:
    """单卷: 详情→start→逐题→(考试)交卷; 返回 (成功提交数, 总题数)"""
    kind_cn = "作业" if kind == "work" else "考试"
    title = quiz["title"]
    if _hqkj_quiz_completed(quiz):
        log_f(Yellow, f"【{title}】{kind_cn}已完成(作答{quiz['frequency']}次), 跳过")
        return 0, 0
    try:
        if kind == "work":
            body, _ = hqkj_api.work_detail_api(
                cache, quiz["id"], course.id, title)
        else:
            body, _ = hqkj_api.exam_detail_api(
                cache, quiz["id"], course.id, title)
    except Exception as e:
        log_f(Red, f"【{title}】拉取{kind_cn}详情失败: {str(e)[:60]}")
        return 0, 0
    recs = _hqkj_parse_records(body)
    paper_id = next((r["paper_id"] for r in recs if r["paper_id"]), "")
    class_id = next((r["class_id"] for r in recs if r["class_id"]), "")
    try:
        if kind == "work":
            raw, _ = hqkj_api.work_start_api(cache, quiz["id"], course.id,
                                             paper_id, class_id)
        else:
            raw, _ = hqkj_api.exam_start_api(cache, quiz["id"], course.id,
                                             paper_id, class_id)
    except Exception as e:
        log_f(Red, f"【{title}】开卷拉题失败: {str(e)[:60]}")
        return 0, 0
    topics = _hqkj_parse_topics(raw)
    if not topics:
        for r in recs:
            try:
                if kind == "work":
                    cb, _ = hqkj_api.work_consult_api(
                        cache, r["id"], course.id)
                else:
                    cb, _ = hqkj_api.exam_consult_api(
                        cache, r["id"], course.id)
            except Exception:
                continue
            topics = _hqkj_parse_topics(cb)
            if topics:
                break
    if not topics:
        log_f(Yellow, f"【{title}】未拉到题目(未开放/已截止/已作答), 跳过")
        return 0, 0
    log_f(Default, f"【{title}】开始{kind_cn}答题({len(topics)}题)")
    ok = 0
    for t in topics:
        answers, src = _hqkj_answers_for(t)
        if not answers:
            log_f(Yellow, f"题{t['topic_id']} 无可用答案, 跳过")
            continue
        try:
            if kind == "work":
                sb, _ = hqkj_api.submit_work_answer_api(
                    cache, course.id, quiz["id"], t["topic_id"],
                    t["record_id"], str(t["type"]), answers)
            else:
                sb, _ = hqkj_api.submit_exam_answer_api(
                    cache, course.id, quiz["id"], t["topic_id"],
                    t["record_id"], str(t["type"]), answers)
        except Exception as e:
            log_f(Red, f"题{t['topic_id']} 提交异常: {str(e)[:50]}")
            continue
        sd = safe_json_parse(sb or "") or {}
        if int(sd.get("code") or 0) == 200:
            ok += 1
            log_f(Green, f"{kind_cn}题{t['topic_id']} 提交成功"
                  f"({ok}/{len(topics)}, {src}, {answers})")
        else:
            log_f(Red, f"{kind_cn}题{t['topic_id']} 提交失败: {str(sb)[:80]}")
            time.sleep(0.5)
        time.sleep(1.0)
    # 考试交卷: 逐题仅暂存, 需 finish(state=2); 受 examAutoSubmit 控制
    if kind == "exam" and ok > 0 and int(
            getattr(cc, "exam_auto_submit", 0) or 0) == 1:
        record_id = topics[0]["record_id"]
        try:
            fb, _ = hqkj_api.finish_exam_answer_api(
                cache, course.id, quiz["id"], record_id)
            fd = safe_json_parse(fb or "") or {}
            if int(fd.get("code") or 0) == 200:
                log_f(Green, f"【{title}】考试已正式交卷")
            else:
                log_f(Yellow, f"【{title}】交卷返回异常: {str(fb)[:80]}")
        except Exception as e:
            log_f(Red, f"【{title}】交卷异常: {str(e)[:60]}")
    log_f(Green, f"【{title}】{kind_cn}答题结束: 成功 {ok}/{len(topics)} 题")
    return ok, len(topics)


def _work_exam_answer_flow(setting: Setting, user: User, cache: HqkjUserCache,
                           course: HqkjCourse, nodes: list):
    """[V3.2.0] 课程级作业/考试自动写题编排(受 hqkjWorkSw 开关与 autoExam 控制)"""
    cc = user.courses_custom
    if int(getattr(cc, "hqkj_work_sw", 1) or 0) != 1:
        return
    if int(getattr(cc, "auto_exam", 0) or 0) != 1:
        return  # 未开启“题库自动答题”时不写题(全平台统一语义)
    if not (cache.token and cache.school_id and cache.user_id):
        model_print(True, INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    Yellow, "写题跳过: 登录会话缺少 token/schoolId/userId")
        return

    def _log(color, msg):
        model_print(setting.basic_setting.log_model == 1, INFO,
                    f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ", color, msg)

    seen = set()
    for node in (nodes or []):
        if not getattr(node, "id", ""):
            continue
        for kind in ("work", "exam"):
            try:
                if kind == "work":
                    lb, _ = hqkj_api.yee_work_list_api(
                        cache, course.id, node.id)
                    quizzes = _hqkj_parse_quiz_list(lb, "workInfo", "workId")
                else:
                    lb, _ = hqkj_api.yee_exam_list_api(
                        cache, course.id, node.id)
                    quizzes = _hqkj_parse_quiz_list(lb, "examInfo", "examId")
            except Exception as e:
                _log(Yellow, f"拉取{kind}列表异常({node.node_name}): {str(e)[:60]}")
                continue
            for q in quizzes:
                key = f"{kind}:{q['id']}"
                if key in seen:
                    continue
                seen.add(key)
                try:
                    _hqkj_answer_one(cache, course, q, kind, cc, _log)
                except Exception as e:
                    _log(Red, f"【{q['title']}】写题异常: {str(e)[:70]}")


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
                _done = _st in ("2", "已完成", "已批阅") or w.get(
                    "finish") in (1, True)
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



# [V3.2.3] 可重做项巡检接入(全平台统一框架; 本平台暂无可重做/重考接口 -> 占位发现层)
try:
    from logic.core.retake_scanner import register_placeholder as _rs_ph
    _rs_ph("HQKJ", "海旗科技")
except Exception:
    pass
