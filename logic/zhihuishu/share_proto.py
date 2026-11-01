# -*- coding: utf-8 -*-
"""智慧树新版共享课(studyvideoh5) 协议级刷课模块

2026-10-13 实战验证: 账号138****0553《从课堂走出来的创新》24/24节全绿。
本模块将实战脚本(_zhs_full24.py / _zhs_touchup8.py)工程化固化, 供长期维护复用。

## 链路
login_password(易盾纯协议) -> ShareCourseAPIClient.ensure_session(gologin)
 -> video_list(rid) 拉取 videoChapterDtos[章].videoLessons[节]
 -> 逐节 prelearningNote 获取 studiedLessonDto.id -> zwsds=base64(id)
 -> save_database_time(DB层) + save_cache_time(cache层) 双上报
 -> code=-8("学习总时长下降了")时对 cache 层梯度推送覆盖历史高值
 -> 可选复核(读回 learnTimeSec)

## -8 拦截破解(关键)
服务端对"推送值 < 当前缓存值(历史播放累计)"判 -8。
破解: total 从视频时长 sec 起梯度 +30/+60/+150/+300/+600/+900/+1200/+2500/+4000
直到 code=0; 极端节(1.1, 历史反复播放累计高)需到 4580 才过。

## 用法(命令行)
python -m logic.zhihuishu.share_proto --account 138xxxx --password xxx \
    [--rid 4e5b...] [--cc-course-id 1000125370] [--recruit-id 431867] [--verify]
省略 --rid 时自动从学堂课列表解析(secret 字段=rid)。

## 用法(代码)
from logic.zhihuishu.share_proto import brush_share_protocol, resolve_rid
stats = brush_share_protocol(cache, rid, cc_course_id, recruit_id, log=print)
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from logic.platform_common import get_simple_logger
from logic.zhihuishu.api import ShareCourseAPIClient

logger = get_simple_logger("[智慧树-协议刷]")

# 梯度补刀步进(-8破解): 从 sec 起的附加增量序列(实测4580上限可覆盖极端历史值)
_GRACE_STEPS = (0, 30, 60, 90, 150, 300, 600, 900, 1200, 2500, 4000)

# 完成阈值(与平台口径对齐: 章 isPass / UI 绿)
_COMPLETE_RATIO = 0.91


def X(s: str) -> str:
    """sdsew 加密: 每字符 ord(c)^ord("zzpttjd"[i%7]) 转2位hex拼接"""
    key = "zzpttjd"
    return "".join("%02x" % (ord(c) ^ ord(key[i % 7])) for i, c in enumerate(s))


def hhmmss(sec: int) -> str:
    """秒 -> HH:MM:SS"""
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def _uuid_of(cli: ShareCourseAPIClient) -> str:
    """从 CASLOGC cookie 取 uuid(sdsew 数组尾部使用 uuid+"zhs")"""
    import urllib.parse
    try:
        raw = cli._session.session.cookies.get(
            "CASLOGC", domain=".zhihuishu.com")
        return json.loads(urllib.parse.unquote(raw or "{}")).get("uuid", "")
    except Exception:
        return ""


def resolve_rid(cli: ShareCourseAPIClient, cc_course_id: int) -> str:
    """通过学堂课列表解析课程的 recruitAndCourseId(rid)

    学堂列表接口 student/course/share 响应的 secret 字段即真实 rid。
    失败返回空串(调用方可手工传 --rid)。
    """
    try:
        body = cli._gw("student/course/share/queryShareCourseInfo",
                       {"courseId": cc_course_id})
        data = (body or {}).get("data") or {}
        secret = data.get("secret") or ""
        if secret:
            return str(secret)
        for c in (data.get("courseList") or []):
            if str(c.get("courseId")) == str(cc_course_id) and c.get("secret"):
                return str(c.get("secret"))
    except Exception as e:
        logger.warning("resolve_rid 失败: %s", str(e)[:120])
    return ""


def list_lessons(cli: ShareCourseAPIClient, rid: str) -> List[Dict[str, Any]]:
    """拉取课程章节树 -> 扁平节列表 [{cid,lid,vid,sec,name,chapter}]"""
    vl = cli.video_list(rid)
    chapters = ((vl or {}).get("data") or {}).get("videoChapterDtos") or []
    out: List[Dict[str, Any]] = []
    for ch in chapters:
        for ls in (ch.get("videoLessons") or []):
            out.append({
                "cid": ch.get("id"),
                "chapter": str(ch.get("name") or ""),
                "lid": ls.get("id"),
                "vid": ls.get("videoId"),
                "sec": int(ls.get("videoSec") or 0),
                "name": str(ls.get("name") or ""),
            })
    return out


def _prelearning(cli: ShareCourseAPIClient, cc_course_id: int,
                 recruit_id: int, lesson: Dict[str, Any]
                 ) -> Tuple[Optional[Any], int]:
    """prelearningNote: 返回 (studiedLessonDto.id, 当前learnTimeSec)"""
    pl = dict(ccCourseId=cc_course_id, chapterId=lesson["cid"], isApply=1,
              lessonId=lesson["lid"], recruitId=recruit_id,
              videoId=lesson["vid"])
    r0 = cli._gw("learning/prelearningNote", pl)
    sld = ((r0 or {}).get("data") or {}).get("studiedLessonDto") or {}
    return sld.get("id"), int(sld.get("learnTimeSec") or 0)


def _push_db(cli: ShareCourseAPIClient, cc_course_id: int, recruit_id: int,
             uuid: str, lesson: Dict[str, Any], total: int) -> Any:
    """save_database_time(DB层, 带 courseId)"""
    sec = lesson["sec"]
    n_p = int(total / 5) + 2
    ew = "0,1," + ",".join(str(v) for v in range(2, n_p + 1))
    arr = [recruit_id, lesson["lid"], 0, lesson["vid"], lesson["cid"], 0,
           n_p, total, hhmmss(total), uuid + "zhs"]
    payload = {"ewssw": ew, "sdsew": X(";".join(str(x) for x in arr)),
               "zwsds": base64.b64encode(str(lesson["_sld_id"]).encode()).decode(),
               "courseId": cc_course_id}
    return cli.save_database_time(payload)


def _push_cache(cli: ShareCourseAPIClient, cc_course_id: int, recruit_id: int,
                uuid: str, lesson: Dict[str, Any], total: int) -> Any:
    """save_cache_time(cache层, 不带 courseId)"""
    n_p = int(total / 5) + 2
    ew = "0,1," + ",".join(str(v) for v in range(2, n_p + 1))
    arr = [recruit_id, lesson["cid"], cc_course_id, lesson["lid"],
           hhmmss(total), total, lesson["vid"], 0, n_p, uuid + "zhs"]
    payload = {"ewssw": ew, "sdsew": X(";".join(str(x) for x in arr)),
               "zwsds": base64.b64encode(str(lesson["_sld_id"]).encode()).decode()}
    return cli.save_cache_time(payload)


def _ok(resp: Any) -> bool:
    return (resp or {}).get("code") in (0, 200, "0", "200")


def brush_share_protocol(cache, rid: str, cc_course_id: int,
                         recruit_id: int,
                         log: Optional[Callable[[str], None]] = None,
                         verify: bool = True) -> Dict[str, Any]:
    """协议级刷课主入口(全量+补刀)

    :param cache: ZhsUserCache(已登录, 含 session)
    :param rid: recruitAndCourseId(课程 secret)
    :param cc_course_id: ccCourseId(如 1000125370)
    :param recruit_id: recruitId(如 431867)
    :return: stats {total, full, pushed, skipped, failed, elapsed}
    """
    def _log(msg: str) -> None:
        try:
            logger.info(msg)
        except Exception:
            pass
        if log:
            try:
                log(msg)
            except Exception:
                pass

    cli = ShareCourseAPIClient(cache.session)
    cli.ensure_session()
    uuid = _uuid_of(cli)
    lessons = list_lessons(cli, rid)
    stats = {"total": len(lessons), "full": 0, "pushed": 0,
             "skipped": 0, "failed": 0, "elapsed": 0.0}
    t0 = time.time()
    _log("共 %d 节, 开始协议刷..." % len(lessons))

    for i, l in enumerate(lessons):
        sec = l["sec"]
        if sec <= 0:
            stats["skipped"] += 1
            continue
        try:
            sld_id, learn = _prelearning(cli, cc_course_id, recruit_id, l)
        except Exception as e:
            stats["failed"] += 1
            _log("  %2d. %s prelearning异常: %s" %
                 (i + 1, l["name"][:18], str(e)[:60]))
            continue
        if not sld_id:
            stats["failed"] += 1
            continue
        if learn >= sec * _COMPLETE_RATIO:
            # 已达标: 跳过推送(仍计入完成)
            stats["full"] += 1
            _log("  %2d. %s 已达标(learn=%d/%d)" %
                 (i + 1, l["name"][:18], learn, sec))
            continue
        l["_sld_id"] = sld_id
        ok_db = ok_ck = False
        try:
            r1 = _push_db(cli, cc_course_id, recruit_id, uuid, l, sec)
            ok_db = _ok(r1)
            time.sleep(1.0)
            r2 = _push_cache(cli, cc_course_id, recruit_id, uuid, l, sec)
            ok_ck = _ok(r2)
            # -8梯度补刀
            if not ok_db or not ok_ck:
                for extra in _GRACE_STEPS[1:]:
                    total = sec + extra
                    rg = _push_cache(cli, cc_course_id,
                                     recruit_id, uuid, l, total)
                    if _ok(rg):
                        ok_ck = True
                        # DB 同步同值
                        try:
                            _push_db(cli, cc_course_id,
                                     recruit_id, uuid, l, total)
                        except Exception:
                            pass
                        break
                    time.sleep(1.0)
        except Exception as e:
            _log("  %2d. %s 上报异常: %s" % (i + 1, l["name"][:18], str(e)[:60]))
        if ok_ck or ok_db:
            stats["pushed"] += 1
            stats["full"] += 1
        else:
            stats["failed"] += 1
        _log("  %2d. %s sec=%d | DB=%s CK=%s" % (
            i + 1, l["name"][:18], sec, "0" if ok_db else "-", "0" if ok_ck else "-"))
        time.sleep(1.2)

    stats["elapsed"] = round(time.time() - t0, 1)
    _log("完成: %d/%d (推送%d 跳过%d 失败%d, 耗时%.0fs)" % (
        stats["full"], stats["total"], stats["pushed"],
        stats["skipped"], stats["failed"], stats["elapsed"]))
    if verify:
        full2 = 0
        for l in lessons:
            try:
                _, learn = _prelearning(cli, cc_course_id, recruit_id, l)
                if l["sec"] > 0 and learn >= l["sec"]:
                    full2 += 1
            except Exception:
                pass
        _log("复核: 学习记录满额 %d/%d" % (full2, len(lessons)))
        stats["verified_full"] = full2
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="智慧树新版共享课协议级刷课")
    ap.add_argument("--account", required=True, help="智慧树账号(手机号)")
    ap.add_argument("--password", required=True, help="密码(含易盾纯协议自动处理)")
    ap.add_argument("--rid", default="", help="recruitAndCourseId(可省略,自动解析)")
    ap.add_argument("--cc-course-id", type=int, default=0, help="ccCourseId")
    ap.add_argument("--recruit-id", type=int, default=0, help="recruitId")
    ap.add_argument("--no-verify", action="store_true", help="跳过复核")
    args = ap.parse_args()

    from config.config import User, CoursesCustom
    from logic.zhihuishu.api import login_password, ManagedSession

    session = ManagedSession()
    login_password(session, args.account, args.password)
    cache = type("_C", (), {})()
    cache.session = session

    rid = args.rid
    if not rid and args.cc_course_id:
        cli0 = ShareCourseAPIClient(session)
        cli0.ensure_session()
        rid = resolve_rid(cli0, args.cc_course_id)
        print("[解析] rid =", rid)
    if not rid:
        print("缺少 --rid 且无法自动解析, 请手工提供")
        sys.exit(1)
    stats = brush_share_protocol(
        cache, rid, args.cc_course_id, args.recruit_id,
        log=lambda m: print(m), verify=not args.no_verify)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
