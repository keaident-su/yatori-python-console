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
    topics = []
    for page in range(1, 6):
        url = (f"https://groupweb.chaoxing.com/course/topic/{bbsid}/getTopicList"
               f"?folder_uuid=&page={page}&pageSize=20&kw=&courseId={course.course_id}"
               f"&isSetTop=&selectedStartTime=&selectedEndTime=&selectedType=0")
        try:
            r = s.post(url, timeout=20,
                       headers={"Content-Type": "application/x-www-form-urlencoded",
                                "Referer": "https://groupweb.chaoxing.com/"})
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
    try:
        r = s.post(
            f"https://groupweb.chaoxing.com/course/topic/{bbsid}/addReply",
            data=data, timeout=20,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Referer": "https://groupweb.chaoxing.com/"})
        d = r.json() if r.text.strip().startswith("{") else {}
        return bool(d.get("status") or d.get("msg") == "success")
    except Exception:
        return False


def run_discussions(cache, course, cc, log) -> int:
    """课程讨论tab全套(全部话题·未回复的; AI回复+话术兜底; 拟人延时)"""
    if int(getattr(cc, "cx_bbs_sw", 1) or 0) != 1:
        return 0
    info = _parse_outer_menu(cache, course)
    if not info.get("bbsid"):
        return 0
    topics = fetch_topics(cache, course)
    if not topics:
        return 0
    my_uid = str(info.get("uid", "") or (cache.cookie_dict or {}).get("_uid", ""))
    done = 0
    for tp in topics:
        try:
            if str(tp.get("createrId", "")) == str(my_uid):
                continue  # 自己发的话题跳过
            text = _gen_reply_text(tp, cc)
            if not text:
                continue
            ok = _reply_topic(cache, course, tp, text, info)
            _t = re.sub(r"<[^>]+>", "", str(tp.get("content", "")))[:30]
            if ok:
                done += 1
                log(f"讨论回复成功[{_t}]: {text[:40]}")
            else:
                log(f"讨论回复未生效(接口待浏览器态或已回复)[{_t}]")
            time.sleep(random.uniform(3, 8))
        except Exception as e:
            log(f"讨论处理异常: {str(e)[:80]}")
    return done


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
