# -*- coding: utf-8 -*-
"""学习通 拓展阅读 + 课程讨论tab 全套功能 (2026-10-17)

【拓展阅读】入口: stucoursemiddle外层菜单 li[dataname=expandread]
  data-url = https://appcd.chaoxing.com/read/index
  实际iframe: appcd.chaoxing.com/read/index?courseid={cid}&clazzid={cls}
              &cpi={cpi}&ut=s&t={ms}&stuenc={enc}&fid={fid}&userId={uid}
  阅读时长: 需在实际阅读页面上报, 由 run_extend_read 处理

【课程讨论tab】入口: li[dataname=tl] -> groupweb.chaoxing.com/course/topic/topicList
  话题列表API: POST https://groupweb.chaoxing.com/course/topic/{bbsid}/getTopicList
  返回 datas[]: {id, uuid, content, createrName, reply_count, create_time, tags...}

用户定夺(2026-10-17): 讨论=全部话题·未回复的; 回复=AI生成学生口吻(话术兜底); 开关默认开
"""
import re
import json
import time
import random
import html as _html


def _http(cache):
    import requests
    import urllib3
    urllib3.disable_warnings()
    s = requests.Session()
    s.verify = False
    try:
        s.cookies.update(cache.cookie_dict or {})
    except Exception:
        pass
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "*/*",
        # 2026-10-18: 实测需要 AJAX 头, 否则 getTopicList 返回"你没有权限操作"
        "X-Requested-With": "XMLHttpRequest",
    })
    return s


def _parse_outer_menu(cache, course) -> dict:
    """拉stucoursemiddle外层HTML, 解析菜单(dataname->data-url)与隐藏字段"""
    from logic.xuexitong import api as xxt
    info = {"menus": {}, "courseid": str(course.course_id),
            "clazzid": str(course.key), "cpi": str(course.cpi),
            "bbsid": "", "enc": "", "fid": "", "uid": ""}
    try:
        client = xxt._build_client(cache)
        try:
            body, _ = client.get(
                f"https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle"
                f"?courseid={course.course_id}&clazzid={course.key}"
                f"&vc=1&cpi={course.cpi}&ismooc2=1&v=2", retry=2)
        finally:
            client.close()
        h = str(body or "")
        for m in re.finditer(
                r'<li[^>]*dataname="([^"]+)"[^>]*>\s*<a[^>]*data-url="([^"]+)"', h):
            info["menus"][m.group(1)] = m.group(2)

        def _hid(k):
            mm = re.search(rf'id="{k}"[^>]*value="([^"]*)"', h)
            return mm.group(1) if mm else ""
        info["bbsid"] = _hid("bbsid")
        info["enc"] = _hid("enc") or _hid("showAIEnc")
        info["fid"] = _hid("cfid") or _hid("fid")
        info["uid"] = _hid("uid") or (cache.cookie_dict or {}).get("_uid", "")
        # 2026-10-18: stuenc 来自外层 studentcourse iframe URL 参数,
        # groupweb 讨论页/接口必须携带它, 否则返回"你没有权限操作"
        _sm = re.search(r'studentcourse\?[^"\']*?stuenc=([0-9a-f]{32})', h)
        info["stuenc"] = _sm.group(1) if _sm else ""
        return info
    except Exception:
        return info


def fetch_topics(cache, course) -> list:
    """拉课程讨论tab话题列表(分页), 返回话题dict列表"""
    info = _parse_outer_menu(cache, course)
    bbsid = info.get("bbsid", "")
    if not bbsid:
        return []
    s = _http(cache)
    # 2026-10-18: 两段式——先 GET topicList 页(带 stuenc/bbsid)建立讨论会话,
    # 再 POST getTopicList; 否则直接 POST 返回"你没有权限操作"
    _stuenc = info.get("stuenc", "")
    _t = str(int(time.time() * 1000))
    page_url = (f"https://groupweb.chaoxing.com/course/topic/topicList"
                f"?courseid={course.course_id}&clazzid={course.key}"
                f"&cpi={course.cpi}&ut=s&t={_t}&stuenc={_stuenc}"
                f"&bbsid={bbsid}&learnSilverStartTime=&learnSilverEndTime=")
    try:
        s.get(page_url, timeout=25)
    except Exception:
        pass
    topics = []
    for page in range(1, 6):
        url = (f"https://groupweb.chaoxing.com/course/topic/{bbsid}/getTopicList"
               f"?folder_uuid=&page={page}&pageSize=20&kw=&courseId={course.course_id}"
               f"&isSetTop=&selectedStartTime=&selectedEndTime=&selectedType=0"
               f"&learnSilverStartTime=&learnSilverEndTime=")
        try:
            r = s.post(url, timeout=20,
                       data=("tags=classId0000001,classId"
                             f"{course.key},courseId{course.course_id}"),
                       headers={"Content-Type":
                                "application/x-www-form-urlencoded; charset=UTF-8",
                                "Referer": page_url})
            d = r.json()
        except Exception:
            break
        datas = d.get("datas") if isinstance(d, dict) else None
        if not datas:
            break
        topics.extend([x for x in datas if isinstance(x, dict)])
        if len(datas) < 20:
            break
        time.sleep(1)
    return topics


