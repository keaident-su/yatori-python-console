# -*- coding: utf-8 -*-
"""学习通·互动测验(视频弹题)自动化模块

基于播放器前端 JS 逆向还原的完整协议 (详见 XXT_INTERACTIVE_QUIZ_PROTOCOL.md):
- 弹题数据: GET /mooc-ans/richvideo/initdatawithviewerV2?mid=&cpi=&classid=&courseid=
- 弹题提交: GET /question/quiz-validation?classid=&cpi=&objectid=&eventid=&memberinfo=&answerContent=
- 答案格式: 判断 "A"/"B"; 多选 "A,B,C,D" (逗号分隔直传)

实战验证要点 (2026-10-12, 5账号139题100%通过):
1. cpi 必须用账号自己的值 (从知识节点 mArg.defaults.cpi 动态获取, 每个账号不同!)
2. 长扫描后提交前必须重新登录刷新会话 (否则 quiz-validation 返回HTML页而非JSON)
3. 扫描接口 (knowledge/cards) 需 0.25s+ 间隔防止验证码风控; 提交接口不受影响
4. 提交响应 body 以 "<!" 开头 = 会话降级, 需重登录重试

用法:
    from logic.xuexitong.interactive_quiz import scan_quizzes_full, submit_quizzes_with_relogin
"""
import json
import time
from typing import Callable, Dict, List, Optional, Tuple

import requests

from logic.xuexitong.api import page_mobile_chapter_card_api, parse_attachment_setting

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_REFERER_VIDEO = "https://mooc1.chaoxing.com/ananas/modules/video/index.html"


def build_session(cache) -> requests.Session:
    """用 XueXiTUserCache.cookie_dict 构造带登录态的 requests.Session"""
    sess = requests.Session()
    for k, v in (cache.cookie_dict or {}).items():
        sess.cookies.set(k, v, domain=".chaoxing.com")
    return sess


def fetch_timeline_quizzes(sess: requests.Session, mid: str, cpi, class_id, course_id,
                           timeout: int = 20) -> List[Dict]:
    """拉取视频弹题时间轴数据 (initdatawithviewerV2)

    返回弹题列表, 每项含 resourceId/description/options/memberinfo/answerContent 等.
    空列表=该视频无弹题 (或cpi错误).
    """
    url = ("https://mooc1.chaoxing.com/mooc-ans/richvideo/initdatawithviewerV2"
           "?mid=%s&cpi=%s&classid=%s&courseid=%s" % (mid, cpi, class_id, course_id))
    try:
        r = sess.get(url, headers={"User-Agent": _UA,
                                   "Referer": "https://mooc1.chaoxing.com/"}, timeout=timeout)
        text = (r.text or "").strip()
        if len(text) < 10 or text.startswith("<!"):
            return []
        arr = json.loads(text)
        quizzes = []
        for blk in arr if isinstance(arr, list) else []:
            if isinstance(blk, dict):
                quizzes.extend(blk.get("datas") or [])
        return quizzes
    except Exception:
        return []


def scan_quizzes_full(cache, class_id, course_id, nodes: List[int],
                      delay: float = 0.35) -> Tuple[List[Dict], int]:
    """全量扫描节点找弹题 (边扫边动态获取真实cpi)

    ★关键: cpi 在扫描循环中从任意成功解析的 att["defaults"]["cpi"] 获取,
    获取前的视频先积压, 获取后统一补拉 timeline (保证 memberinfo 绑定正确cpi).

    :return: (found列表 [{kid, oid, mid, quizzes}], real_cpi)
    """
    sess = build_session(cache)
    H0 = {"User-Agent": _UA, "Referer": "https://mooc1.chaoxing.com/"}
    real_cpi = 0
    found: List[Dict] = []
    seen = set()
    pending = []

    for kid in nodes:
        try:
            html, _ = page_mobile_chapter_card_api(cache, int(class_id), int(course_id),
                                                   int(kid), 0, 0, retry=2)
            att, _enc = parse_attachment_setting(html)
            if not att:
                time.sleep(delay)
                continue
            if not real_cpi and isinstance(att.get("defaults"), dict) and att["defaults"].get("cpi"):
                real_cpi = att["defaults"]["cpi"]
            for a in (att.get("attachments") or []):
                if a.get("type") != "video":
                    continue
                oid = a.get("objectId")
                if oid in seen:
                    continue
                seen.add(oid)
                if real_cpi:
                    qs = fetch_timeline_quizzes(sess, a.get(
                        "mid"), real_cpi, class_id, course_id)
                    if qs:
                        found.append(
                            {"kid": kid, "oid": oid, "mid": a.get("mid"), "quizzes": qs})
                else:
                    pending.append((kid, a))
        except Exception:
            pass
        time.sleep(delay)

    if real_cpi and pending:
        for kid, a in pending:
            qs = fetch_timeline_quizzes(sess, a.get(
                "mid"), real_cpi, class_id, course_id)
            if qs:
                found.append({"kid": kid, "oid": a.get("objectId"),
                             "mid": a.get("mid"), "quizzes": qs})
            time.sleep(0.3)

    return found, real_cpi


