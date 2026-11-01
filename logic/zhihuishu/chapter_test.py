# -*- coding: utf-8 -*-
"""[V3.2.3] 智慧树 章节测试(onlineexamh5new) 自动作答模块（2026-10-26 逆向+实测）

链路（全部实测验证）:
  ① 列表: ShareCourseAPIClient.video_list(rid) -> videoChapterDtos[].studentExamDto
     examUrl = //onlineexamh5new.zhihu.../dohomework/{recruitId}/{stuExamId}/{examId}/{courseId}/{schoolId}/0
  ② 进入/拿卷: POST studentexam-api /student/doHomework
     {recruitId, examId, studentExamId, schoolId, courseId}
  ③ 逐题保存: POST /answer/saveStudentAnswer
     参数 stuExamAnswer = JSON字符串[{examId,recruitId,stuExamId,eid,answer(选项id),schoolId,questionType}]
     ⚠ eid 由前端加密生成(密钥未公开) -> 采用"页面内点击作答"由页面自身完成保存
  ④ 交卷: POST /answer/submit {recruitId, examId, stuExamId, achieveCount}
     返回 rt.msg=提交成功 + rt.score

实现策略: 页面内自动作答(Playwright):
  登录态 cookie 注入 -> 打开章节测试页 -> 逐题(题干+选项) -> 多源答题 -> 按选项文本点击
  -> 题号校验/题号栏兜底切题 -> 全部后点"提交作业" -> 确认 -> 抓 submit 得分
  安全保护: 0 题作答/空卷禁止提交; 卡题保护(题号不前进即止损)

配置开关: coursesCustom.zhs_chapter_test_sw (默认 0=关)
"""
import re
import time


def _parse_chapters(vl_data):
    """从 video_list 响应解析章节测试列表"""
    out = []
    for i, ch in enumerate((vl_data or {}).get("videoChapterDtos") or []):
        dto = ch.get("studentExamDto") or {}
        eu = dto.get("examUrl") or ""
        m = re.search(
            r"dohomework/(\d+)/([^/]+)/([^/]+)/(\d+)/(\d+)/(\d+)", eu)
        if not m:
            continue
        out.append({
            "idx": i + 1,
            "name": ch.get("name") or "",
            "recruitId": m.group(1),
            "stuExamId": m.group(2),
            "examId": m.group(3),
            "courseId": m.group(4),
            "schoolId": m.group(5),
            "state": dto.get("state"),
            "score": dto.get("score"),
            "examUrl": eu,
        })
    return out


_GETQ_JS = """() => {
    var vis = [...document.querySelectorAll('div.examquestions-answer')].filter(e=>e.offsetParent!==null);
    if (!vis.length) return {title: '', opts: [], qtype: '', no: 0};
    var qbox = vis[0].closest('.examPaper_subject') || vis[0].closest('div');
    var mark = qbox.querySelector('.subject_type');
    var stem = qbox.querySelector('.subject_stem');
    var clone = stem ? stem.cloneNode(true) : null;
    if (clone) clone.querySelectorAll('.subject_node').forEach(e=>e.remove());
    var title = clone ? (clone.innerText||'') : '';
    title = title.replace(/【[^】]*】/g,'').replace(/\\(\\d+分\\)/g,'').replace(/\\s+/g,' ').trim().slice(0,160);
    var m2 = title.match(/^(\\d+)[.\\.、]?/);
    var no = m2 ? parseInt(m2[1]) : 0;
    return {title: title, opts: vis.map(e=>(e.innerText||'').trim()).filter(Boolean),
            qtype: mark ? mark.textContent : '', no: no};
}"""
_NEXT_JS = """() => {
    var els=[...document.querySelectorAll('div,span,button,a')].filter(
        e=>e.offsetParent!==null && e.children.length===0 && (e.textContent||'').trim()==='下一题');
    if (els.length){ els[0].scrollIntoView({block:'center'}); els[0].click(); return true; }
    return false;
}"""
_JUMP_JS = """(n) => {
    var els=[...document.querySelectorAll('li.white')].filter(
        e=>e.offsetParent!==null && (e.textContent||'').trim()===String(n));
    if (els.length){ var e2=els[els.length-1]; e2.scrollIntoView({block:'center'}); e2.click(); return true; }
    return false;
}"""
_CLICK_OPT_JS = """(t) => {
    var els=[...document.querySelectorAll('div.examquestions-answer')].filter(e=>e.offsetParent!==null);
    for (var e of els){ if ((e.innerText||'').trim().indexOf(t)>=0){ e.click(); return true; } }
    return false;
}"""
_HAS_SUBMIT_JS = """() => [...document.querySelectorAll('div,span,button,a')].some(
    e=>e.offsetParent!==null && e.children.length===0 && (e.textContent||'').trim()==='提交作业')"""
