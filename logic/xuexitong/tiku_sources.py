# -*- coding: utf-8 -*-
"""外部题库聚合源 - 全部协议还原自逆向 xxt eaxam 的 tiku()
来源: xxt eaxam/analysis/function_evidence/APPGUI.functions.txt (逐家字节码还原)
统一返回值: 命中返回原始答案字符串(由上层按题型归一化), 未命中 None。
默认 token 来自逆向 load_config(SpaceX/Super), 可被配置覆盖。
"""
import json
import re
import time
import html as _html
import requests

DEFAULT_TOKENS = {
    "SpaceX": "c5ecf55ebeb4b61d669713b54693ce09",   # doc.spacex-api.com
    "Super": "pEnkGq0muO4X9LPY",                    # tk.xxtmooc.com
    "MAX": "", "Wk": "", "AXE": "", "yizhi": "", "dxstj": "",
}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0")
_SUBJECTIVE = {"2", "3", "6", "5", "4", "10", "7", "8", "9"}

_COOLDOWN = {}         # name -> cooldown_until
_FAIL_COOLDOWN = 300   # 失败冷却秒数


def _opts(options, qtype):
    if str(qtype) == "3":
        return ["对", "错"]
    out = []
    for o in (options or []):
        s = str(o).strip()
        if len(s) >= 2 and s[0].upper() in "ABCDEFGHIJKLMN" and s[1] in ".、,， 　":
            s = s[2:].strip()
        out.append(s)
    return out


def _strip_html(t):
    try:
        return _html.unescape(re.sub(r"<[^>]*>", "", str(t or ""))).strip()
    except Exception:
        return str(t or "").strip()


def _post_json(url, body, headers=None, params=None, timeout=12):
    h = {"User-Agent": _UA, "Content-Type": "application/json;charset=utf-8",
         "Accept-Encoding": "gzip, deflate"}
    if headers:
        h.update(headers)
    return requests.post(url, params=params, data=json.dumps(body, ensure_ascii=False),
                         headers=h, timeout=timeout, verify=False)


# ---------------- 各家实现 ----------------
def q_spacex(timu, options, qtype, token, timeout=12):
    if not token:
        return None
    o = _opts(options, qtype)
    p = {"token": token, "question": timu, "options": str(o).replace('"', "'")}
    r = requests.get("https://doc.spacex-api.com/Api/tiku", params=p,
                     headers={"User-Agent": "python-requests/2.x",
                              "Accept": "application/json"},
                     timeout=timeout)
    d = r.json()
    return str(d.get("answer")) if d.get("code") == 1 and d.get("answer") else None


def q_super(timu, options, qtype, token, timeout=12):  # = xxtmooc
    if not token:
        return None
    body = {"question": timu, "options": _opts(
        options, qtype), "token": token, "type": int(qtype or 0)}
    d = _post_json("https://tk.xxtmooc.com/api/q/v1", body).json()
    return str(d.get("data")) if d.get("code") == 200 and d.get("data") else None


def q_ake(timu, options, qtype, token, timeout=12):  # = 万卷/wanjuantiku (AXE)
    if not token:
        return None
    p = {"token": token, "version": "", "ran": ""}
    body = {"tm": timu, "type": str(qtype or 0), "wid": "", "answernum": "",
            "cid": "", "options": json.dumps(_opts(options, qtype), ensure_ascii=False)}
    d = _post_json("https://tk.wanjuantiku.com/api/query",
                   body, params=p).json()
    return str(d.get("data")) if d.get("code") == 1 and d.get("data") else None


def q_max(timu, options, qtype, token, timeout=12):
    if not token:
        return None
    p = {"key": token, "question": timu}
    d = requests.get("https://max.tlicf.com/Interface/xxt/", params=p,
                     headers={"User-Agent": _UA}, timeout=timeout, verify=False).json()
    return str(d.get("data")) if d.get("code") == 1 and d.get("data") else None


def q_wk(timu, options, qtype, token, timeout=12):  # swk.tw, key=Wk_token
    if not token:
        return None
    body = {"key": token, "question": timu, "options": _opts(
        options, qtype), "type": str(qtype or 0)}
    d = _post_json("http://tk.swk.tw/api/search.php", body).json()
    raw = d.get("data")
    return _strip_html(raw) if raw else None


