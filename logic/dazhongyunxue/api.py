# -*- coding: utf-8 -*-
"""大众云学(yxlearning)协议层(2026-10-22 逆向实测)

供应商泛化: 同供应商各局点仅主机名不同(<region>.<gxk|zyk>.yxlearning.com),
基地址可由配置 basicSetting.dzyxBaseUrl 指定, 缺省 xjbt.gxk。

接口清单(实测):
  登录态: cookies(storage_state 缓存复用, 滑块仅首登需要)
  GET  /train/cms/study/find-my-study-info.gson?...   学习列表(myClassId/studyStatus/score...)
  GET  /train/class/my-class.gson?myClassId=          班级详情(watchTimeLength/studyStatus...)
  GET  /train/cms/face/check/class-checkface-config.gson?myClassId=  人脸开关
  POST /train/cms/my-video/update-last-video.gson     切课记录(浏览器内自动)
  GET  /train/dictionary/get-baijiayun-token.gson?videoSource=<vid>  百家云token(浏览器内自动)
"""
import json
import os
import random
import time
from typing import Dict, List, Optional

import requests

DEFAULT_BASE = "http://xjbt.gxk.yxlearning.com"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36")


def resolve_base(setting=None, user=None) -> str:
    """基地址解析(2026-10-24, 对齐英华URL平台模式):
    账号级 url 优先(每账号可填自己的平台地址) → 全局 dzyx_base_url → 内置默认"""
    # ① 账号级 URL(与英华学堂等URL平台同语义)
    try:
        u = str(getattr(user, "url", "") or "").strip()
        if u and u.startswith("http"):
            return u.rstrip("/")
    except Exception:
        pass
    # ② 全局基地址
    try:
        u = getattr(getattr(setting, "basic_setting", None),
                    "dzyx_base_url", "") or ""
        u = u.strip()
        if u:
            return u.rstrip("/")
    except Exception:
        pass
    return DEFAULT_BASE


def state_path(account: str) -> str:
    safe = str(account).replace("/", "_").replace("\\", "_")
    return os.path.join("assets", f"dzyx_state_{safe}.json")


def load_state(account: str) -> Optional[dict]:
    p = state_path(account)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_state(account: str, state: dict) -> None:
    p = state_path(account)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, p)


def cookies_from_state(state: dict) -> Dict[str, str]:
    return {c["name"]: c["value"] for c in (state or {}).get("cookies", [])}


class DzyxClient:
    """纯协议客户端(列表/详情类只读接口; 播放必须走浏览器)"""

    def __init__(self, base: str, cookies: Dict[str, str]):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": _UA,
                               "Referer": self.base + "/index"})
        self.s.cookies.update(cookies or {})

    def _gson(self, path: str, params: Optional[dict] = None) -> dict:
        r = self.s.get(self.base + path, params=params or {}, timeout=25)
        try:
            return r.json()
        except ValueError:
            return {}

    def study_list(self) -> List[dict]:
        """我的学习列表(兼容 gxk 公需 + zyk 专业课两站)

        2026-10-22 实测: gxk 站 orderBy=1 即学习列表; zyk 站需 orderBy=0&subject=0
        才能拉到"学习任务(通配任务)"下的课程(否则为空)。双查询合并去重。
        """
        merged: Dict[str, dict] = {}
        variants = [
            {"orderBy": 1, "subject": ""},
            {"orderBy": 0, "subject": 0},
        ]
        for v in variants:
            d = self._gson("/train/cms/study/find-my-study-info.gson", {
                "studyStatus": "", "mylearnTaskId": "", "attribute": "",
                "subject": v["subject"], "searchYear": "",
                "orderBy": v["orderBy"],
                "mathRandom": str(random.random())[:17],
                "pageSize": 99999, "pageNo": 1})
            for x in ((d.get("attribute") or {}).get("list") or []):
                mid = str(x.get("myClassId", ""))
                if mid and mid not in merged:
                    merged[mid] = x
        return list(merged.values())

    def my_class(self, my_class_id: str) -> dict:
        d = self._gson("/train/class/my-class.gson",
                       {"myClassId": my_class_id})
        return (d.get("attribute") or {}).get("data") or {}

    def checkface(self, my_class_id: str) -> dict:
        d = self._gson("/train/cms/face/check/class-checkface-config.gson",
                       {"myClassId": my_class_id})
        return (d.get("attribute") or {})
