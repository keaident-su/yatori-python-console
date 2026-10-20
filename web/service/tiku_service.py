# -*- coding: utf-8 -*-
"""题库管理服务(方案A, 2026-10-08)

- 复用全局答题引擎的 LocalTikuCache(与刷课查询同源: 更正后立即对后续查询生效)
- 引擎未初始化(纯API进程)时按配置路径兜底自建懒加载实例
- 所有写操作走 LocalTikuCache.update(): 原子替换 + 外部修改检测 + 每日自动备份
"""
import os
import threading
import time

from entity.vo import Response
from logic.core import answer_engine as ae

_fallback_cache = None
_fallback_path = ""
_collect_lock = threading.Lock()  # (保留: 旧同步版兼容, 当前异步版用 _collect_state.running)
_collect_state = {"running": False, "startedAt": 0, "finishedAt": 0,
                  "stats": None, "error": "", "uid": "", "progress": ""}
_merge_state = {"running": False, "startedAt": 0, "finishedAt": 0,
                "stats": None, "error": "", "progress": ""}


def _configured_path() -> str:
    """从 config.yaml 读取 localCachePath(读不到则用默认)"""
    try:
        from config.config import read_config
        for cand in ("config.yaml", os.path.join(os.getcwd(), "config.yaml")):
            if os.path.exists(cand):
                cfg = read_config(cand)
                p = str(getattr(cfg.setting.answer_setting,
                                "local_cache_path", "") or "")
                if p.strip():
                    return p.strip()
                break
    except Exception:
        pass
    return "questions_answers.json"


def _get_cache():
    """优先全局引擎缓存(与运行同源); 兜底自建(按路径缓存实例)"""
    global _fallback_cache, _fallback_path
    try:
        eng = ae.get_answer_engine()
        cache = getattr(eng, "cache", None) if eng else None
        if cache is not None:
            return cache
    except Exception:
        pass
    path = _configured_path()
    if _fallback_cache is None or _fallback_path != path:
        _fallback_cache = ae.LocalTikuCache(path, enable=1)
        _fallback_path = path
    return _fallback_cache


def tiku_stats_service() -> dict:
    """题库概况: 总条数/文件路径/是否加载失败"""
    try:
        cache = _get_cache()
        cache.load()
        return Response(code=200, message="OK", data={
            "total": cache.count,
            "path": cache.path,
            "loadFailed": bool(getattr(cache, "_load_failed", False)),
        }).to_dict()
    except Exception as e:
        return Response(code=500, message=f"读取题库失败: {e}").to_dict()


def tiku_search_service(body: dict) -> dict:
    """题库检索: keyword + 分页 + 搜索范围(question/answer/all)"""
    try:
        cache = _get_cache()
        kw = str(body.get("keyword", "") or "")
        page = body.get("page", 1)
        size = body.get("size", 20)
        search_in = str(body.get("searchIn", "question") or "question")
        if search_in not in ("question", "answer", "all"):
            search_in = "question"
        data = cache.search(kw, page=page, size=size, search_in=search_in)
        data["path"] = cache.path
        return Response(code=200, message="OK", data=data).to_dict()
    except Exception as e:
        return Response(code=500, message=f"检索失败: {e}").to_dict()


