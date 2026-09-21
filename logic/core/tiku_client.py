# -*- coding: utf-8 -*-
"""
第三方题库客户端 - 言溪题库(emmcy) / AVXE题库(axe) / N1题库 / ZE题库 / EveryAPI题库
接口规范来源: 项目根目录参考材料(SDK目录)

言溪题库(默认 https://tk.enncy.cn):
  查题: GET  /query?token=xxx&title=题目&options=选项1(\n分隔)&type=single
  自检: GET  /info?token=xxx           -> data.times 为剩余次数, code==1 有效
AVXE题库(默认 https://tk.wanjuantiku.com, 旧域名tk.tk.icu已停用):
  查题: POST /api/query?v=2  (form)   token/tm/type/options(JSON数组串)/answernum/questionnum/ai
        返回 {code:1, data:{questions:[{tm, answer, percent}], lefts}}
  自检: POST /api/checkLeft?token=xxx  返回 {code:1, data:剩余次数}
  注册: PUT  /api/register {token, md5}  (自检失败时自动尝试一次)
N1题库(默认 http://tk.n1t.cn, 无言题库/网课搜题助手):
  查题: POST /api/search.php (form)   question/key/type(中文)/options(JSON数组串)
        命中 {code:1, data:"答案"}; 未命中 {code:-1, data:[{question,answer}], quota_info:{...}}
  自检: 用不存在短题探测(不消耗配额), 返回 quota_info.remaining 即token有效
ZE题库(默认 https://api.zaizhexue.top, ZError):
  查题: GET/POST /api/query   token/title/options(\n分隔)/type(single|multiple|judgement|completion)
        返回 {data:{code:1, data:"答案(多个用#分隔)", msg:...}, success:true}
  自检: 短题探测, data.code in (0,1) 且非token错误即有效
EveryAPI题库(默认 https://q.icodef.com, 搜题型; 旧域名go.every-api.com已停用):
  查题: GET /api/v1/q/{question}?token=KEY
        首选 simple=true&split=# -> {code:0, data:"答案1#答案2", question, msg}
        结构化 -> {code:0, data:{correct:[{option,content}], question, type}, msg}
        未命中 -> HTTP 400 + {code:-1, msg:"没有找到相关问题"}
  自检: GET /api/v1/q/hello?token=KEY, 返回含 code 即服务可达
  注意: 服务端有限流("2并发限制,您的速度太快了"), 客户端已做全局串行+最小间隔节流
"""
import hashlib
import json
import re
import threading
import time
from typing import List, Optional, Tuple
from urllib.parse import quote as _url_quote

import httpx

from utils.log import log_print, INFO, DarkGray

_DEFAULT_TIMEOUT = 10
_DEFAULT_RETRY = 2
_CHECK_RETRY = 0
_AI_TIMEOUT = 60  # AI型题库(生成较慢)超时

# AXE题库默认(新)接口地址; 以下旧地址会自动纠正到新域名
AXE_DEFAULT_BASE = "https://tk.wanjuantiku.com"
_AXE_LEGACY_MARKERS = ("apifox.cn", "tk.tk.icu",
                       "doc.v2.tk.icu", "apifoxmock.com")

# N1 / ZE / EveryAPI 默认接口地址
N1_DEFAULT_BASE = "http://tk.n1t.cn"
ZE_DEFAULT_BASE = "https://api.zaizhexue.top"
# EveryAPI新域名(旧域名go.every-api.com已停用, 自动纠正)
EVERY_DEFAULT_BASE = "https://q.icodef.com"
_EVERY_LEGACY_MARKERS = ("go.every-api.com", "every-api.com",
                         "apifoxmock.com", "every-api.apifox.cn")
# 服务端限流("2并发限制,您的速度太快了"实为滚动窗口限流), 全局串行+最小间隔节流
_EVERY_MIN_INTERVAL = 0.6  # 秒(实测间隔≥0.6s可稳定不触发限流)
_EVERY_LOCK = threading.Lock()
_EVERY_LAST_TS = [0.0]


