# -*- coding: utf-8 -*-
"""易盾滑块完整求解器(纯协议, 无浏览器)

流程(2026-09-28 实测抓包验证, 智慧树场景):
  ① getconf      → dt + ir.token(上报用)
  ② ir-sdk/up    → irToken(信息上报, 失败可降级省略)
  ③ v3/get       → token + bg[]背景图 + front[]拼图
  ④ ddddocr 识别缺口 → 距离
  ⑤ get_check(token, distance) → data(轨迹+加密)
  ⑥ v3/check     → validate
  ⑦ get_onVerify(validate, fp) → "CN31_xxx_v_i_1"

输出: CN31_ 前缀的 validate 令牌, 供智慧树登录接口使用。
"""
from __future__ import annotations

import json
import random
import time
from urllib.parse import quote, urlencode

from logic.zhihuishu.yidun import yidun_js

# ---------- 智慧树易盾配置(2026-09-28 抓包确认) ----------
APP_ID = "75f9f716460a422f89a628f50fd8cc2b"   # captchaId(id 参数)
ZONE_ID = "CN31"                               # 与 JS 内 ns="CN31" 一致
REFERER = "https://login.zhihuishu.com/"
GETCONF_URL = "https://c.dun.163.com/api/v2/getconf"
GET_URL = "https://c.dun.163.com/api/v3/get"
CHECK_URL = "https://c.dun.163.com/api/v3/check"
IR_UP_URL = "https://ir-sdk.dun.163.com/v4/j/up"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class YidunSolveError(Exception):
    """易盾求解失败"""