def tiku_update_service(body: dict) -> dict:
    """更正题目: 覆盖答案值 / 可选重命名题面

    2026-10-13 增强: allowAdd=true 时题目不存在则新增(用于"无法获取到题目"
    场景下人工对照正确答案录入); 默认仍为仅更正已有键。
    """
    try:
        cache = _get_cache()
        q = str(body.get("question", "") or "").strip()
        a = str(body.get("answer", "") or "")
        nq = str(body.get("newQuestion", "") or "").strip()
        allow_add = bool(body.get("allowAdd", False))
        if not q:
            return Response(code=400, message="缺少原题面").to_dict()
        cache.load()
        if getattr(cache, "_load_failed", False):
            return Response(code=500,
                            message="题库文件读取失败, 已禁止写入(防覆盖损坏文件)").to_dict()
        if q not in cache._data:
            if allow_add and a:
                ok = cache.save(q, a)
                if not ok:
                    return Response(code=500,
                                    message="新增失败(空值/占位答案/写盘异常)").to_dict()
                return Response(code=200, message="题库中无此题, 已新增").to_dict()
            return Response(code=400,
                            message="该题目不在当前题库中(仅支持更正已有题目; "
                                    "如需录入新题请勾选\"不存在则新增\")").to_dict()
        ok = cache.update(q, a, nq)
        if not ok:
            return Response(code=500,
                            message="更正失败(可能无有效变更或写入异常)").to_dict()
        return Response(code=200, message="更正成功").to_dict()
    except Exception as e:
        return Response(code=500, message=f"更正异常: {e}").to_dict()


def _collect_worker(account: str, password: str, cid: str, uid: str,
                    kinds: str = "works", exam_ids=None,
                    submit: bool = True, rate: int = 100):
    """采集后台线程(2026-10-13 扩展): works=作业/章测; exams=考试采集; all=全部"""
    try:
        from logic.xuexitong.models import XueXiTUserCache
        from logic.xuexitong.part import (
            _login_action, _generate_device_flag,
            collect_answers_manual, collect_exams_manual)
        cache = XueXiTUserCache(account=account, password=password)
        cache.device_flag = _generate_device_flag()
        err = _login_action(cache)
        if err:
            _collect_state["error"] = f"登录失败: {str(err)[:120]}"
            return
        merged = {"account": account, "kinds": kinds}
        if kinds in ("works", "all"):
            _collect_state["progress"] = "作业/章测采集..."
            w = collect_answers_manual(cache, course_id_filter=cid)
            merged.update(w)
        if kinds in ("exams", "all"):
            _collect_state["progress"] = "考试采集(进考试拉卷)..."
            ex = collect_exams_manual(
                cache, course_id_filter=cid,
                exam_ids_filter=exam_ids, submit=bool(submit),
                submit_rate=int(rate or 100))
            merged["examScanned"] = ex.get("examsScanned", 0)
            merged["examEntered"] = ex.get("examsEntered", 0)
            merged["examSubmitted"] = ex.get("examsSubmitted", 0)
            merged["examQuestions"] = ex.get("questions", 0)
            merged["examErrors"] = (ex.get("errors") or [])[:10]
            merged["collectedNew"] = (int(merged.get("collectedNew", 0) or 0)
                                      + int(ex.get("collectedNew", 0) or 0))
            merged["collectedUpd"] = (int(merged.get("collectedUpd", 0) or 0)
                                      + int(ex.get("collectedUpd", 0) or 0))
            merged["skipped"] = (int(merged.get("skipped", 0) or 0)
                                 + int(ex.get("skipped", 0) or 0))
        _collect_state["stats"] = merged
    except Exception as e:
        _collect_state["error"] = f"采集异常: {str(e)[:160]}"
    finally:
        _collect_state["running"] = False
        _collect_state["finishedAt"] = time.time()