def _normalize_every_base(url: str) -> str:
    """EveryAPI接口地址归一化: 旧域名(go.every-api.com等)自动纠正为新域名"""
    u = (url or "").strip().rstrip("/")
    if not u:
        return EVERY_DEFAULT_BASE
    low = u.lower()
    for legacy in _EVERY_LEGACY_MARKERS:
        if legacy in low:
            return EVERY_DEFAULT_BASE
    return u


def _normalize_axe_base(url: str) -> str:
    """AXE接口地址归一化: 旧域名/文档站地址自动纠正为官方新域名"""
    u = (url or "").strip().rstrip("/")
    if not u:
        return AXE_DEFAULT_BASE
    low = u.lower()
    for legacy in _AXE_LEGACY_MARKERS:
        if legacy in low:
            return AXE_DEFAULT_BASE
    return u


def _is_html_body(text: str) -> bool:
    """判断响应是否为网页(常见于URL填成文档站/后台页面)"""
    head = (text or "").lstrip()[:100].lower()
    return head.startswith("<!") or head.startswith("<html")


def _do_request(method: str, url: str, *, params: Optional[dict] = None,
                form_body: Optional[dict] = None,
                json_body: Optional[dict] = None,
                headers: Optional[dict] = None,
                timeout: int = _DEFAULT_TIMEOUT,
                retry: int = _DEFAULT_RETRY,
                ok_status: Tuple[int, ...] = (200,)) -> Tuple[str, str]:
    """通用请求: ok_status内且非HTML视为成功, 返回 (body, err)

    注: 部分接口用400携带正常业务JSON(如EveryAPI未命中 code:-1),
        此类接口传入 ok_status=(200,400) 使业务体可被解析
    """
    last_err = ""
    for _ in range(retry + 1):
        try:
            resp = httpx.request(
                method, url, params=params, data=form_body, json=json_body,
                headers=headers or {"User-Agent": "Mozilla/5.0"},
                timeout=timeout, verify=False)
            if resp.status_code in ok_status:
                if _is_html_body(resp.text):
                    return "", "接口地址无效(返回网页内容, 请检查URL配置)"
                return resp.text, ""
            last_err = f"HTTP {resp.status_code}: {(resp.text or '')[:100]}"
        except Exception as e:
            last_err = f"网络错误: {e}"
    return "", last_err


# 内部题型键 -> 言溪type
_EMMCY_TYPE_MAP = {
    "single_choice": "single",
    "choice": "single",
    "multiple_choice": "multiple",
    "judge": "judgement",
    "fill": "completion",
}

# 内部题型键 -> AVXE type（对齐参考配置: 0单选题、1多选题、3判断题、2填空题）
_AXE_TYPE_MAP = {
    "single_choice": 0,
    "choice": 0,
    "multiple_choice": 1,
    "fill": 2,
    "judge": 3,
}

# 内部题型键 -> N1中文type
_N1_TYPE_MAP = {
    "single_choice": "单选题",
    "choice": "单选题",
    "multiple_choice": "多选题",
    "judge": "判断题",
    "fill": "填空题",
    "short": "简答题",
    "term_explanation": "简答题",
    "essay": "简答题",
    "matching": "连线题",
}

# 内部题型键 -> ZE type(英文, 同言溪风格)
_ZE_TYPE_MAP = {
    "single_choice": "single",
    "choice": "single",
    "multiple_choice": "multiple",
    "judge": "judgement",
    "fill": "completion",
}


def _strip_option_prefix(opt: str) -> str:
    """去除选项字母前缀(如 "A.xxx" -> "xxx")"""
    opt = (opt or "").strip()
    m = re.match(r'^[A-Za-zＡ-Ｚ][\.、．:：\s]*', opt)
    return opt[m.end():].strip() if m else opt


def _plain_options(options: Optional[List[str]]) -> List[str]:
    """选项统一为纯文本列表(去字母前缀/去空白)"""
    result = []
    for opt in options or []:
        text = _strip_option_prefix(str(opt))
        if text:
            result.append(text)
    return result


