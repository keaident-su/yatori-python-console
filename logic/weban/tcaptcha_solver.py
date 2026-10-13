# -*- coding: utf-8 -*-
"""TCaptcha 无感验证纯协议求解器（2026-09-29 攻克版）

原理（逆向结论）:
1. GET /cap_union_prehandle  -> sess / sid / pow_cfg / tdc_path
2. GET tdc.js               -> 腾讯"混沌VM"JS, 用进程内 V8(py_mini_racer) 执行
   - 补 V8 环境(ENV_JS): btoa/atob、navigator/screen/document 真值、全内建、魔法兜底
   - 假 Canvas/WebGL(FAKE_CANVAS_JS): 喂入真浏览器采集的 PNG 指纹模板与 GPU 信息
   - window.TDC.getData() -> [0] 数据段(URL编码形态)
3. POW: 找 nonce 使 md5(prefix+nonce)==pow_cfg.md5
4. POST /cap_union_new_verify (form):
   **关键**: & / = / collect= 为字面分隔符, 只有每个"值"做 URIComponent!
   collect=<enc([0])>&tlg=<900-1000>&eks=<enc>&sess=<enc>&ans=<enc>&tkid=<10位>&pow_answer=<enc>&pow_calc_time=<n>
   -> {"errorCode":"0","ticket":"tr03...","randstr":"@xx"}

实测: 2026-09-29 连续 4+ 次 errorCode=0, 全流程约 0.5-1 秒, 服务端 exam_check 返回 {"code":"0","detailCode":"0"}
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import time
from typing import Any
from urllib.parse import quote, unquote

import requests

from logic.weban.tcaptcha_env import (
    CANVAS_DATAURL,
    ENV_JS,
    FAKE_CANVAS_JS,
    WEBGL_EXTS,
    WEBGL_RENDERER,
    WEBGL_VENDOR,
)

TC = "https://turing.captcha.qcloud.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) HeadlessChrome/153.0.0.0 Safari/537.36")
APP_VERSION = ("5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) HeadlessChrome/153.0.0.0 Safari/537.36")
# 与 Canvas 模板采集时一致的 document.cookie(参与 [0] 生成; 无感判定不校验其真伪)
DEFAULT_COOKIE = ("SERVERID=960d3937b58d431003f75e175ffea128|1790615403|1790615403; "
                  "Hm_lvt_05399ccffcee10764eab39735c54698f=1790615403; "
                  "Hm_lpvt_05399ccffcee10764eab39735c54698f=1790615403")
_SAFE = "!~*'()"  # encodeURIComponent 语义(Python quote 默认 safe='/' 需替换)


def _log(log: Any, msg: str, level: str = "info") -> None:
    if log is None:
        return
    try:
        getattr(log, level, log.info)(f"TCaptcha: {msg}")
    except Exception:
        pass


def _solve_pow(prefix: str, target_md5: str, max_n: int = 5_000_000) -> int | None:
    for n in range(max_n):
        if hashlib.md5(f"{prefix}{n}".encode()).hexdigest() == target_md5:
            return n
    return None


def _solve_once(app_id: str, entry_url: str, host: str,
                cookie: str, log: Any) -> dict[str, str] | None:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": entry_url,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "sec-ch-ua": '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    })
    # 1) prehandle
    tkid = str(random.randint(1000000000, 9999999999))
    params = {
        "aid": app_id, "protocol": "https", "accver": "1",
        "showtype": "popup", "ua": base64.b64encode(UA.encode()).decode(),
        "noheader": "1", "fb": "1", "aged": "0", "enableAged": "0",
        "enableDarkMode": "0", "grayscale": "1", "clientype": "2",
        "userLanguage": "zh-cn", "lang": "zh-cn", "entry_url": entry_url,
        "elder_captcha": "0", "js": "/tgJCap.64fe1d13.js", "wb": "2",
        "tkid": tkid, "subsid": "1",
        "callback": f"_aq_{random.randint(10000, 99999)}",
    }
    r = s.get(f"{TC}/cap_union_prehandle", params=params, timeout=15)
    t = r.text
    pre = json.loads(t[t.find("(") + 1:t.rfind(")")])
    sess = pre.get("sess", "")
    cfg = (pre.get("data") or {}).get("comm_captcha_cfg") or {}
    pow_cfg = cfg.get("pow_cfg") or {}
    tdc_path = cfg.get("tdc_path", "")
    if not sess or not tdc_path:
        _log(log, "prehandle 响应缺少 sess/tdc_path", "warning")
        return None

    # 2) tdc.js -> V8 执行
    r2 = s.get(f"{TC}{tdc_path}", timeout=15)
    tdc_js = r2.text
    from py_mini_racer import MiniRacer
    ctx = MiniRacer()
    fake = (FAKE_CANVAS_JS
            .replace("__EXTS__", json.dumps(WEBGL_EXTS))
            .replace("__VENDOR__", json.dumps(WEBGL_VENDOR))
            .replace("__RENDERER__", json.dumps(WEBGL_RENDERER))
            .replace("__DATAURL__", json.dumps(CANVAS_DATAURL)))
    env = (ENV_JS
           .replace("__UA__", json.dumps(UA))
           .replace("__APPV__", json.dumps(APP_VERSION))
           .replace("__ENTRY__", json.dumps(entry_url))
           .replace("__HOST__", host)
           .replace("__COOKIE__", json.dumps(cookie))
           + "\n" + fake)
    ctx.eval(env)
    ctx.eval(tdc_js)
    seg0 = str(ctx.eval("window.TDC.getData()"))
    if seg0.startswith("Err"):
        _log(log, f"getData 失败: {seg0[:80]}", "warning")
        return None
    info = json.loads(str(ctx.eval("JSON.stringify(window.TDC.getInfo())")))
    eks = info.get("info", "")
    seg0_dec = unquote(seg0)

    # 3) POW
    nonce = _solve_pow(pow_cfg.get("prefix", ""), pow_cfg.get("md5", ""))
    if nonce is None:
        _log(log, "POW 求解失败", "warning")
        return None
    pow_answer = f"{pow_cfg.get('prefix', '')}{nonce}"
    pct = max(1, round(nonce / 100) + 1)

    # 4) 组装(关键: 字面分隔符 + 逐值 URIComponent)
    tlg = random.randint(900, 1000)
    ans = json.dumps([{"elem_id": 0, "type": "DynAnswerType_TIME", "data": ""}],
                     separators=(",", ":"))
    body = (f"collect={quote(seg0_dec, safe=_SAFE)}&tlg={tlg}"
            f"&eks={quote(eks, safe=_SAFE)}&sess={quote(sess, safe=_SAFE)}"
            f"&ans={quote(ans, safe=_SAFE)}&tkid={tkid}"
            f"&pow_answer={quote(pow_answer, safe=_SAFE)}&pow_calc_time={pct}")

    # 5) verify
    r3 = s.post(f"{TC}/cap_union_new_verify", data=body.encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                timeout=15)
    try:
        res = r3.json()
    except ValueError:
        return None
    if str(res.get("errorCode")) == "0" and res.get("ticket"):
        return {"ticket": res["ticket"], "randstr": res.get("randstr", "")}
    _log(log, f"verify 被拒: errorCode={res.get('errorCode')}", "warning")
    return None


def solve_tcaptcha_pick(app_id: str, entry_url: str, host: str,
                        log: Any = None, retry: int = 5,
                        cookie: str = DEFAULT_COOKIE) -> dict[str, str] | None:
    """纯协议求解 TCaptcha 图片点选验证（weban 课程完成场景, appId=195119536）。

    流程: prehandle(拿 sess/pow/tdc + dyn_show_info 的 img_url/sprite_url/size_2d)
          -> V8 生成 [0] -> 下载背景/提示图 -> detect_points 识别 3 点
          -> ans=[{"elem_id":i,"type":"DynAnswerType_POS","data":"x,y"}]
          -> POW -> verify -> ticket

    实测(2026-09-29): 单次成功率约 50%(识别精度), 内置重试(默认 5 次)可显著提升;
    频繁触发可能返回 errorCode=12(限流), 故每次重试间隔 0.8s。
    """
    from logic.weban.captcha import detect_points, fetch_image

    t0 = time.time()
    for attempt in range(1, retry + 1):
        if attempt > 1:
            time.sleep(0.8)
        try:
            res = _solve_pick_once(app_id, entry_url, host, cookie, log)
            if res:
                _log(log, f"点选求解成功(第{attempt}次, {time.time()-t0:.1f}s): "
                     f"randstr={res['randstr']}")
                return res
        except Exception as e:  # noqa: BLE001 -- 重试或由调用方降级
            _log(
                log, f"点选求解异常(第{attempt}次): {type(e).__name__}: {e}", "warning")
    _log(log, f"点选求解失败(共{retry}次, {time.time()-t0:.1f}s)", "warning")
    return None


def _solve_pick_once(app_id: str, entry_url: str, host: str,
                     cookie: str, log: Any) -> dict[str, str] | None:
    from logic.weban.captcha import detect_points, fetch_image

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": entry_url,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "sec-ch-ua": '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    })
    tkid = str(random.randint(1000000000, 9999999999))
    params = {
        "aid": app_id, "protocol": "https", "accver": "1",
        "showtype": "popup", "ua": base64.b64encode(UA.encode()).decode(),
        "noheader": "1", "fb": "1", "aged": "0", "enableAged": "0",
        "enableDarkMode": "0", "grayscale": "1", "clientype": "2",
        "userLanguage": "zh-cn", "lang": "zh-cn", "entry_url": entry_url,
        "elder_captcha": "0", "js": "/tgJCap.64fe1d13.js", "wb": "1",
        "tkid": tkid, "subsid": "1",
        "callback": f"_aq_{random.randint(10000, 99999)}",
    }
    r = s.get(f"{TC}/cap_union_prehandle", params=params, timeout=15)
    t = r.text
    pre = json.loads(t[t.find("(") + 1:t.rfind(")")])
    sess = pre.get("sess", "")
    cfg = (pre.get("data") or {}).get("comm_captcha_cfg") or {}
    pow_cfg = cfg.get("pow_cfg") or {}
    tdc_path = cfg.get("tdc_path", "")
    dsi = (pre.get("data") or {}).get("dyn_show_info") or {}
    bcfg = dsi.get("bg_elem_cfg") or {}
    img_url = bcfg.get("img_url", "")
    sprite_url = dsi.get("sprite_url", "")
    size_2d = bcfg.get("size_2d") or []
    if not (sess and tdc_path and img_url and sprite_url):
        _log(log, "prehandle 缺少点选字段", "warning")
        return None

    r2 = s.get(f"{TC}{tdc_path}", timeout=15)
    from py_mini_racer import MiniRacer
    ctx = MiniRacer()
    fake = (FAKE_CANVAS_JS
            .replace("__EXTS__", json.dumps(WEBGL_EXTS))
            .replace("__VENDOR__", json.dumps(WEBGL_VENDOR))
            .replace("__RENDERER__", json.dumps(WEBGL_RENDERER))
            .replace("__DATAURL__", json.dumps(CANVAS_DATAURL)))
    env = (ENV_JS
           .replace("__UA__", json.dumps(UA))
           .replace("__APPV__", json.dumps(APP_VERSION))
           .replace("__ENTRY__", json.dumps(entry_url))
           .replace("__HOST__", host)
           .replace("__COOKIE__", json.dumps(cookie))
           + "\n" + fake)
    ctx.eval(env)
    ctx.eval(r2.text)
    seg0 = str(ctx.eval("window.TDC.getData()"))
    if seg0.startswith("Err"):
        return None
    info = json.loads(str(ctx.eval("JSON.stringify(window.TDC.getInfo())")))
    eks = info.get("info", "")
    seg0_dec = unquote(seg0)

    main_img = fetch_image(f"{TC}{img_url}")
    prompt_img = fetch_image(f"{TC}{sprite_url}")
    nat_h, nat_w = main_img.shape[:2]
    ordered, _candidates = detect_points(prompt_img, main_img)
    if any(p is None for p in ordered):
        _log(log, f"点选识别不完整: {ordered}", "warning")
        return None
    tw, th = (size_2d[0], size_2d[1]) if len(size_2d) == 2 else (nat_w, nat_h)
    pts = [(int(px * tw / nat_w), int(py * th / nat_h)) for px, py in ordered]
    ans = json.dumps([{"elem_id": i + 1, "type": "DynAnswerType_POS",
                       "data": f"{x},{y}"} for i, (x, y) in enumerate(pts)],
                     separators=(",", ":"))

    nonce = _solve_pow(pow_cfg.get("prefix", ""), pow_cfg.get("md5", ""))
    if nonce is None:
        return None
    pow_answer = f"{pow_cfg.get('prefix', '')}{nonce}"
    pct = max(1, round(nonce / 100) + 1)
    tlg = random.randint(900, 1400)
    body = (f"collect={quote(seg0_dec, safe=_SAFE)}&tlg={tlg}"
            f"&eks={quote(eks, safe=_SAFE)}&sess={quote(sess, safe=_SAFE)}"
            f"&ans={quote(ans, safe=_SAFE)}&tkid={tkid}"
            f"&pow_answer={quote(pow_answer, safe=_SAFE)}&pow_calc_time={pct}")
    r3 = s.post(f"{TC}/cap_union_new_verify", data=body.encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                timeout=15)
    try:
        res = r3.json()
    except ValueError:
        return None
    if str(res.get("errorCode")) == "0" and res.get("ticket"):
        return {"ticket": res["ticket"], "randstr": res.get("randstr", "")}
    _log(log, f"点选 verify 被拒: errorCode={res.get('errorCode')}", "warning")
    return None


def solve_tcaptcha(app_id: str, entry_url: str, host: str,
                   log: Any = None, retry: int = 3,
                   cookie: str = DEFAULT_COOKIE) -> dict[str, str] | None:
    """纯协议求解 TCaptcha 无感验证。

    :param app_id: 验证码 appId（weban 考试=190330343, 课程点选=195119536）
    :param entry_url: 触发页 URL（须在腾讯域名白名单内）
    :param host: 页面域名
    :param log: 可选日志器
    :param retry: 重试次数
    :param cookie: document.cookie 值（参与 [0] 生成）
    :return: {"ticket": "tr03...", "randstr": "@xx"} 或 None
    """
    t0 = time.time()
    for attempt in range(1, retry + 1):
        try:
            res = _solve_once(app_id, entry_url, host, cookie, log)
            if res:
                _log(log, f"求解成功(第{attempt}次, {time.time()-t0:.1f}s): "
                     f"randstr={res['randstr']}")
                return res
        except Exception as e:  # noqa: BLE001 -- 求解失败由调用方决定降级
            _log(log, f"求解异常(第{attempt}次): {type(e).__name__}: {e}", "warning")
        time.sleep(0.5)
    _log(log, f"求解失败(共{retry}次, {time.time()-t0:.1f}s)", "warning")
    return None
