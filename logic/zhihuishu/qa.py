# -*- coding: utf-8 -*-
"""[V3.2.4] 智慧树课程问答(讨论)自动作答

逆向定型(2026-10-27, 真机验证 46 题提交成功):
- 入口: https://qah5.zhihuishu.com/qa.html#/web/home/{courseId}?role=2&recruitId={rid}
- 列表: Vue 组件 QaList.getQaList() (pageIndex 翻页 / noMore / questionList[].questionId / content)
- 提交: question-Dialog.saveAnswer(''):
    {annexs, qid:questionId, source:roleId, aContent:inputContent,
     courseId, recruitId, validate, saveSource:1}
    -> 页面内部完成 creditqa 网关加密(secretStr=yxyz(params,dynStr), 密钥随会话下发),
       故采用"组件直调"方案, 不在 Python 侧复刻加密
- 平台限流: {"msg":"超过最大提交数","code":"1010"} -> 遇此立即停止, 次日再跑
- 去重: 重复提交返回 {"msg":"已回答过该问题","status":"-1"} -> 计为 dup(不算失败)
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 页内 JS: 拉齐题目(热门+最新 tab 翻页去重)
_JS_COLLECT = """async () => {
    var vm=null, all=[...document.querySelectorAll('*')];
    for (var el of all) { if (el.__vue__) { vm = el.__vue__; break; } }
    if (!vm) return {err:'no-vue'};
    var queue=[vm], list=null, seen=0;
    while (queue.length && seen<600) {
        var c=queue.shift(); seen++;
        if ((c.$options.name||c.$options._componentTag||'')==='QaList') { list=c; break; }
        (c.$children||[]).forEach(ch=>queue.push(ch));
    }
    if (!list) return {err:'no-list'};
    var seenIds={}, out=[];
    for (var tab=0; tab<2; tab++) {
        list.selectedIndex = tab;
        for (var page=0; page<10; page++) {
            list.pageIndex = page;
            try { await list.getQaList(); } catch(e) { break; }
            var arr = list.questionList || [];
            for (var q of arr) {
                if (!seenIds[q.questionId]) {
                    seenIds[q.questionId]=1;
                    out.push({id:q.questionId, c:(q.content||'').slice(0,400)});
                }
            }
            if (list.noMore || arr.length===0) break;
            await new Promise(r=>setTimeout(r,700));
        }
    }
    return {len: out.length, qs: out};
}"""

# 页内 JS: 组件直调提交一条回答(页面自加密)
_JS_SUBMIT = """async (p) => {
    var vm=null, all=[...document.querySelectorAll('*')];
    for (var el of all) { if (el.__vue__) { vm = el.__vue__; break; } }
    if (!vm) return {err:'no-vue'};
    var queue=[vm], dlg=null, seen=0;
    while (queue.length && seen<600) {
        var c=queue.shift(); seen++;
        if ((c.$options.name||c.$options._componentTag||'')==='question-Dialog') { dlg=c; break; }
        (c.$children||[]).forEach(ch=>queue.push(ch));
    }
    if (!dlg) return {err:'no-dlg'};
    try {
        dlg.questionId = p.qid;
        dlg.inputContent = p.ans;
        dlg.type = 1; dlg.allType = 0;
        dlg.imgList = dlg.imgList || [];
        dlg.repetitionFlag = true;
        dlg.saveAnswer('');
        return {sent:true};
    } catch(e) { return {err: String(e).slice(0,200)}; }
}"""


def run_course_qa(cache, course, log=None, limit: int = 35) -> Dict[str, Any]:
    """批量回答课程问答(讨论)。

    :param cache: 登录缓存(cache.session 提供 cookies)
    :param course: 课程对象(需 course.id / course.recruit_id / course.name)
    :param log: 日志对象(需 .info/.success/.warning)
    :param limit: 单次最多提交数(默认 35, 低于平台约 40+ 的限流线)
    :return: {total, ok, dup, fail, limited, note}
    """
    _log = log.info if (log is not None and hasattr(
        log, "info")) else (lambda *a, **k: None)
    stats: Dict[str, Any] = {"total": 0, "ok": 0, "dup": 0, "fail": 0,
                             "limited": 0, "note": ""}
    try:
        from playwright.sync_api import sync_playwright
        from logic.zhihuishu.answer_bridge import zhs_answer_question
    except Exception as e:
        stats["note"] = f"依赖缺失: {e}"
        return stats
    cookies = []
    try:
        for ck in getattr(cache.session, "cookies", None) or []:
            if getattr(ck, "name", "") and getattr(ck, "value", ""):
                cookies.append({"name": ck.name, "value": str(ck.value),
                                "domain": ".zhihuishu.com", "path": "/"})
    except Exception:
        pass
    cid = str(getattr(course, "id", "") or "")
    rid = str(getattr(course, "recruit_id", "") or "")
    cname = str(getattr(course, "name", "") or "")
    url = (f"https://qah5.zhihuishu.com/qa.html#/web/home/{cid}"
           f"?role=2&recruitId={rid}")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            ctx = b.new_context(user_agent=_UA)
            if cookies:
                ctx.add_cookies(cookies)
            pg = ctx.new_page()
            cap: List[str] = []

            def _on_resp(r):
                try:
                    if "creditqa" in r.url and "saveAnswer" in r.url:
                        cap.append(r.text()[:240])
                except Exception:
                    pass

            pg.on("response", _on_resp)
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                stats["note"] = f"页面打开失败: {e}"
                return stats
            pg.wait_for_timeout(12000)
            try:
                got = pg.evaluate(_JS_COLLECT) or {}
            except Exception as e:
                stats["note"] = f"拉题失败: {e}"
                return stats
            qs = got.get("qs") or []
            stats["total"] = len(qs)
            if not qs:
                stats["note"] = got.get("err") or "未取到题目(页面未就绪或该课无问答)"
                return stats
            done = 0
            for q in qs:
                if done >= max(1, int(limit)):
                    stats["note"] = f"已达单次上限, 余{len(qs) - done}题下次继续"
                    break
                qid = q.get("id")
                qtext = (q.get("c") or "").strip()
                if not qid or not qtext:
                    stats["fail"] += 1
                    continue
                try:
                    ans, _src = zhs_answer_question(qtext, [], q_type="essay")
                except Exception:
                    ans = ""
                if not ans:
                    # [V3.2.4] AI 不可用(402配额等)时话术兜底: 保证互动分可补
                    _q = (qtext or "").strip()[:20]
                    ans = (f"学习了这个话题，我对「{_q}」有了更深入的认识。"
                           f"作为新时代大学生，应当把所学知识与实践相结合，"
                           f"主动思考、积极行动，把个人成长融入国家发展之中。")
                    _log(f"[课程问答] AI无答案, 使用话术兑底 qid={qid}")
                cap.clear()
                try:
                    pg.evaluate(_JS_SUBMIT, {"qid": qid, "ans": ans[:500]})
                except Exception:
                    pass
                pg.wait_for_timeout(3200)
                resp = cap[-1] if cap else ""
                if '"answerId"' in resp:
                    stats["ok"] += 1
                    done += 1
                elif "1010" in resp or "超过最大提交数" in resp:
                    stats["limited"] += 1
                    stats["note"] = "触发平台限流(超过最大提交数), 稍后再试"
                    _log("[课程问答] 触发平台限流1010, 停止本轮")
                    break
                elif "已回答过" in resp:
                    stats["dup"] += 1
                    done += 1
                else:
                    stats["fail"] += 1
                    _log(f"[课程问答] 提交失败 qid={qid} resp={resp[:100]}")
                time.sleep(0.8)
        finally:
            try:
                b.close()
            except Exception:
                pass
    _log(f"[课程问答] 课程【{cname}】结果: 题{stats['total']} 成功{stats['ok']} "
         f"重复{stats['dup']} 失败{stats['fail']} 限流{stats['limited']} {stats['note']}")
    return stats