def _json_path_get(data, path: str):
    """极简JSONPath提取, 支持 $.data.answer 与 $.data.questions[0].answer 形式"""
    if not path:
        return None
    # 将 [0] 形式归一为 .0
    path = re.sub(r"\[(\d+)\]", r".\1", path)
    keys = [k for k in path.strip().lstrip("$").strip(".").split(".") if k]
    cur = data
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and k.isdigit():
            idx = int(k)
            cur = cur[idx] if 0 <= idx < len(cur) else None
        else:
            return None
    return cur


def _answer_to_str(ans) -> str:
    """答案统一转字符串(列表用逗号连接)"""
    if ans is None:
        return ""
    if isinstance(ans, str):
        return ans.strip()
    if isinstance(ans, (int, float)):
        return str(ans)
    if isinstance(ans, list):
        parts = [_answer_to_str(p) for p in ans]
        return ",".join([p for p in parts if p])
    if isinstance(ans, dict):
        for k in ("answer", "value", "text", "content"):
            if k in ans:
                return _answer_to_str(ans[k])
    return ""


class _TikuClientBase:
    """题库客户端基类"""

    type_name = "题库"

    def __init__(self, base_url: str, token: str, timeout: int = _DEFAULT_TIMEOUT):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()
        self.timeout = timeout
        self.last_error = ""  # 最近一次请求的网络级错误(供调用方判定失败)

    def _req(self, method: str, url: str, **kw) -> Tuple[str, str]:
        """携带 last_error 的通用请求"""
        kw.setdefault("timeout", self.timeout)
        body, err = _do_request(method, url, **kw)
        self.last_error = err
        return body, err

    def check(self) -> Tuple[bool, str]:
        """token有效性自检 -> (是否可用, 详情)"""
        raise NotImplementedError

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "") -> str:
        """查询题目答案, 查不到返回空串"""
        raise NotImplementedError


class EmmcyTikuClient(_TikuClientBase):
    """言溪题库客户端"""

    type_name = "言溪题库"

    def __init__(self, base_url: str = "", token: str = "",
                 timeout: int = _DEFAULT_TIMEOUT):
        super().__init__(base_url or "https://tk.enncy.cn", token, timeout)

    def check(self) -> Tuple[bool, str]:
        if not self.token:
            return False, "未填写token"
        body, err = self._request("GET", f"{self.base_url}/info",
                                  params={"token": self.token},
                                  retry=_CHECK_RETRY)
        if err:
            return False, err
        data = None
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return False, f"响应格式异常: {(body or '')[:100]}"
        if not isinstance(data, dict):
            return False, "响应格式异常"
        if data.get("code") == 1:
            d = data.get("data") or {}
            times = d.get("times", "未知")
            success = d.get("success_times", "未知")
            return True, f"可用, 剩余次数: {times}, 累计成功: {success}"
        msg = data.get("message") or data.get("msg") or "token无效或已过期"
        return False, str(msg)

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "") -> str:
        if not self.token or not question:
            return ""
        e_type = _EMMCY_TYPE_MAP.get(q_type, "unknown")
        plain_opts = _plain_options(options)
        params = {"token": self.token, "title": question, "type": e_type}
        if plain_opts:
            params["options"] = "\n".join(plain_opts)

        body, err = self._request("GET", f"{self.base_url}/query",
                                  params=params)
        if err or not body:
            return ""
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return ""
        if not isinstance(data, dict) or data.get("code") != 1:
            return ""
        d = data.get("data") or {}
        return _answer_to_str(d.get("answer"))

    def _request(self, method: str, url: str, params: Optional[dict] = None,
                 json_body: Optional[dict] = None,
                 retry: int = _DEFAULT_RETRY) -> Tuple[str, str]:
        last_err = ""
        for _ in range(retry + 1):
            try:
                resp = httpx.request(
                    method, url, params=params, json=json_body,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=self.timeout, verify=False)
                if resp.status_code == 200:
                    if _is_html_body(resp.text):
                        self.last_error = "接口地址无效(返回网页内容, 请检查URL配置)"
                        return "", self.last_error
                    self.last_error = ""
                    return resp.text, ""
                last_err = f"HTTP {resp.status_code}: {(resp.text or '')[:100]}"
            except Exception as e:
                last_err = f"网络错误: {e}"
        self.last_error = last_err
        return "", last_err


