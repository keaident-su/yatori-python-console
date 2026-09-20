# -*- coding: utf-8 -*-
"""
第三方题库客户端 - 言溪题库(emmcy) / AVXE题库(axe)
接口规范来源: 项目根目录参考材料
  - emmcy_tiku_python_sdk/言溪题库 接口 API 开发者文档
  - axe_tiku_python_sdk/示例：题目查询.py 等

言溪题库(默认 https://tk.enncy.cn):
  查题: GET  /query?token=xxx&title=题目&options=选项1(\n分隔)&type=single
  自检: GET  /info?token=xxx           -> data.times 为剩余次数, code==1 有效
AVXE题库(默认 https://tk.wanjuantiku.com, 旧域名tk.tk.icu已停用):
  查题: POST /api/query?v=2  (form)   token/tm/type/options(JSON数组串)/answernum/questionnum/ai
        返回 {code:1, data:{questions:[{tm, answer, percent}], lefts}}
  自检: POST /api/checkLeft?token=xxx  返回 {code:1, data:剩余次数}
  注册: PUT  /api/register {token, md5}  (自检失败时自动尝试一次)
"""
import hashlib
import json
import re
from typing import List, Optional, Tuple

import httpx

from utils.log import log_print, INFO, DarkGray

_DEFAULT_TIMEOUT = 10
_DEFAULT_RETRY = 2
_CHECK_RETRY = 0

# AXE题库默认(新)接口地址; 以下旧地址会自动纠正到新域名
AXE_DEFAULT_BASE = "https://tk.wanjuantiku.com"
_AXE_LEGACY_MARKERS = ("apifox.cn", "tk.tk.icu",
                       "doc.v2.tk.icu", "apifoxmock.com")


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


def log_debug_source(name: str, msg: str):
    """统一的答题源调试日志"""
    log_print(INFO, DarkGray, f"[答题源] [{name}] {msg}")
