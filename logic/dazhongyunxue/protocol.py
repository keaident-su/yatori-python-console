# -*- coding: utf-8 -*-
"""大众云学 纯协议学习模块(2026-10-22 实测突破)

核心链路(全实测验证):
  1. my-class.gson?myClassId=  → data.courseList[].videoRPs[]
     每讲: myClassCourseVideoId / myClassCourseId / videoSource(百家云vid数字)
  2. POST /train/cms/my-video/cv.gson  (每20秒一次=平台计时心跳)
       myClassId, myClassCourseId, myClassCourseVideoId,
       watchInfo={"vid":<videoSource>,"pid":"BAIJIAYUN_"+32hex随机,
                  "playduration":<累计秒>,"timestamp":<毫秒>},
       isCalculateclassHourFlag=true
     服务端规则(实测):
       - pid 无需真实(随机BAIJIAYUN_+32hex 即回"正常计时!")
       - playduration 增量 > 实际时间流逝 → "非法的参数!(time)" (1倍速封顶)
       - 正常时服务端按真实时间差累计, 返回 [entry,entry] 课程/视频学习率
       - 讲播完(videoLearnRate≈100)后切换下一讲继续
"""
import json
import random
import time
import urllib.parse
from typing import Dict, List, Optional

from logic.dazhongyunxue import api as dzyx_api


def _rand_pid() -> str:
    return "BAIJIAYUN_" + "".join(
        random.choice("0123456789ABCDEF") for _ in range(32))


def fetch_video_plans(client: "dzyx_api.DzyxClient",
                      my_class_id: str) -> List[dict]:
    """从 my-class.gson 提取各讲学习计划

    实测结构(2026-10-22): attribute.data.myClassCourseRPList[].videoRPs[]
      · baiJiaYunVideoSource = 百家云数字vid
      · watchTimeLength / duration = 已看秒 / 总秒
    """
    d = client._gson("/train/class/my-class.gson",
                     {"myClassId": my_class_id})
    data = (d.get("attribute") or {}).get("data") or {}
    plans = []
    for course in (data.get("myClassCourseRPList") or []):
        for rp in (course.get("videoRPs") or []):
            vid = str(rp.get("baiJiaYunVideoSource") or "")
            if not vid.isdigit():
                continue
            plans.append({
                "myClassCourseId": rp.get("myClassCourseId", ""),
                "myClassCourseVideoId": rp.get("myClassCourseVideoId", ""),
                "vid": vid,
                "watched": int(rp.get("watchTimeLength") or 0),
                "duration": int(rp.get("duration") or 0),
                "name": str(rp.get("videoName") or "")[:24],
            })
    return plans


def report_heartbeat(client: "dzyx_api.DzyxClient", my_class_id: str,
                     plan: dict, pid: str, play_seconds: int) -> tuple:
    """发一次cv.gson计时心跳; 返回(status_desc, courseRate, videoRate)"""
    watch = {
        "vid": plan["vid"],
        "pid": pid,
        "playduration": int(play_seconds),
        "timestamp": int(time.time() * 1000),
    }
    fd = {
        "myClassId": my_class_id,
        "myClassCourseId": plan["myClassCourseId"],
        "myClassCourseVideoId": plan["myClassCourseVideoId"],
        "watchInfo": json.dumps(watch, separators=(",", ":")),
        "isCalculateclassHourFlag": "true",
    }
    r = client.s.post(client.base + "/train/cms/my-video/cv.gson",
                      data=fd, timeout=20,
                      headers={"X-Requested-With": "XMLHttpRequest"})
    try:
        d = r.json()
        dd = (d.get("attribute") or {}).get("data") or {}
        return (str(dd.get("respDesc", "")),
                float(dd.get("courseLearnRate") or 0),
                float(dd.get("videoLearnRate") or 0))
    except Exception:
        return (f"HTTP{r.status_code}", 0.0, 0.0)


def run_protocol_study(client: "dzyx_api.DzyxClient", my_class_id: str,
                       log=print, interval: int = 20,
                       max_hours: float = 8.0) -> dict:
    """纯协议刷课: 逐讲按1倍速节奏心跳, 直到课程完成

    返回统计 {rounds, courseRate, done}
    """
    plans = fetch_video_plans(client, my_class_id)
    if not plans:
        log("未找到视频学习计划(myClassCourseRPList为空)")
        return {"rounds": 0, "courseRate": 0.0, "done": False}
    todo = [p for p in plans if p["watched"] < p["duration"]]
    if not todo:
        log("全部讲已完成")
        return {"rounds": 0, "courseRate": 100.0, "done": True}
    log(f"纯协议学习: {len(todo)}讲待播(每{interval}秒心跳, 1倍速)")
    t_start = time.time()
    rounds = 0
    cur_rate = 0.0
    for plan in todo:
        play = plan["watched"]
        pid = _rand_pid()
        fails = 0
        while time.time() - t_start < max_hours * 3600:
            last = time.time()
            play += interval
            desc, cr, vr = report_heartbeat(client, my_class_id, plan,
                                            pid, play)
            rounds += 1
            cur_rate = cr or cur_rate
            if rounds % 3 == 0:
                log(f"  [{rounds}轮] {desc[:26]} | 课程{cr:.2f}% 本讲{vr:.2f}% [{plan['name']}]")
            if vr >= 99.9:
                log(f"  ✅本讲完成: {plan['name']} (课程{cr:.2f}%)")
                break
            if "非法" in desc:
                fails += 1
                time.sleep(interval)
                if fails > 5:
                    log(f"  连续非法参数, 跳出本讲: {plan['name']}")
                    break
                continue
            fails = 0
            elapsed = time.time() - last
            rest = interval - elapsed
            if rest > 0:
                time.sleep(rest)
        time.sleep(random.uniform(2, 5))
    log(f"纯协议学习结束: {rounds}轮, 课程进度{cur_rate:.2f}%")
    return {"rounds": rounds, "courseRate": cur_rate,
            "done": cur_rate >= 99.9}
