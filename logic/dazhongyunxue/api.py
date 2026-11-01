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


def normalize_base_url(u) -> str:
    """[V3.2.1] 地址归一化: 无协议自动补 https://，去掉路径/查询，只保留 scheme://host[:port]。

    背景: 旧实现(if u.startswith("http"))会把用户填写的无协议域名
    (如 xjbt.zyk.yxlearning.com) 静默丢弃并回退到内置默认 gxk 站，
    导致登录/课程全部对不上(用户反馈"启动不了、课程在学习中心却刷不到")。
    """
    from urllib.parse import urlsplit
    s = str(u or "").strip()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s.lstrip("/")
    try:
        sp = urlsplit(s)
        if not sp.netloc:
            return ""
        return "%s://%s" % (sp.scheme or "https", sp.netloc)
    except Exception:
        return ""


_BASE_PROBE_CACHE: Dict[str, str] = {}


def _reachable(base: str, timeout: int = 6) -> bool:
    """快速探测站点是否可达(仅用于协议 http/https 二选一)"""
    try:
        r = requests.get(base + "/login", timeout=timeout,
                         allow_redirects=True, headers={"User-Agent": _UA})
        return int(r.status_code) < 500
    except Exception:
        return False


def probe_base(u) -> str:
    """[V3.2.1] 归一化 + 协议自适应: https 不通则尝试 http(反之亦然)。
    结果缓存，避免每次登录重复探测; 两者都不通时返回归一化结果(由登录环节报明确错误)。"""
    base = normalize_base_url(u)
    if not base:
        return ""
    if base in _BASE_PROBE_CACHE:
        return _BASE_PROBE_CACHE[base]
    chosen = base
    if not _reachable(base):
        alt = (base.replace("https://", "http://", 1)
               if base.startswith("https://")
               else base.replace("http://", "https://", 1))
        if _reachable(alt):
            chosen = alt
    _BASE_PROBE_CACHE[base] = chosen
    return chosen


def resolve_base(setting=None, user=None) -> str:
    """基地址解析(2026-10-24, 对齐英华URL平台模式):
    账号级 url 优先(每账号可填自己的平台地址) → 全局 dzyx_base_url → 内置默认

    [V3.2.1] 账号/全局地址均走 probe_base: 支持无协议域名(自动补并探测 http/https)。
    """
    # ① 账号级 URL(与英华学堂等URL平台同语义)
    try:
        u = probe_base(getattr(user, "url", "") or "")
        if u:
            return u
    except Exception:
        pass
    # ② 全局基地址
    try:
        u = probe_base(getattr(getattr(setting, "basic_setting", None),
                               "dzyx_base_url", "") or "")
        if u:
            return u
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
            d = json.load(f)
        # [V3.2.3] 类型安全: 非 dict(含 None/损坏) 一律视为无登录态
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def save_state(account: str, state: dict) -> None:
    # [V3.2.3] 类型安全: 只落盘有效 dict, 防止 None 写入后续被当状态使用
    if not isinstance(state, dict) or not state:
        return
    p = state_path(account)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, p)


def cookies_from_state(state: dict) -> Dict[str, str]:
    # [V3.2.3] 防御: state/cookies 结构异常时不抛错
    if not isinstance(state, dict):
        return {}
    out: Dict[str, str] = {}
    for c in (state.get("cookies") or []):
        if isinstance(c, dict) and c.get("name"):
            out[str(c["name"])] = str(c.get("value", ""))
    return out


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