def submit_quiz_answer(sess: requests.Session, class_id, cpi, object_id: str,
                       event_id, memberinfo: str, answer_content: str,
                       timeout: int = 30) -> Dict:
    """提交单个弹题答案 (GENERIC: 传入已构建的sess)

    :param answer_content: "A"/"B" 或 "A,B,C,D" (逗号分隔)
    :return: 服务端JSON; 会话降级时返回 {"isRight": False, "raw_html": True}
    """
    url = ("https://mooc1.chaoxing.com/question/quiz-validation"
           "?classid=%s&cpi=%s&objectid=%s&eventid=%s&memberinfo=%s&answerContent=%s"
           % (class_id, cpi, object_id, event_id, memberinfo, answer_content))
    try:
        r = sess.get(url, headers={"User-Agent": _UA,
                     "Referer": _REFERER_VIDEO}, timeout=timeout)
        body = (r.text or "").strip()
        if body.startswith("<!"):
            return {"isRight": False, "raw_html": True}
        return r.json()
    except Exception as e:
        return {"isRight": False, "err": str(e)[:80]}


def submit_quizzes_with_relogin(cache_factory: Callable[[], object], class_id, cpi,
                                plan: List[Tuple[Dict, str]], delay: float = 1.5,
                                log_fn=None) -> Tuple[int, int, int]:
    """批量提交弹题 (★提交前重登录刷新会话 + HTML响应自动重登录重试)

    :param cache_factory: 返回新登录 XueXiTUserCache 的函数 (内部自行 login)
    :param plan: [(video_dict, quiz_dict, answer_str), ...]
        video_dict 含 oid; quiz_dict 含 resourceId/memberinfo
    :return: (ok, fail, html_retry_count)
    """
    cache = cache_factory()
    sess = build_session(cache)
    ok = fail = html_cnt = 0
    for video, quiz, ans in plan:
        for attempt in range(2):
            d = submit_quiz_answer(sess, class_id, cpi, video.get("oid"),
                                   quiz.get("resourceId"), quiz.get("memberinfo"), ans)
            if d.get("raw_html"):
                html_cnt += 1
                if attempt == 0:
                    cache = cache_factory()  # 重登录
                    sess = build_session(cache)
                    time.sleep(2)
                    continue
                fail += 1
                break
            if d.get("isRight") or d.get("status"):
                ok += 1
            else:
                fail += 1
            if log_fn:
                log_fn(video, quiz, ans, d)
            break
        time.sleep(delay)
    return ok, fail, html_cnt


# ==================== 2026-10-12 增强: 权威清单 + 双接口轮换 ====================
# 实战验证 (5账号540题100%完成): "互动测验 x/108" 统计单位=弹题视频(每视频1个);
# 权威清单接口 stat2-ans.chaoxing.com/study-videoTest/finish (status=""未完成 / "1"已完成);
# PC接口与Mobile接口风控独立, 互相轮换可完避验证码。

_STAT2 = "https://stat2-ans.chaoxing.com"
_PC_CARDS = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"
_VIDEOTEST_REFERER = "https://stat2-ans.chaoxing.com/study-videoTest/index"
_CARDS_REFERER = "https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudy"


def fetch_quiz_plan(sess: requests.Session, class_id, course_id, cpi,
                    status: str = "", page_size: int = 16,
                    max_pages: int = 10) -> Tuple[List[Dict], Optional[int]]:
    """拉互动测验权威清单 (stat2 study-videoTest/finish)

    :param status: ""=未完成清单; "1"=已完成清单
    :return: (行列表, totalResult)  每行含 name/knowledgeName/knowledgeId/
             finishQuestionCount/questionCount/type/rate
    """
    rows: List[Dict] = []
    total = None
    for p in range(1, max_pages + 1):
        try:
            r = sess.get(_STAT2 + "/study-videoTest/finish",
                         params={"clazzid": str(class_id), "courseid": str(course_id),
                                 "cpi": str(cpi), "ut": "s", "pageNo": p,
                                 "pageSize": page_size, "status": status},
                         headers={"User-Agent": _UA,
                                  "Referer": _VIDEOTEST_REFERER},
                         timeout=30)
            d = r.json()
            data = d.get("data") or {}
            lst = data.get("data") or []
            pi = data.get("pageInfo") or {}
            total = pi.get("totalResult", total)
            if not lst:
                break
            rows.extend(lst)
        except Exception:
            break
        time.sleep(0.8)
    return rows, total