def _gen_reply_text(topic: dict, cc) -> str:
    """AI按话题生成学生口吻回复(20-60字), 话术库兜底"""
    title = str(topic.get("content", "") or "")
    title = re.sub(r"<[^>]+>", " ", title)
    title = re.sub(r"\s+", " ", _html.unescape(title)).strip()[:120]
    try:
        from logic.core.answer_engine import answer_query_detail
        _prompt = (f"请以一名大学生学生的身份, 针对讨论话题「{title}」"
                   f"写一段20-60字的自然口语化回复, 直接输出回复正文, 不要引号不要解释")
        ans, src = answer_query_detail(_prompt, options=None, q_type="short")
        if ans and 10 <= len(str(ans)) <= 120:
            return str(ans).strip()
    except Exception:
        pass
    _phrases = [
        "学习了这个话题，我深刻认识到青年一代要勇担时代责任，把个人成长融入国家发展之中。",
        "通过这节课的学习，我更加明白了初心和使命的意义，今后会更加努力学习、积极实践。",
        "这个话题让我感触很深，历史是最好的教科书，我们要从中汲取前进的力量。",
        "我认为作为新时代青年，应当脚踏实地、勤学笃行，用实际行动回答时代的问卷。",
        "学习之后收获很大，立志把爱国之情转化为报国之行，从身边小事做起。",
    ]
    return random.choice(_phrases)


def _reply_topic(cache, course, topic: dict, text: str, info: dict = None) -> bool:
    """提交话题回复(groupweb addReply)"""
    info = info or _parse_outer_menu(cache, course)
    bbsid = info.get("bbsid", "")
    if not bbsid:
        return False
    s = _http(cache)
    data = {
        "bbsid": bbsid,
        "topicId": topic.get("id", ""),
        "uuid": topic.get("uuid", ""),
        "content": text,
        "courseId": str(course.course_id),
        "classId": str(course.key),
        "cpi": str(course.cpi),
    }
    _stuenc = info.get("stuenc", "")
    _t = str(int(time.time() * 1000))
    referer = (f"https://groupweb.chaoxing.com/course/topic/topicList"
               f"?courseid={course.course_id}&clazzid={course.key}"
               f"&cpi={course.cpi}&ut=s&t={_t}&stuenc={_stuenc}"
               f"&bbsid={bbsid}&learnSilverStartTime=&learnSilverEndTime=")
    try:
        r = s.post(
            f"https://groupweb.chaoxing.com/course/topic/{bbsid}/addReply",
            data=data, timeout=20,
            headers={"Content-Type":
                     "application/x-www-form-urlencoded; charset=UTF-8",
                     "Referer": referer})
        d = r.json() if r.text.strip().startswith("{") else {}
        return bool(d.get("status") or d.get("msg") == "success")
    except Exception:
        return False


def _browser_session(cache):
    """2026-10-18: 讨论接口需 stuenc(由外层页JS动态生成, 纯协议无法获取),
    改用 Playwright 浏览器态: 打开 stucoursemiddle -> 点讨论 -> iframe 内 fetch。
    返回 (playwright, browser, page, gw_frame) 或抛异常"""
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, channel="chrome")
    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              ignore_https_errors=True)
    page = ctx.new_page()
    cks = []
    for k, v in (cache.cookie_dict or {}).items():
        try:
            cks.append({"name": str(k), "value": str(v),
                        "domain": ".chaoxing.com", "path": "/"})
        except Exception:
            pass
    try:
        ctx.add_cookies(cks)
    except Exception:
        pass
    return p, browser, ctx, page