def tiku_collect_service(body: dict) -> dict:
    """一键采集题目(2026-10-13 异步化): {uid, courseId(可空=全部课程)}

    立即返回启动结果; 大批量采集(几分钟~几十分钟)不再受前端90秒超时影响,
    进度/结果用 GET /tiku/collect/status 轮询; 同一时间仅允许1个任务。
    """
    uid = str(body.get("uid", "") or "").strip()
    cid = str(body.get("courseId", "") or "").strip()
    if not uid:
        return Response(code=400, message="缺少 uid").to_dict()
    if _collect_state.get("running"):
        return Response(code=429, message="已有采集任务进行中, 请先查询状态").to_dict()
    # 查库取用户(与 start_brush 同源)
    from dao.database import get_session
    from dao import user_mapper
    session = get_session()
    try:
        user = user_mapper.query_user(session, uid=uid)
        if not user:
            return Response(code=400, message="该账号不存在").to_dict()
        account = str(getattr(user, "account", "") or "")
        password = str(getattr(user, "password", "") or "")
        acc_type = str(getattr(user, "account_type", "") or "")
    finally:
        session.close()
    if acc_type and acc_type != "XUEXITONG":
        return Response(code=400, message="暂仅支持学习通账号采集").to_dict()
    kinds = str(body.get("kinds", "works") or "works")
    if kinds not in ("works", "exams", "all"):
        kinds = "works"
    exam_ids = body.get("examIds") or []
    if not isinstance(exam_ids, list):
        exam_ids = []
    submit = bool(body.get("submit", True))
    try:
        rate = int(body.get("submitRate", 100) or 100)
    except Exception:
        rate = 100
    _collect_state.update({"running": True, "startedAt": time.time(),
                           "finishedAt": 0, "stats": None, "error": "",
                           "uid": uid, "progress": "准备中"})
    threading.Thread(target=_collect_worker,
                     args=(account, password, cid, uid, kinds,
                           exam_ids, submit, rate),
                     daemon=True, name="tiku-collect").start()
    return Response(code=200, message="采集任务已启动",
                    data={"started": True, "kinds": kinds}).to_dict()


def tiku_collect_status_service() -> dict:
    """查询采集任务状态(running/elapsed/stats/error)"""
    try:
        st = dict(_collect_state)
        st["elapsed"] = (int(time.time() - st["startedAt"])
                         if st.get("startedAt") else 0)
        return Response(code=200, message="OK", data=st).to_dict()
    except Exception as e:
        return Response(code=500, message=f"状态查询异常: {e}").to_dict()


def _norm_cmp(x) -> str:
    """投票比较用规范化(大小写/空白/中英标点)"""
    return (str(x or "").strip().lower()
            .replace(" ", "").replace("，", ",")
            .replace("。", ".").replace("；", ";"))


def _vote_answers(eng, question: str, options=None, q_type: str = ""):
    """逐源查询收集答案(跳过本地缓存源与AI源): [(源名, 答案)...]"""
    from logic.core.answer_engine import SOURCE_LOCAL, SOURCE_AI
    results = []
    for src in getattr(eng, "sources", []) or []:
        try:
            if not src.enable:
                continue
            if src.type in (SOURCE_LOCAL, SOURCE_AI):
                continue
            if not src.token:
                continue
            ans = src.query(question, options, q_type)
            if ans:
                results.append((src.name, str(ans).strip()))
        except Exception:
            continue
    return results


def _vote_decide(collected_a: str, live_a: str, votes) -> str:
    """投票判定: 'collected'=采纳采集答案 / 'live'=保留现役 / ''=无法定夺"""
    c = _norm_cmp(collected_a)
    l = _norm_cmp(live_a)
    c_votes = l_votes = 0
    for _nm, v in votes:
        nv = _norm_cmp(v)
        if nv == c:
            c_votes += 1
        elif nv == l:
            l_votes += 1
    if c_votes > l_votes:
        return "collected"
    if l_votes > c_votes:
        return "live"
    return ""


def _ai_review(eng, question: str, collected_a: str, live_a: str) -> str:
    """AI复核平局: 返回 'collected'/'live'/''"""
    from logic.core.answer_engine import SOURCE_AI
    prompt = ("有一道题存在两个候选答案，请判断哪个更可能是正确答案。\n"
              "题目：%s\n候选A：%s\n候选B：%s\n"
              "请只回答一个大写字母：A 或 B（无法判断则回答 C）。"
              % (str(question)[:500], str(collected_a)[:200], str(live_a)[:200]))
    for src in getattr(eng, "sources", []) or []:
        try:
            if not (src.enable and src.type == SOURCE_AI and src.token):
                continue
            from logic.core.ai_client import AIClient
            ans = AIClient(src.url, src.model, src.token, src.ai_type).ask(
                prompt, None, "")
            r = str(ans or "").strip().upper()
            if r[:3].find("A") == 0:
                return "collected"
            if r[:3].find("B") == 0:
                return "live"
            if "A" in r[:3] and "B" not in r[:3]:
                return "collected"
            if "B" in r[:3]:
                return "live"
        except Exception:
            continue
    return ""


