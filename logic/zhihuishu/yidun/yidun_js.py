# -*- coding: utf-8 -*-
"""易盾 JS 引擎封装(V8): 执行 yidun_ms.js 生成 cb/fp/check/onVerify

来源: 参考项目的 msData.js(智慧树定制版易盾 JS, 已解码为明文)
依赖: mini-racer(pip install mini-racer) — 进程内 V8, 无需外部浏览器

对外接口:
    get_img_data()                -> {cb, callback}          初始化数据
    get_fp()                      -> 指纹字符串(ydfp v1.1)
    get_check(token, distance)    -> data JSON(轨迹模式)
    get_check2(token, x, y)       -> data JSON(坐标模式)
    get_onVerify(validate, fp)    -> "CN31_xxx_v_i_1"        最终 validate
    get_uuid(n)                   -> 随机 uuid
"""
from __future__ import annotations

import json
import os
import threading

_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "yidun_ms.js")
# 2026-10-15: 打包/编译环境下 __file__ 可能是 .pyd 的临时目录; 加 exe 旁 fallback
if not os.path.isfile(_JS_PATH):
    import sys as _sys
    if getattr(_sys, "frozen", False):
        for _alt in (
                os.path.join(os.path.dirname(
                    os.path.abspath(_sys.executable)), "yidun_ms.js"),
                os.path.join(os.path.dirname(os.path.abspath(_sys.executable)), "logic", "zhihuishu", "yidun", "yidun_ms.js")):
            if os.path.isfile(_alt):
                _JS_PATH = _alt
                break

_ctx = None
_ctx_lock = threading.Lock()
_eval_lock = threading.Lock()


class YidunJSError(Exception):
    """易盾 JS 执行异常"""


def _get_ctx():
    """惰性初始化 V8 上下文(全局单例)"""
    global _ctx
    if _ctx is None:
        with _ctx_lock:
            if _ctx is None:
                from py_mini_racer import MiniRacer
                ctx = MiniRacer()
                with open(_JS_PATH, "r", encoding="utf-8") as f:
                    ctx.eval(f.read())
                _ctx = ctx
    return _ctx


def _eval(expr: str):
    """线程安全地执行 JS 表达式"""
    with _eval_lock:
        try:
            return _get_ctx().eval(expr)
        except Exception as e:
            raise YidunJSError(f"JS 执行失败: {e}") from e


def get_img_data() -> dict:
    """获取初始化数据: {cb, callback}"""
    raw = _eval("get_img_data()")
    return json.loads(raw)


def get_fp() -> str:
    """生成指纹(ydfp v1.1, 已含 :timestamp 后缀)"""
    return str(_eval("get_fp()"))


def get_cb() -> str:
    """生成单次 cb"""
    return str(_eval("get_cb()"))


def get_check(token: str, distance) -> str:
    """轨迹模式提交数据: get_check(token, ctory) -> JSON 字符串 {d, m, p, f, ext}

    注意: JS 的 get_check 返回外层 {get_ctory:{...}, cb, callback},
    实际 HTTP 提交的 data 参数只需内层 {d,m,p,f,ext}(2026-09-28 抓包确认),
    此处直接返回内层结构。
    :param token: v3/get 返回的 token
    :param distance: 滑动距离(像素, 会被 JS 内部 getTrack 用于生成轨迹)
    """
    raw = str(_eval(
        f"get_check({json.dumps(str(token))}, {json.dumps(str(distance))})"))
    d = json.loads(raw)
    inner = d.get("get_ctory")
    if isinstance(inner, str):
        inner = json.loads(inner)
    return json.dumps(inner, separators=(",", ":"))


def get_check2(token: str, x, y) -> str:
    """坐标模式提交数据: get_check2(token, x, y) -> JSON 字符串 {d, m, p, ext}

    (同样只返回内层结构)
    """
    raw = str(_eval(
        f"get_check2({json.dumps(str(token))}, {json.dumps(x)}, {json.dumps(y)})"))
    d = json.loads(raw)
    inner = d.get("get_ctory")
    if isinstance(inner, str):
        inner = json.loads(inner)
    return json.dumps(inner, separators=(",", ":"))


def get_onVerify(validate: str, fp: str) -> str:
    """生成最终验证令牌: "CN31_" + AES(validate::fp) + "_v_i_1" """
    return str(_eval(
        f"get_onVerify({json.dumps(str(validate))}, {json.dumps(str(fp))})"))


def get_uuid(n: int = 36) -> str:
    """生成随机 uuid"""
    return str(_eval(f"get_uuid({int(n)})"))