class AxeTikuClient(_TikuClientBase):
    """AVXE题库客户端"""

    type_name = "AVXE题库"

    def __init__(self, base_url: str = "", token: str = "",
                 answer_field: str = "$.data.questions[0].answer",
                 timeout: int = _DEFAULT_TIMEOUT):
        super().__init__(_normalize_axe_base(base_url), token, timeout)
        self.answer_field = answer_field or "$.data.questions[0].answer"

    def check(self) -> Tuple[bool, str]:
        if not self.token:
            return False, "未填写token"
        body, err = self._request(
            "POST", f"{self.base_url}/api/checkLeft",
            params={"token": self.token}, form_body={"token": self.token},
            retry=_CHECK_RETRY)
        ok, detail = self._parse_left(body, err)
        if ok:
            return ok, detail + f" (接口: {self.base_url})"
        # URL无效/网络错误时不尝试注册; 否则自动注册token(md5=md5(token))后重试一次
        if err and ("网页" in err or "网络错误" in err):
            return False, detail
        reg_detail = ""
        try:
            md5_val = hashlib.md5(self.token.encode("utf-8")).hexdigest()
            reg_body, reg_err = self._request(
                "PUT", f"{self.base_url}/api/register",
                json_body={"token": self.token, "md5": md5_val},
                retry=_CHECK_RETRY)
            if reg_err:
                reg_detail = f", 注册请求失败({reg_err})"
            else:
                reg_detail = f", 已尝试Token注册: {(reg_body or '')[:80]}"
            body2, err2 = self._request(
                "POST", f"{self.base_url}/api/checkLeft",
                params={"token": self.token}, form_body={"token": self.token},
                retry=_CHECK_RETRY)
            ok2, detail2 = self._parse_left(body2, err2)
            if ok2:
                return ok2, detail2 + reg_detail
        except Exception:
            pass
        return False, detail + reg_detail

    def _parse_left(self, body: str, err: str) -> Tuple[bool, str]:
        if err:
            return False, err
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return False, f"响应格式异常: {(body or '')[:100]}"
        if isinstance(data, dict):
            # 常见剩余次数字段兼容
            for key in ("left", "leftNum", "count", "num", "times", "balance"):
                if isinstance(data.get(key), (int, float)):
                    return True, f"可用, 剩余次数: {data[key]}"
            d = data.get("data")
            if isinstance(d, dict):
                for key in ("left", "leftNum", "count", "num", "times", "balance"):
                    if isinstance(d.get(key), (int, float)):
                        return True, f"可用, 剩余次数: {d[key]}"
            if isinstance(d, (int, float)):
                return True, f"可用, 剩余次数: {d}"
            msg = str(data.get("message") or data.get("msg") or "")
            code = data.get("code")
            if code in (1, 200, "1", "200", True) or "成功" in msg:
                return True, f"可用({msg})" if msg else "可用"
            if msg:
                return False, msg
        return False, f"响应异常: {(body or '')[:100]}"

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "") -> str:
        if not self.token or not question:
            return ""
        plain_opts = _plain_options(options)
        form = {"token": self.token, "tm": question}
        if q_type in _AXE_TYPE_MAP:
            form["type"] = str(_AXE_TYPE_MAP[q_type])
        if plain_opts:
            form["options"] = json.dumps(plain_opts, ensure_ascii=False)
        form["answernum"] = "3"
        form["questionnum"] = "1"
        form["ai"] = "1"

        body, err = self._request(
            "POST", f"{self.base_url}/api/query", params={"v": "2"},
            form_body=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if err or not body:
            return ""
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return ""
        if isinstance(data, dict) and data.get("code") in (0, "0", False):
            # code=0: 未找到答案(如"相似度低于70%")
            return ""
        # 按配置的JSONPath提取(默认 $.data.questions[0].answer), 失败则兼容常见路径
        text = _answer_to_str(_json_path_get(data, self.answer_field))
        if not text and isinstance(data, dict):
            for path in ("$.data.questions[0].answer", "$.data.answer",
                         "$.answer", "$.data"):
                text = _answer_to_str(_json_path_get(data, path))
                if text:
                    break
        return text

    def _request(self, method: str, url: str, params: Optional[dict] = None,
                 form_body: Optional[dict] = None,
                 json_body: Optional[dict] = None,
                 headers: Optional[dict] = None,
                 retry: int = _DEFAULT_RETRY) -> Tuple[str, str]:
        last_err = ""
        for _ in range(retry + 1):
            try:
                resp = httpx.request(
                    method, url,
                    params=params,
                    data=form_body,
                    json=json_body,
                    headers=headers or {"User-Agent": "Mozilla/5.0"},
                    timeout=self.timeout, verify=False)
                if resp.status_code == 200:
                    if _is_html_body(resp.text):
                        self.last_error = "接口地址无效(返回网页内容, 请检查URL配置)"
                        return "", self.last_error
                    self.last_error = ""
                    return resp.text, ""
                last_err = f"HTTP {resp.status_code}: {(resp.text or '')[:100]}"
            except Exception as e:
                last_err = f"网络错误: {e}"
        self.last_error = last_err
        return "", last_err


def _safe_json_loads(text: str):
    """安全JSON解析: 失败返回 None"""
    try:
        return json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None


def _extract_every_simple(data) -> str:
    """EveryAPI简单模式响应解析: {code:0, data:"答案1#答案2", question, msg}
    未命中(code:-1)时无data字段 -> 返回空串
    """
    if not isinstance(data, dict):
        return ""
    if data.get("code") in (-1, "-1"):
        return ""
    d = data.get("data")
    if isinstance(d, str):
        return d.strip()
    if d is not None:
        return _dig_text(d)
    return ""


def _dig_text(v, depth: int = 0) -> str:
    """从任意嵌套值中提取文本(去除重保序, 多值用#连接)"""
    if depth > 4:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        parts = [_dig_text(x, depth + 1) for x in v]
        return _join_parts(parts)
    if isinstance(v, dict):
        # 优先常见内容字段
        for k in ("text", "value", "answer", "content", "title", "name",
                  "option", "options", "answers", "result"):
            if k in v:
                t = _dig_text(v[k], depth + 1)
                if t:
                    return t
        return _join_parts([_dig_text(x, depth + 1) for x in v.values()])
    return ""


def _join_parts(parts) -> str:
    uniq = []
    for p in parts:
        if p and p not in uniq:
            uniq.append(p)
    return "#".join(uniq)


def _extract_every_search_answers(data) -> str:
    """EveryAPI题库搜索(/api/v1/q/)响应解析:
    {code, data:{correct:[{content,option}], question, type}, msg}
    content为嵌套对象, 用通用提取器容错解析
    """
    if not isinstance(data, dict):
        return ""
    d = data.get("data")
    if isinstance(d, str):
        return d.strip()
    if isinstance(d, list):
        return _dig_text(d)
    if not isinstance(d, dict):
        return ""
    corrects = d.get("correct")
    if isinstance(corrects, list) and corrects:
        parts = []
        for item in corrects:
            if isinstance(item, dict):
                txt = _dig_text(item.get("content"))
                if not txt:
                    txt = _dig_text(item)
            else:
                txt = _dig_text(item)
            if txt and txt not in parts:
                parts.append(txt)
        if parts:
            return "#".join(parts)
    for k in ("answer", "content", "data", "text", "result", "answers"):
        if k in d:
            t = _dig_text(d[k])
            if t:
                return t
    return ""


class N1TikuClient(_TikuClientBase):
    """N1题库(无言题库/网课搜题助手)客户端"""

    type_name = "N1题库"

    def __init__(self, base_url: str = "", token: str = "",
                 timeout: int = _DEFAULT_TIMEOUT):
        super().__init__(base_url or N1_DEFAULT_BASE, token, timeout)

    def check(self) -> Tuple[bool, str]:
        if not self.token:
            return False, "未填写token"
        # 用必然不存在的短题探测(未命中不消耗配额), 返回quota_info即key有效
        body, err = self._req(
            "POST", f"{self.base_url}/api/search.php",
            form_body={"question": "__check__", "key": self.token},
            retry=_CHECK_RETRY)
        if err:
            return False, err
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return False, f"响应格式异常: {(body or '')[:100]}"
        if not isinstance(data, dict):
            return False, "响应格式异常"
        quota = data.get("quota_info")
        if isinstance(quota, dict):
            return True, (
                f"可用, 剩余次数: {quota.get('remaining', '未知')} "
                f"(免费剩余: {quota.get('free_remaining', '?')}, "
                f"充值余额: {quota.get('recharge_balance', '?')})"
                f" | 接口: {self.base_url}")
        msg = str(data.get("msg") or "")
        return False, msg or f"响应异常: {(body or '')[:100]}"

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "") -> str:
        if not self.token or not question:
            return ""
        form = {"question": question, "key": self.token}
        cn_type = _N1_TYPE_MAP.get(q_type)
        if cn_type:
            form["type"] = cn_type
        plain_opts = _plain_options(options)
        if plain_opts:
            form["options"] = json.dumps(plain_opts, ensure_ascii=False)
        elif q_type in ("fill", "short", "term_explanation", "essay"):
            # 简答/填空题: 传填写的空数(对齐官方说明)
            form["options"] = json.dumps(["1"], ensure_ascii=False)
        body, err = self._req("POST", f"{self.base_url}/api/search.php",
                              form_body=form)
        if err or not body:
            return ""
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        d = data.get("data")
        if data.get("code") == 1:
            return _answer_to_str(d)
        # 未命中时 data 为列表[{question,answer}], 需过滤占位/无效答案
        if isinstance(d, list):
            for item in d:
                if not isinstance(item, dict):
                    continue
                ans = _answer_to_str(item.get("answer"))
                q_txt = str(item.get("question") or "")
                if not ans:
                    continue
                if ("抱歉" in q_txt or "抱歉" in ans
                        or "无答案" in ans or "搜不到" in ans):
                    continue
                return ans
        return ""