class YidunSolver:
    """易盾滑块求解器(单实例可复用, 内部 JS 上下文有锁保护)"""

    def __init__(self, session, log=None):
        """
        :param session: requests.Session(用于访问 dun.163.com)
        :param log: 可选日志函数 log(msg, err=False)
        """
        self._s = session
        self._log = log or (lambda m, err=False: None)

    def _info(self, msg):
        self._log(msg, False)

    def _warn(self, msg):
        self._log(msg, True)

    # ---------- JSONP 响应解析 ----------
    @staticmethod
    def _parse_jsonp(text: str) -> dict:
        """解析 __JSONP_xxx({...}); 响应"""
        t = (text or "").strip()
        i, j = t.find("("), t.rfind(")")
        if i < 0 or j < 0:
            raise YidunSolveError(f"响应格式异常: {t[:120]}")
        return json.loads(t[i + 1:j])

    # ---------- ① getconf ----------
    def _getconf(self) -> dict:
        cb = yidun_js.get_img_data()["callback"]
        params = {
            "referer": REFERER,
            "zoneId": "",
            "dt": "",
            "id": APP_ID,
            "ipv6": "false",
            "runEnv": "10",
            "iv": "5",
            "loadVersion": "2.5.4",
            "lang": "zh-CN",
            "callback": cb,
        }
        r = self._s.get(GETCONF_URL, params=params, timeout=15,
                        headers={"User-Agent": _UA, "Referer": REFERER})
        data = self._parse_jsonp(r.text)
        if data.get("error") not in (0, None):
            raise YidunSolveError(f"getconf 失败: {data}")
        return data.get("data") or {}

    # ---------- ② ir 上报(可选) ----------
    def _ir_up(self, ir_pn: str) -> str | None:
        """信息上报, 返回 irToken(失败返回 None, 可降级省略)"""
        try:
            # 用 combined.js 的 build_request_body 结构(h5 模式)
            body = {
                "p": ir_pn,
                "v": "2.0.13_yanzhengma",
                "vk": "d44593ca",
                "n": yidun_js.get_uuid(32).replace("-", "")[:32],
                "d": yidun_js.get_cb(),
            }
            r = self._s.post(IR_UP_URL, json=body, timeout=10,
                             headers={"User-Agent": _UA, "Referer": REFERER})
            data = r.json()
            return data.get("irToken") or (data.get("data") or {}).get("irToken")
        except Exception as e:
            self._warn(f"ir 上报失败(可降级): {e}")
            return None

    # ---------- ③ v3/get ----------
    def _get(self, dt: str, ir_token: str | None) -> dict:
        img = yidun_js.get_img_data()
        fp = yidun_js.get_fp()
        params = {
            "referer": REFERER,
            "zoneId": ZONE_ID,
            "dt": dt,
            "id": APP_ID,
            "fp": fp,
            "https": "true",
            "version": "2.28.5",
            "dpr": "1",
            "dev": "3",
            "cb": img["cb"],
            "ipv6": "false",
            "runEnv": "10",
            "lang": "zh-CN",
            "loadVersion": "2.5.4",
            "iv": "4",
            "width": "400",
            "audio": "false",
            "sizeType": "10",
            "smsVersion": "v3",
            "callback": img["callback"],
        }
        if ir_token:
            params["irToken"] = ir_token
        r = self._s.get(GET_URL, params=params, timeout=15,
                        headers={"User-Agent": _UA, "Referer": REFERER})
        data = self._parse_jsonp(r.text)
        if data.get("error") not in (0, None):
            raise YidunSolveError(f"v3/get 失败: {data}")
        return data.get("data") or {}

    # ---------- ④ 缺口识别(Autovisor 算法, 9/25 实测成功) ----------
    @staticmethod
    def _detect_gap(bg_bytes: bytes, front_bytes: bytes) -> int | None:
        """识别缺口左边缘 x(原图坐标) - Autovisor 算法

        背景: 降噪+OTSU二值化+Canny(500,900)
        拼图: 反色+二值化+Canny(500,900)
        注: ddddocr 对易盾 2.28.5 偏约 44px, 已弃用(2026-09-29 目视验证)
        """
        try:
            import cv2
            import numpy as np
            bg = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8),
                              cv2.IMREAD_COLOR)
            jig = cv2.imdecode(np.frombuffer(front_bytes, np.uint8),
                               cv2.IMREAD_UNCHANGED)
            if bg is None or jig is None:
                return None
            bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
            bg_dn = cv2.fastNlMeansDenoising(bg_gray, None, 10, 7, 21)
            _, bg_bin = cv2.threshold(bg_dn, 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            bg_edge = cv2.Canny(bg_bin, 500, 900, apertureSize=3)
            if jig.ndim == 3 and jig.shape[2] == 4:
                jg = cv2.cvtColor(jig, cv2.COLOR_BGRA2GRAY)
            else:
                jg = cv2.cvtColor(jig, cv2.COLOR_BGR2GRAY)
            ji = cv2.bitwise_not(jg)
            _, jb = cv2.threshold(ji, 240, 255, cv2.THRESH_BINARY_INV)
            je = cv2.Canny(jb, 500, 900, apertureSize=3)
            res = cv2.matchTemplate(bg_edge, je, cv2.TM_CCOEFF_NORMED)
            _, _, _, ml = cv2.minMaxLoc(res)
            return int(ml[0])
        except Exception:
            return None

    # ---------- ⑤⑥⑦ 完整求解 ----------
    def solve(self) -> str | None:
        """完整求解一次, 返回 validate(CN31_ 前缀) 或 None"""
        try:
            # ① getconf
            conf = self._getconf()
            dt = conf.get("dt") or ""
            self._info(
                f"getconf OK: dt={dt[:12]}.. zoneId={conf.get('zoneId')}")

            # ② ir 上报(可选)
            ir_pn = ((conf.get("ir") or {}).get("pn")) or ""
            ir_token = self._ir_up(ir_pn) if ir_pn else None

            # ③ v3/get
            data = self._get(dt, ir_token)
            token = data.get("token") or ""
            bg_url = (data.get("bg") or [""])[0]
            front_url = (data.get("front") or [""])[0]
            if not (token and bg_url and front_url):
                raise YidunSolveError(f"v3/get 数据不完整: {list(data.keys())}")
            self._info(f"v3/get OK: token={token[:10]}..")

            # ④ 下载图片 + 识别(Autovisor 算法, 原图 480 坐标)
            bg = self._s.get(bg_url, timeout=15).content
            front = self._s.get(front_url, timeout=15).content
            raw_dist = self._detect_gap(bg, front)
            if raw_dist is None:
                raise YidunSolveError("缺口识别失败")
            # ctory 语义: 易盾内部 320 坐标系 = raw(480) × 320/480 = raw × 2/3
            # (2026-09-28 扫描实测: ctory=round(raw*2/3) 一次命中 result=True,
            #  与 JS 内 parseInt(ctory)/320*100 百分比逻辑自洽)
            dist = round(raw_dist * 2 / 3)
            self._info(f"缺口识别: 原图{raw_dist}px -> ctory={dist} (320坐标系)")

            # ⑤ get_check(轨迹模式, 传入 ctory(320坐标系距离))
            check_data = yidun_js.get_check(token, dist)

            # ⑥ v3/check(GET)
            img = yidun_js.get_img_data()
            params = {
                "referer": REFERER,
                "zoneId": ZONE_ID,
                "dt": dt,
                "id": APP_ID,
                "token": token,
                "data": check_data,
                "width": "400",
                "type": "2",
                "version": "2.28.5",
                "cb": img["cb"],
                "bf": "0",
                "runEnv": "10",
                "loadVersion": "2.5.4",
                "iv": "4",
                "callback": img["callback"],
            }
            r = self._s.get(CHECK_URL, params=params, timeout=15,
                            headers={"User-Agent": _UA, "Referer": REFERER})
            res = self._parse_jsonp(r.text)
            if res.get("error") not in (0, None):
                self._warn(f"v3/check 返回: error={res.get('error')} "
                           f"msg={res.get('msg')}")
                return None
            validate = res.get("validate") or (
                res.get("data") or {}).get("validate")
            if not validate:
                self._warn(f"v3/check 无 validate: {str(res)[:150]}")
                return None
            self._info("v3/check 通过, 获得 validate")

            # ⑦ 生成 CN31_ 令牌
            fp = yidun_js.get_fp()
            on_verify = yidun_js.get_onVerify(validate, fp)
            self._info(f"CN31 令牌已生成: {on_verify[:30]}...")
            return on_verify
        except YidunSolveError as e:
            self._warn(f"求解失败: {e}")
            return None
        except Exception as e:
            self._warn(f"求解异常: {type(e).__name__}: {e}")
            return None