_CLICK_SUBMIT_JS = """() => {
    var els=[...document.querySelectorAll('div,span,button,a')].filter(
        e=>e.offsetParent!==null && e.children.length===0 && (e.textContent||'').trim()==='提交作业');
    if (els.length){ els[els.length-1].click(); return true; } return false;
}"""
_CLICK_CONFIRM_JS = """() => {
    var els=[...document.querySelectorAll('button,div,span')].filter(
        e=>e.offsetParent!==null && e.children.length===0 && /^(确定|提交|确认提交)$/.test((e.textContent||'').trim()));
    if (els.length){ els[els.length-1].click(); return true; } return false;
}"""
_ANS_JS = """(t) => {
    var els=[...document.querySelectorAll('div.examquestions-answer')].filter(e=>e.offsetParent!==null);
    for (var e of els){ if ((e.innerText||'').trim().indexOf(t)>=0){ e.click(); return true; } }
    return false;
}"""
# [V3.2.4 真机验证] TCaptcha 真弹层检测(视口内大尺寸 drag_ele iframe; 预载隐藏帧不算)
_TCAP_JS = """() => {
    var ifrs=[...document.querySelectorAll('iframe')];
    for (var f of ifrs) {
        if (!/drag_ele|tcaptcha/.test(f.src||'')) continue;
        var r = f.getBoundingClientRect();
        if (r.width > 150 && r.height > 100 && r.top > -20 && r.top < window.innerHeight) return true;
    }
    return false;
}"""
# 末题无"下一题"时: 点"暂存作业"保存最后一题
_SAVE_DRAFT_JS = """() => {
    var els=[...document.querySelectorAll('div,span,button,a')].filter(
        e=>e.offsetParent!==null && e.children.length===0 && (e.textContent||'').trim()==='暂存作业');
    if (els.length){ els[0].click(); return true; } return false;
}"""

_QMAP = {"单选题": "single_choice", "多选题": "multiple_choice",
         "判断题": "judge", "填空题": "fill"}


def _answer_for(title: str, opts, qtype: str):
    """多源答题 -> (answer, src)"""
    try:
        from logic.zhihuishu.answer_bridge import zhs_answer_question
        return zhs_answer_question(title, opts, q_type=qtype)
    except Exception:
        return "", ""


def _targets_from_answer(ans: str, opts):
    """答案 -> 目标选项文本列表"""
    targets = []
    if not ans:
        return targets
    a = ans.strip()
    if all(ch in "ABCDEFGH" for ch in a.replace(",", "").replace("，", "")) and len(a) <= 8:
        idxs = [ord(ch) - 65 for ch in a.upper() if ch.isalpha()]
        return [opts[i] for i in idxs if 0 <= i < len(opts)]
    for part in [x.strip() for x in a.replace("，", ",").split(",") if x.strip()]:
        hit = next((o for o in opts if part and (
            part in o or o in part)), None)
        if hit:
            targets.append(hit)
    return targets