class ZETikuClient(_TikuClientBase):
    """ZE题库(ZError)客户端"""

    type_name = "ZE题库"

    def __init__(self, base_url: str = "", token: str = "",
                 timeout: int = _DEFAULT_TIMEOUT):
        super().__init__(base_url or ZE_DEFAULT_BASE, token, timeout)

    @staticmethod
    def _parse_inner(body: str) -> Optional[dict]:
        """取外层 data 对象 {code, data, msg}"""
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        inner = data.get("data")
        return inner if isinstance(inner, dict) else None

    def check(self) -> Tuple[bool, str]:
        if not self.token:
            return False, "未填写token"
        # 无专用自检接口: 用不存在短题探测(未找到不扣次数)
        body, err = self._req(
            "GET", f"{self.base_url}/api/query",
            params={"token": self.token, "title": "__check__"},
            retry=_CHECK_RETRY)
        if err:
            return False, err
        inner = self._parse_inner(body)
        if inner is None:
            return False, f"响应格式异常: {(body or '')[:100]}"
        code = inner.get("code")
        msg = str(inner.get("msg") or "")
        low = msg.lower()
        bad_kw = ("无效", "过期", "未授权", "认证失败", "不正确")
        if any(k in msg for k in bad_kw) or ("token" in low and code != 1):
            return False, msg or "token无效"
        if code in (0, 1, "0", "1"):
            return True, f"可用(轻量探测通过) | 接口: {self.base_url}"
        return False, msg or f"响应异常: {(body or '')[:100]}"

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "") -> str:
        if not self.token or not question:
            return ""
        params = {"token": self.token, "title": question}
        plain_opts = _plain_options(options)
        if plain_opts:
            params["options"] = "\n".join(plain_opts)
        z_type = _ZE_TYPE_MAP.get(q_type)
        if z_type:
            params["type"] = z_type
        body, err = self._req("GET", f"{self.base_url}/api/query",
                              params=params)
        if err or not body:
            return ""
        inner = self._parse_inner(body)
        if inner is None:
            return ""
        if inner.get("code") in (1, "1"):
            return _answer_to_str(inner.get("data")).strip()
        return ""