def get_video_attachment_dual(sess: requests.Session, cache, class_id, course_id,
                              kid, cpi) -> Tuple[Optional[Dict], str]:
    """双接口轮换拿video附件 (★核心战术: PC被验证码挡→切Mobile,风控独立)

    :return: (attachment_dict | None, way)  way ∈ {pc, mobile, both_fail}
    """
    # 1) PC接口: 解析 knowledge/cards 页面的 mArg JSON
    try:
        url = ("%s?clazzid=%s&courseid=%s&knowledgeid=%s&num=0&ut=s&cpi=%s"
               % (_PC_CARDS, class_id, course_id, kid, cpi))
        r = sess.get(url, headers={"User-Agent": _UA,
                     "Referer": _CARDS_REFERER}, timeout=25)
        if "验证码" not in (r.text or ""):
            import re as _re
            m = _re.search(r"mArg\s*=\s*(\{[\s\S]{50,30000}?\})\s*;", r.text)
            if m:
                import json as _json
                d = _json.loads(m.group(1))
                for a in (d.get("attachments") or []):
                    if a.get("type") == "video":
                        return a, "pc"
    except Exception:
        pass
    # 2) Mobile接口
    try:
        html, _ = page_mobile_chapter_card_api(cache, int(class_id), int(course_id),
                                               int(kid), 0, 0, retry=2)
        att, _enc = parse_attachment_setting(html)
        if att:
            for a in (att.get("attachments") or []):
                if a.get("type") == "video":
                    return a, "mobile"
    except Exception:
        pass
    return None, "both_fail"


def run_quiz_full_flow(cache_factory: Callable[[], object], class_id, course_id, cpi,
                       solver: Callable[[List[Dict]], Dict[int, str]],
                       scan_delay: float = 1.2, submit_delay: float = 1.5,
                       progress_fn=None) -> Dict:
    """互动测验完整补齐闭环 (★经过5账号540题实战验证的黄金流程)

    流程: 拉权威未完成清单 → 双接口轮换扫描弹题 → solver解答 → 重登录提交 → 终审

    :param cache_factory: 返回新登录 XueXiTUserCache 的函数
    :param solver: 解答回调, 入参为弹题列表(每项含description/options/questionType),
                   返回 {序号(1-based): 答案字符串(如"A"/"A,B,C")}
    :param progress_fn: 进度回调 fn(stage, info_dict), 可选
    :return: 结果dict {remaining_before, found, to_answer, ok, fail, remaining_after, ways}
    """
    result = {"remaining_before": None, "found": 0, "to_answer": 0, "ok": 0,
              "fail": 0, "remaining_after": None, "ways": {}}
    cache = cache_factory()
    if not cache:
        result["error"] = "login_fail"
        return result
    sess = build_session(cache)
    # stat2 域cookie
    for k, v in (cache.cookie_dict or {}).items():
        sess.cookies.set(k, v, domain=".stat2-ans.chaoxing.com")

    # 1. 权威未完成清单
    items, total = fetch_quiz_plan(sess, class_id, course_id, cpi, status="")
    result["remaining_before"] = total if total is not None else len(items)
    if progress_fn:
        progress_fn("plan", {"remaining": result["remaining_before"]})
    if not items:
        result["error"] = None  # 无需处理
        return result

    # 2. 双接口轮换扫描
    found = []
    for i, item in enumerate(items):
        kid = item.get("knowledgeId")
        a, way = get_video_attachment_dual(
            sess, cache, class_id, course_id, kid, cpi)
        result["ways"][way] = result["ways"].get(way, 0) + 1
        if a:
            qs = fetch_timeline_quizzes(
                sess, a.get("mid"), cpi, class_id, course_id)
            if qs:
                found.append({"kid": kid, "oid": a.get("objectId"),
                              "mid": a.get("mid"), "quizzes": qs})
        time.sleep(scan_delay)
    result["found"] = len(found)
    undone = [(f, q) for f in found for q in f["quizzes"]
              if not (q.get("answerContent") or "").strip()]
    result["to_answer"] = len(undone)
    if progress_fn:
        progress_fn("scan", {"found": len(found), "to_answer": len(undone)})
    if not undone:
        return result

    # 3. 解答
    qlist = [q for _f2, q in undone]
    ans_map = solver(qlist) or {}

    # 4. 重登录 + 提交 (复用重登录重试机制)
    cache = cache_factory()
    sess = build_session(cache)
    ok = fail = 0
    for i, (video, quiz) in enumerate(undone):
        a2 = ans_map.get(i + 1)
        if not a2:
            fail += 1
            continue
        for attempt in range(2):
            d = submit_quiz_answer(sess, class_id, cpi, video.get("oid"),
                                   quiz.get("resourceId"), quiz.get("memberinfo"), a2)
            if d.get("raw_html"):
                if attempt == 0:
                    cache = cache_factory()
                    sess = build_session(cache)
                    time.sleep(2)
                    continue
                fail += 1
                break
            if d.get("isRight") or d.get("status"):
                ok += 1
            else:
                fail += 1
            break
        time.sleep(submit_delay)
    result["ok"] = ok
    result["fail"] = fail

    # 5. 终审 (统计有1-2分钟延迟, 调用方如需精确可稍后复查)
    try:
        _rows, left = fetch_quiz_plan(
            sess, class_id, course_id, cpi, status="")
        result["remaining_after"] = left
    except Exception:
        pass
    if progress_fn:
        progress_fn("done", result)
    return result