def run_chapter_tests(cache, user, course, log=print, only=None):
    """页面内自动完成课程全部章节测试。

    :param only: 限定章节 idx 列表(如 [5,6,7]); None=全部
    :return: {"chapters":[{idx,name,answered,submitted,score,note}], "submitted":n}
    """
    result = {"chapters": [], "submitted": 0}
    try:
        from logic.zhihuishu.api import ShareCourseAPIClient
    except Exception as e:
        log(f"章节测试: 依赖不可用 {str(e)[:80]}")
        return result
    rid = str(getattr(course, "rid", "") or "")
    if not rid:
        log("章节测试: 课程缺 rid, 跳过")
        return result
    gw = ShareCourseAPIClient(cache.session)
    gw.ensure_session()
    try:
        vl = gw.video_list(rid)
    except Exception as e:
        log(f"章节测试: 目录拉取异常 {str(e)[:80]}")
        return result
    chapters = _parse_chapters(vl.get("data") or {})
    if only:
        chapters = [c for c in chapters if c["idx"] in only]
    if not chapters:
        log("章节测试: 未发现章节测试")
        return result
    jar = {}
    try:
        for ck in cache.session.cookies:
            if ck.name and ck.value:
                jar[ck.name] = ck.value
    except Exception:
        pass
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log(f"章节测试: playwright 不可用 {str(e)[:60]}")
        return result
    cookies = [{"name": k, "value": str(v), "domain": ".zhihuishu.com",
                "path": "/"} for k, v in jar.items()]
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(
            # [V3.2.4 真机验证] PC UA+桌面视口(旧移动UA下"下一题"点不动=卡题根因)
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900})
        ctx.add_cookies(cookies)
        for ch in chapters:
            rec = {"idx": ch["idx"], "name": ch["name"], "answered": 0,
                   "submitted": False, "score": None, "note": ""}
            pg = ctx.new_page()
            sub_res = []
            saved_evt = {"t": 0.0}

            def _on_resp(r, _sr=sub_res):
                if "/answer/submit" in r.url and r.request.method == "POST":
                    try:
                        _sr.append(r.text()[:300])
                    except Exception:
                        pass
                if "/answer/saveStudentAnswer" in r.url:
                    saved_evt["t"] = time.time()
            pg.on("response", _on_resp)
            url = ("https://onlineexamh5new.zhihuishu.com/stuExamWeb.html"
                   f"#/webExamList/dohomework/{ch['recruitId']}/{ch['stuExamId']}"
                   f"/{ch['examId']}/{ch['courseId']}/{ch['schoolId']}/0")
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(12000)
                if not pg.evaluate(_HAS_SUBMIT_JS):
                    rec["note"] = "已提交/无作答入口"
                    log(f"章节测试 章{ch['idx']} {ch['name']}: 已提交或无入口, 跳过")
                    pg.close()
                    continue
                seen_nos = set()
                for qi in range(16):
                    # [V3.2.4] TCaptcha真弹层: 等5s, 仍弹则提交已答部分
                    if pg.evaluate(_TCAP_JS):
                        log(f"章节测试 章{ch['idx']}: TCaptcha弹层, 等待5s")
                        pg.wait_for_timeout(5000)
                        if pg.evaluate(_TCAP_JS):
                            rec["note"] = "TCaptcha拦截, 提交已答"
                            log(f"章节测试 章{ch['idx']}: TCaptcha仍拦截")
                            break
                    info = pg.evaluate(_GETQ_JS)
                    title = (info.get("title") or "").strip()
                    opts = info.get("opts") or []
                    qno = int(info.get("no") or 0)
                    if not title or not opts:
                        break
                    if qno and qno in seen_nos:
                        # 兑底1: Playwright 真实鼠标强制点击(绕过遮挡/可操作性检查)
                        try:
                            pg.get_by_text("下一题", exact=True).first.click(
                                force=True, timeout=3000)
                        except Exception:
                            pass
                        time.sleep(1.0)
                        info = pg.evaluate(_GETQ_JS)
                        title = (info.get("title") or "").strip()
                        opts = info.get("opts") or []
                        qno2 = int(info.get("no") or 0)
                        if qno2 and qno2 in seen_nos:
                            # 兑底2: 题号栏跳转
                            pg.evaluate(_JUMP_JS, (max(seen_nos) + 1)
                                        if seen_nos else 2)
                            time.sleep(1.0)
                            info = pg.evaluate(_GETQ_JS)
                            title = (info.get("title") or "").strip()
                            opts = info.get("opts") or []
                            qno3 = int(info.get("no") or 0)
                            if qno3 and qno3 in seen_nos:
                                rec["note"] = f"卡题(题号不前进, 停于{qno3})"
                                log(f"章节测试 章{ch['idx']}: 卡题保护 @题{qno3}")
                                break
                            qno = qno3
                        else:
                            qno = qno2
                    if qno:
                        seen_nos.add(qno)
                    qt = ""
                    for k2 in _QMAP:
                        if k2 in (info.get("qtype") or ""):
                            qt = _QMAP[k2]
                            break
                    ans, src = _answer_for(title, opts, qt)
                    if qt == "judge" and ans:
                        ans = (ans.replace("正确", "对").replace("错误", "错")
                               .replace("√", "对").replace("×", "错"))
                    sel_n = 0
                    for t in _targets_from_answer(ans, opts):
                        if pg.evaluate(_ANS_JS, t):
                            sel_n += 1
                        time.sleep(0.22)
                    if sel_n:
                        rec["answered"] += 1
                    log(f"章节测试 章{ch['idx']} 题{qno or qi+1}: "
                        f"{title[:28]} [{qt}] ans={ans[:18]} 选中={sel_n}")
                    # 等选项保存(saveStudentAnswer)响应完成 + 页面重渲染, 再切题
                    if sel_n:
                        _t0 = time.time()
                        while time.time() - _t0 < 5.0:
                            if saved_evt["t"] >= _t0 - 0.1:
                                break
                            time.sleep(0.15)
                        pg.wait_for_timeout(900)
                    else:
                        pg.wait_for_timeout(300)
                    # [V3.2.4 真机验证] 切题: 直接点"下一题"(叶子精确文本),
                    # 末题无"下一题" -> 点"暂存作业"保存最后一题
                    if pg.evaluate(_NEXT_JS):
                        pg.wait_for_timeout(2600)
                        continue
                    if pg.evaluate(_SAVE_DRAFT_JS):
                        pg.wait_for_timeout(2500)
                        log(f"章节测试 章{ch['idx']}: 末题暂存保存")
                    break
                log(f"章节测试 章{ch['idx']} 作答: {rec['answered']} 题")
                if rec["answered"] <= 0:
                    rec["note"] = "0题作答, 保护不提交"
                    log(f"章节测试 章{ch['idx']}: 保护(空卷不提交)")
                    pg.close()
                    continue
                ok_sub = pg.evaluate(_CLICK_SUBMIT_JS)
                pg.wait_for_timeout(2000)
                ok_conf = pg.evaluate(_CLICK_CONFIRM_JS)
                pg.wait_for_timeout(8000)
                for s in sub_res:
                    m = re.search(r'"score":"?([\d.]+)', s)
                    if m:
                        rec["score"] = m.group(1)
                rec["submitted"] = bool(sub_res) or bool(ok_sub and ok_conf)
                if not sub_res and ok_sub:
                    rec["note"] = (rec["note"] + " 已点提交(响应未捕获)").strip()
                if rec["submitted"]:
                    result["submitted"] += 1
                log(f"章节测试 章{ch['idx']} 提交: {rec['submitted']} "
                    f"得分={rec['score']}")
            except Exception as e:
                rec["note"] = f"异常 {type(e).__name__}: {str(e)[:80]}"
                log(f"章节测试 章{ch['idx']} 异常: {str(e)[:100]}")
            finally:
                try:
                    pg.close()
                except Exception:
                    pass
            result["chapters"].append(rec)
            time.sleep(1.5)
        b.close()
    return result