def _merge_worker(items, mode: str, max_vote: int):
    """并入清洗后台任务(safe=仅新增; vote=多源投票+AI复核)"""
    try:
        cache = _get_cache()
        if mode != "vote":
            add_n, skip_n = cache.save_many(items)
            _merge_state["stats"] = {"mode": "safe", "added": add_n,
                                     "addSkipped": skip_n,
                                     "collectedTotal": len(items)}
            return
        from logic.core.answer_engine import get_answer_engine, _norm_question
        eng = get_answer_engine()
        if eng is None:
            _merge_state["error"] = "答题引擎未初始化(纯API进程), 请在本地程序内执行投票清洗"
            return
        idx = {}
        with cache._lock:
            for k in cache._data.keys():
                nk = _norm_question(k)
                if nk and nk not in idx:
                    idx[nk] = k
        add_pairs, conflicts = [], []
        for q, a in items:
            nk = _norm_question(q)
            key = idx.get(nk) if nk else None
            if key is None:
                add_pairs.append((q, a))
            else:
                live_a = str(cache._data.get(key, ""))
                if _norm_cmp(live_a) != _norm_cmp(a):
                    conflicts.append((key, q, a, live_a))
        add_n, skip_n = cache.save_many(add_pairs)
        cap = min(len(conflicts), max(1, int(max_vote or 300)))
        over_pairs, keep_n, iso = [], 0, []
        for i, (key, q, ca, la) in enumerate(conflicts[:cap]):
            _merge_state["progress"] = "投票中 %d/%d" % (i + 1, cap)
            votes = _vote_answers(eng, q, None, "")
            dec = _vote_decide(ca, la, votes)
            if not dec:
                dec = _ai_review(eng, q, ca, la)
            if dec == "collected":
                over_pairs.append((key, ca))
            elif dec == "live":
                keep_n += 1
            else:
                if len(iso) < 50:
                    iso.append({"q": str(q)[:60], "collected": str(ca)[:40],
                                "live": str(la)[:40]})
        over_n = 0
        if over_pairs:
            try:
                over_n, _f = cache.update_many(over_pairs)
            except Exception:
                over_n = 0
        _merge_state["stats"] = {
            "mode": "vote", "collectedTotal": len(items),
            "added": add_n, "addSkipped": skip_n,
            "conflicts": len(conflicts), "votedOverride": over_n,
            "votedKeepLive": keep_n, "isolated": len(conflicts) - over_n - keep_n,
            "isolatedSample": iso, "voteCapped": len(conflicts) > cap,
        }
    except Exception as e:
        _merge_state["error"] = f"并入清洗异常: {str(e)[:160]}"
    finally:
        _merge_state["running"] = False
        _merge_state["finishedAt"] = time.time()