def q_yizhi(timu, options, qtype, token, timeout=12):  # icodef, Authorization=yizhi_token
    if not token:
        return None
    d = _post_json("http://cx.icodef.com/wyn-nb", {"question": timu},
                   headers={"Authorization": token}, params={"v": "4"}).json()
    return str(d.get("data")) if d.get("code") == 1 and d.get("data") else None


def q_soso(timu, options, qtype, token=None, timeout=12):  # kvai
    url = "http://ti.kvai.cn/api/?question=" + str(timu)
    d = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout).json()
    return str(d.get("data")) if d.get("code") == 1 and d.get("data") else None


def q_muketool(timu, options, qtype, token=None, timeout=12):
    d = _post_json("https://api.muketool.com/cx/v2/query",
                   {"question": timu}).json()
    return str(d.get("data")) if d.get("code") == 1 and d.get("data") else None


def q_ze(timu, options, qtype, token=None, timeout=12):  # zaizhexue
    p = {"query": timu, "type": "题目", "page": "1",
         "pageSize": "8", "sort": "newest"}
    d = requests.get("https://webapi.zaizhexue.top/search", params=p,
                     headers={"User-Agent": _UA}, timeout=timeout, verify=False).json()
    if d.get("success") is True:
        ans = (d.get("data") or {}).get("answer")
        return _strip_html(ans) if ans else None
    return None


def q_lemon(timu, options, qtype, token=None, timeout=12):  # lemtk
    url = ("https://api.lemtk.xyz/api/v1/cx?question=" + str(timu)
           + "&type=" + str(qtype or 0)
           + "&options=" + str(_opts(options, qtype)))
    d = requests.request("GET", url, headers={"Content-Type": "application/json"},
                         timeout=timeout, verify=False).json()
    if d.get("code") == 1000:
        ans = (d.get("data") or {}).get("answer")
        return str(ans) if ans else None
    return None


def q_wanneng(timu, options, qtype, token=None, timeout=12):  # wkexam, token=qqqqq
    url = "http://api.wkexam.com/api/?token=qqqqq&q=" + str(timu)
    r = requests.get(url, timeout=timeout, verify=False)
    try:
        d = json.loads(r.text)
    except Exception:
        return None
    if d.get("code") == 1:
        ans = (d.get("data") or {}).get("answer")
        return str(ans) if ans else None
    return None


def q_dxstj(timu, options, qtype, token=None, timeout=15):  # 大学生搜题酱(需 Cookie=dxstj_Cookie)
    if not token:
        return None
    import time as _t
    payload = {
        "appId": "collegepcpi", "vcname": "1.5.4", "os": "Windows", "image": "",
        "picMD5": "", "historyResult": "", "questionText": timu,
        "options": _opts(options, qtype), "questionType": str(qtype or 0),
        "questionFrom": "cxExam", "llmType": "", "exciseUrl": "https://mooc1.chaoxing.com/",
        "chapterName": "", "courseName": "", "ceYanName": "", "questionTextHtml": "", "vc": "154",
    }
    headers = {"User-Agent": _UA, "Content-Type": "application/json", "ua": "collegepcpi/1.5.4",
               "origin": "chrome-extension://egfkhocobmgeafdbjbphhfdfbmlobgdc",
               "Accept-Language": "zh-CN,zh;q=0.9", "Cookie": token}
    r = requests.post("https://www.daxuesoutijiang.com/dxai/submit/exercise/solve",
                      data=payload, headers=headers, timeout=timeout)
    d = r.json()
    if d.get("errNo") == 0 and "data" in d:
        try:
            hr = json.loads((d.get("data") or {}).get("historyResult") or "[]")
            for item in hr:
                a = item.get("answer") or item.get(
                    "answere") or item.get("content")
                if a:
                    return str(a)
        except Exception:
            pass
    return None