class EveryTikuClient(_TikuClientBase):
    """EveryAPI题库(icodef搜题型)客户端

    接口: GET /api/v1/q/{question}?token=KEY
    优先简单模式(simple=true&split=#)直接返回"答案1#答案2";
    未命中为 HTTP 400 + {code:-1, msg:"没有找到相关问题"}(业务体正常解析);
    服务端限流("2并发限制") -> 全局串行+最小间隔节流
    """

    type_name = "EveryAPI题库"

    def __init__(self, base_url: str = "", token: str = "",
                 model: str = "", timeout: int = _DEFAULT_TIMEOUT):
        # model 参数保留仅为配置兼容(新接口已无AI聊天兜底)
        super().__init__(_normalize_every_base(base_url), token, timeout)
        self.model = (model or "").strip()

    def _headers(self) -> dict:
        # 新接口按官方示例仅用 query token, 无需 Bearer 头
        return {"User-Agent": "Mozilla/5.0"}

    @staticmethod
    def _throttle():
        """全局节流: 服务端限制2并发, 串行化并保证最小请求间隔
        (多账号/多线程共享同一 token 时防触发"2并发限制")
        """
        with _EVERY_LOCK:
            wait = _EVERY_MIN_INTERVAL - (time.time() - _EVERY_LAST_TS[0])
            if wait > 0:
                time.sleep(wait)
            _EVERY_LAST_TS[0] = time.time()

    def check(self) -> Tuple[bool, str]:
        if not self.token:
            return False, "未填写token"
        # 题库搜索接口轻量探测(hello短题)
        self._throttle()
        body, err = self._req(
            "GET", f"{self.base_url}/api/v1/q/hello",
            params={"token": self.token}, headers=self._headers(),
            retry=_CHECK_RETRY)
        if err:
            return False, err
        try:
            data = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return False, f"响应格式异常: {(body or '')[:100]}"
        if isinstance(data, dict) and "code" in data:
            return True, f"可用 | 接口: {self.base_url}"
        return False, f"响应异常: {(body or '')[:100]}"

    def _query_once(self, question: str, params_extra: dict,
                    attempts: int = 3) -> str:
        """单次搜题请求(接受400承载的业务体) -> 原始JSON

        服务端限流(msgs含"并发/太快/频繁")时退避重试
        """
        url = (f"{self.base_url}/api/v1/q/"
               f"{_url_quote(question, safe='')}")
        params = {"token": self.token}
        params.update(params_extra or {})
        body = ""
        for i in range(max(1, attempts)):
            self._throttle()
            body, err = self._req("GET", url, params=params,
                                  headers=self._headers(), retry=1,
                                  ok_status=(200, 400))
            if not body:
                return ""
            data = _safe_json_loads(body)
            if isinstance(data, dict):
                msg = str(data.get("msg") or data.get("message") or "")
                if ("并发" in msg or "太快" in msg or "频繁" in msg) \
                        and i < attempts - 1:
                    time.sleep(0.8 * (i + 1))  # 退避后重试
                    continue
            break
        return body

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "") -> str:
        if not self.token or not question:
            return ""
        question = question.strip()
        # 1. 简单模式(官方推荐: 直接返回以 split 拼接的答案串)
        body = self._query_once(question, {"simple": "true", "split": "#"})
        ans = _extract_every_simple(_safe_json_loads(body))
        if ans:
            return ans
        # 2. 结构化模式(兜底: 返回 correct[].content)
        body = self._query_once(question, {})
        return _extract_every_search_answers(_safe_json_loads(body))


def log_debug_source(name: str, msg: str):
    """统一的答题源调试日志"""
    log_print(INFO, DarkGray, f"[答题源] [{name}] {msg}")