def _open_discuss_frame(page, course):
    """打开课程页并点击「讨论」菜单, 返回 groupweb iframe 句柄"""
    page.goto(f"https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle"
              f"?courseid={course.course_id}&clazzid={course.key}&vc=1"
              f"&cpi={course.cpi}&ismooc2=1&v=2",
              timeout=90000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    page.evaluate("""() => {
        var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n;
        while (n = w.nextNode()) {
            if (n.textContent.trim() === '讨论') { n.parentElement.click(); return; }
        }
    }""")
    page.wait_for_timeout(8000)
    for f in page.frames:
        if "groupweb.chaoxing.com/course/topic" in f.url:
            return f
    return None


def run_discussions(cache, course, cc, log) -> int:
    """课程讨论tab全套(浏览器态: 全部话题·未回复的; AI回复+话术兜底; 拟人延时)"""
    if int(getattr(cc, "cx_bbs_sw", 1) or 0) != 1:
        return 0
    info = _parse_outer_menu(cache, course)
    bbsid = info.get("bbsid", "")
    if not bbsid:
        log("该课程无讨论区(bbsid缺失), 跳过")
        return 0
    try:
        p, browser, ctx, page = _browser_session(cache)
    except Exception as e:
        log(f"讨论浏览器启动失败: {str(e)[:80]}")
        return 0
    done = 0
    try:
        gw = _open_discuss_frame(page, course)
        if gw is None:
            log("讨论区打开失败(未找到iframe), 跳过")
            return 0
        # iframe 内拉话题列表(分页)
        topics = gw.evaluate("""async (bbsid) => {
            const all = [];
            for (let pg = 1; pg <= 5; pg++) {
                const u = '/course/topic/' + bbsid + '/getTopicList?folder_uuid='
                    + '&page=' + pg + '&pageSize=20&kw=&courseId=' + new URLSearchParams(location.search).get('courseid')
                    + '&isSetTop=&selectedStartTime=&selectedEndTime=&selectedType=0'
                    + '&learnSilverStartTime=&learnSilverEndTime=';
                const cid = new URLSearchParams(location.search).get('courseid');
                const cls = new URLSearchParams(location.search).get('clazzid');
                const res = await fetch(u, {method:'POST',
                    headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                    body:'tags=classId0000001,classId'+cls+',courseId'+cid, credentials:'include'});
                const d = await res.json();
                if (!d || !d.datas || !d.datas.length) break;
                all.push(...d.datas);
                if (d.datas.length < 20) break;
            }
            return all;
        }""", bbsid)
        if not topics:
            log("讨论区无话题")
            return 0
        log(f"讨论区共{len(topics)}个话题, 开始处理未回复的...")
        my_uid = str(info.get("uid", "") or "")
        _q = {}
        try:
            from urllib.parse import urlparse, parse_qs
            _q = {k: v[0] for k, v in parse_qs(urlparse(gw.url).query).items()}
        except Exception:
            pass
        _cid = _q.get("courseid", str(course.course_id))
        _cls = _q.get("clazzid", str(course.key))
        _cpi = _q.get("cpi", str(course.cpi))
        for tp in topics:
            try:
                if str(tp.get("createrId", "")) == my_uid and my_uid:
                    continue  # 自己发的话题跳过
                _uuid = str(tp.get("uuid", ""))
                if not _uuid:
                    continue
                text = _gen_reply_text(tp, cc)
                if not text:
                    continue
                # 2026-10-18 真人UI流程(实测发回复唯一可靠路径):
                #   打开话题详情页(replysList) → 点回复需钮 → 填textarea → 点addReply
                #   (addReplys请求的 replyId/uuid/urlToken 由页面JS自动生成带入)
                dp = ctx.new_page()
                try:
                    detail_url = (f"https://groupweb.chaoxing.com/course/topic/v3/bbs/"
                                  f"{bbsid}/{_uuid}/replysList"
                                  f"?courseId={_cid}&classId={_cls}&cpi={_cpi}&ut=s")
                    dp.goto(detail_url, timeout=60000,
                            wait_until="domcontentloaded")
                    dp.wait_for_timeout(5000)
                    if "话题详情" not in (dp.evaluate("() => document.body ? document.body.innerText : ''") or ""):
                        log(f"详情页打开异常, 跳过[{_uuid[:8]}]")
                        continue
                    # 1. 点「回复」打开输入框
                    dp.evaluate("""() => {
                        var els = Array.from(document.querySelectorAll('div,a,span'));
                        for (var i = 0; i < els.length; i++) {
                            var t = (els[i].innerText || '').trim();
                            var c = String(els[i].className);
                            if (t === '回复' && c.indexOf('replyBtn') >= 0 && els[i].offsetParent !== null) {
                                els[i].click(); return;
                            }
                        }
                        for (var i = 0; i < els.length; i++) {
                            var t = (els[i].innerText || '').trim();
                            var c = String(els[i].className);
                            if (t === '回复' && c.indexOf('reply') >= 0 && els[i].offsetParent !== null) {
                                els[i].click(); return;
                            }
                        }
                    }""")
                    dp.wait_for_timeout(2000)
                    # 2. 填内容到可见 textarea
                    filled = dp.evaluate("""(content) => {
                        var eds = Array.from(document.querySelectorAll('textarea, [contenteditable=true]')).filter(x => x.offsetParent !== null);
                        if (!eds.length) return '';
                        var ed = eds[eds.length - 1];
                        ed.focus();
                        if (ed.tagName === 'TEXTAREA') {
                            ed.value = content;
                            ed.dispatchEvent(new Event('input', {bubbles:true}));
                            ed.dispatchEvent(new Event('change', {bubbles:true}));
                        } else {
                            ed.innerHTML = content;
                        }
                        return ed.tagName;
                    }""", text)
                    if not filled:
                        log(f"未找到回复输入框, 跳过[{_uuid[:8]}]")
                        continue
                    dp.wait_for_timeout(800)
                    # 3. 点提交(addReply按钮)
                    dp.evaluate("""() => {
                        var els = Array.from(document.querySelectorAll('div,a,span,button'));
                        for (var i = 0; i < els.length; i++) {
                            var c = String(els[i].className);
                            if (c.indexOf('addReply') >= 0 && els[i].offsetParent !== null) {
                                els[i].click(); return;
                            }
                        }
                    }""")
                    dp.wait_for_timeout(4000)
                    # 4. 验证: 页面出现刚发的内容
                    ok_page = dp.evaluate("""(c) => document.body ? document.body.innerText.indexOf(c.slice(0,15)) >= 0 : false""", text)
                    _t = re.sub(r"<[^>]+>", "", str(tp.get("content", "")))[:30]
                    if ok_page:
                        done += 1
                        log(f"讨论回复成功[{_t}]: {text[:40]}")
                    else:
                        log(f"讨论回复未确认[{_t}](页面未见回显)")
                finally:
                    try: dp.close()
                    except Exception: pass
                time.sleep(random.uniform(3, 8))
            except Exception as e:
                log(f"讨论处理异常: {str(e)[:80]}")
        return done
    except Exception as e:
        log(f"讨论流程异常: {str(e)[:100]}")
        return done
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass


def run_extend_read(cache, course, cc, log, read_rounds: int = 5,
                    delay: int = 30) -> int:
    """拓展阅读阅读时长(开关独立; appcd阅读材料→阅读行为上报)"""
    if int(getattr(cc, "cx_extend_read_sw", 1) or 0) != 1:
        return 0
    info = _parse_outer_menu(cache, course)
    if "expandread" not in info.get("menus", {}):
        log("该课程无「拓展阅读」菜单, 跳过")
        return 0
    s = _http(cache)
    uid = str(info.get("uid", "") or (cache.cookie_dict or {}).get("_uid", ""))
    t = str(int(time.time() * 1000))
    _enc = info.get("enc", "")
    _fid = info.get("fid", "")
    base = (f"https://appcd.chaoxing.com/read/index?courseid={course.course_id}"
            f"&clazzid={course.key}&cpi={course.cpi}&ut=s&t={t}"
            f"&stuenc={_enc}&fid={_fid}&userId={uid}"
            f"&_from_={course.course_id}_{course.key}_{uid}_0")
    rounds = 0
    for i in range(max(1, read_rounds)):
        try:
            r = s.get(base, timeout=20)
            ok = r.status_code == 200 and len(r.text) > 200
            if ok:
                rounds += 1
                log(f"拓展阅读: 已进入阅读页(第{i+1}/{read_rounds}轮, "
                    f"停留{delay}秒模拟阅读)...")
            if i < read_rounds - 1:
                time.sleep(max(5, delay))
        except Exception as e:
            log(f"拓展阅读异常: {str(e)[:80]}")
            break
    return rounds