# 名称, token键, url, 实现, token获取页(占位, 后续填充)
SOURCES = [
    ("SpaceX",    "SpaceX", "https://doc.spacex-api.com/Api/tiku",
     q_spacex, "https://doc.spacex-api.com"),
    ("Super",     "Super",  "https://tk.xxtmooc.com/api/q/v1",
     q_super,  "https://tk.xxtmooc.com"),
    ("AKE",       "AXE",    "https://tk.wanjuantiku.com/api/query",
     q_ake,    "https://tk.wanjuantiku.com"),
    ("MAX",       "MAX",    "https://max.tlicf.com/Interface/xxt/",
     q_max,    "https://max.tlicf.com"),
    ("Wk",        "Wk",     "http://tk.swk.tw/api/search.php",
     q_wk,     "http://tk.swk.tw"),
    ("yizhi",     "yizhi",  "http://cx.icodef.com/wyn-nb",
     q_yizhi,  "http://cx.icodef.com"),
    ("Soso",      None,     "http://ti.kvai.cn/api/?question=",
     q_soso,   "http://ti.kvai.cn"),
    ("Muketool",  None,     "https://api.muketool.com/cx/v2/query",
     q_muketool, "https://api.muketool.com"),
    ("ze",        None,     "https://webapi.zaizhexue.top/search",
     q_ze,     "https://webapi.zaizhexue.top"),
    ("lemon",     None,     "https://api.lemtk.xyz/api/v1/cx",
     q_lemon,  "https://api.lemtk.xyz"),
    ("wanneng",   None,     "http://api.wkexam.com/api/",
     q_wanneng, "http://api.wkexam.com"),
    ("dxstj",     "dxstj",  "https://www.daxuesoutijiang.com/dxai/submit/exercise/solve",
     q_dxstj, "https://www.daxuesoutijiang.com"),
]


def query_external_tiku(question, options, qtype, tokens=None, order=None, log_fn=None):
    """聚合查询: 按顺序尝试, 命中返回 (name, answer_str), 否则 (None, None)
    带失败冷却: 抛异常的源(宕机/非JSON/404)冷却 300s, 避免拖慢每题。"""
    toks = dict(DEFAULT_TOKENS, **(tokens or {}))
    now = time.time()
    for name, tkey, url, impl, getpage in SOURCES:
        if order and name not in order:
            continue
        if _COOLDOWN.get(name, 0) > now:
            continue
        if tkey and not toks.get(tkey):
            continue  # 需要 token 但没配, 跳过
        try:
            ans = impl(question, options, qtype, toks.get(tkey or "", ""))
        except Exception:
            _COOLDOWN[name] = now + _FAIL_COOLDOWN
            ans = None
        if ans:
            _a = str(ans).strip()
            # 判断题(3)只接受真/假语义, 否则视为未命中(防垃圾答案如'日全食')
            if str(qtype) == "3":
                _tf = ("对", "错", "正确", "错误", "√", "×",
                       "true", "false", "True", "False", "是", "否")
                if not any(k in _a or _a in k for k in _tf):
                    continue
            if log_fn:
                log_fn("[题库-" + name + "] 命中: " + _a[:60])
            return name, ans
    return None, None


# ---- 供答题引擎接入(运行时token + 总开关 + 可用性) ----
_RUNTIME_TOKENS = {}
ENABLED = True


def set_runtime_tokens(d):
    global _RUNTIME_TOKENS
    if isinstance(d, dict):
        _RUNTIME_TOKENS = {k: str(v) for k, v in d.items() if v}


def available():
    """是否有可用源(免token的 kvai/zaizhexue 等默认可用)"""
    if not ENABLED:
        return False
    now = time.time()
    for name, tkey, url, impl, getpage in SOURCES:
        if _COOLDOWN.get(name, 0) > now:
            continue
        if not tkey or _RUNTIME_TOKENS.get(tkey) or DEFAULT_TOKENS.get(tkey):
            return True
    return False


def query_for_engine(question, options, qtype):
    """答题引擎入口 -> (name, answer) 或 (None, None)"""
    if not ENABLED or not question:
        return None, None
    return query_external_tiku(question, options, qtype,
                               tokens=_RUNTIME_TOKENS)


def token_get_pages():
    """各题库 token 获取页(用于前端配置展示/引导)"""
    return {name: getpage for name, tkey, url, impl, getpage in SOURCES}