def tiku_merge_collected_service(body: dict = None) -> dict:
    """并入清洗(异步): body {mode: safe|vote, maxVote}

    safe=仅新增(默认, 秒级); vote=多源投票+AI复核(异步, 进度查 /tiku/mergeCollected/status)。
    """
    body = body or {}
    mode = str(body.get("mode", "safe") or "safe")
    try:
        max_vote = int(body.get("maxVote", 300) or 300)
    except Exception:
        max_vote = 300
    try:
        if _merge_state.get("running"):
            return Response(code=429, message="已有并入清洗任务进行中, 请先查询状态").to_dict()
        from logic.xuexitong.part import _get_collected_cache
        cc = _get_collected_cache()
        cc.load()
        if getattr(cc, "_load_failed", False):
            return Response(code=500, message="采集库读取失败(文件损坏?)").to_dict()
        with cc._lock:
            items = list(cc._data.items())
        if not items:
            return Response(code=200, message="采集库为空, 无需并入",
                            data={"started": False, "collectedTotal": 0}).to_dict()
        if mode != "vote":
            # 安全模式(同步秒级): 仅新增
            cache = _get_cache()
            add_n, skip_n = cache.save_many(items)
            return Response(code=200,
                            message=f"并入完成(安全模式): 新增{add_n}条 (已存在跳过{skip_n}条)",
                            data={"mode": "safe", "added": add_n,
                                  "skipped": skip_n,
                                  "collectedTotal": len(items),
                                  "finished": True}).to_dict()
        # 投票模式: 异步
        _merge_state.update({"running": True, "startedAt": time.time(),
                             "finishedAt": 0, "stats": None, "error": "",
                             "progress": "准备中"})
        threading.Thread(target=_merge_worker,
                         args=(items, "vote", max_vote),
                         daemon=True, name="tiku-merge").start()
        return Response(code=200, message="投票清洗任务已启动",
                        data={"started": True, "mode": "vote",
                              "collectedTotal": len(items)}).to_dict()
    except Exception as e:
        return Response(code=500, message=f"并入异常: {e}").to_dict()


def tiku_merge_status_service() -> dict:
    """查询并入清洗任务状态"""
    try:
        st = dict(_merge_state)
        st["elapsed"] = (int(time.time() - st["startedAt"])
                         if st.get("startedAt") else 0)
        return Response(code=200, message="OK", data=st).to_dict()
    except Exception as e:
        return Response(code=500, message=f"状态查询异常: {e}").to_dict()


def tiku_exam_list_service(uid: str, course_id: str) -> dict:
    """列出某课程的考试(供"指定考试采集"勾选, 2026-10-13)"""
    try:
        from dao.database import get_session
        from dao import user_mapper
        session = get_session()
        try:
            user = user_mapper.query_user(session, uid=uid)
            if not user:
                return Response(code=400, message="该账号不存在").to_dict()
            account = str(getattr(user, "account", "") or "")
            password = str(getattr(user, "password", "") or "")
            acc_type = str(getattr(user, "account_type", "") or "")
        finally:
            session.close()
        if acc_type and acc_type != "XUEXITONG":
            return Response(code=400, message="暂仅支持学习通").to_dict()
        from logic.xuexitong.models import XueXiTUserCache
        from logic.xuexitong import part as P
        from logic.xuexitong import api as X
        cache = XueXiTUserCache(account=account, password=password)
        cache.device_flag = P._generate_device_flag()
        err = P._login_action(cache)
        if err:
            return Response(code=500,
                            message=f"登录失败: {str(err)[:120]}").to_dict()
        courses = P._pull_course_action(cache) or []
        course = None
        for c in courses:
            if str(c.course_id) == str(course_id):
                course = c
                break
        if course is None:
            return Response(code=400, message="未找到该课程").to_dict()
        body, _ = X.pull_exam_list_api(
            cache, course.course_id, course.key, str(course.cpi), retry=2)
        exams = P._parse_exam_list_html(body or "")
        out = []
        for e in exams:
            if not isinstance(e, dict):
                continue
            out.append({"id": str(e.get("taskrefId") or ""),
                        "name": str(e.get("name") or ""),
                        "status": str(e.get("status") or "")})
        return Response(code=200, message="OK",
                        data={"courseId": str(course_id),
                              "exams": out}).to_dict()
    except Exception as e:
        return Response(code=500,
                        message=f"考试列表获取异常: {str(e)[:120]}").to_dict()
