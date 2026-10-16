# -*- coding: utf-8 -*-
"""青书学堂 API"""
from typing import Tuple, Optional, Any
from logic.core.http_client import HttpClient
from logic.qingshuxuetang.models import QsxtUserCache


def _build_client(cache: QsxtUserCache) -> HttpClient:
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    if cache.cookie_dict:
        client.load_cookies(cache.cookie_dict)
    return client


def _extract_cookies(client: HttpClient, cache):
    for name, value in client.cookies.items():
        cache.cookie_dict[name] = value


def login_api(cache: QsxtUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/login"
    data = {"username": cache.account, "password": cache.password}
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=False, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def course_list_api(cache: QsxtUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/courseList"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def node_list_api(cache: QsxtUserCache, course_id: str,
                  retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/chapterList?courseId={course_id}"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def start_study_time_api(cache: QsxtUserCache, node_id: str, course_id: str,
                         retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/startStudyTime"
    data = {"nodeId": node_id, "courseId": course_id}
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()


def submit_study_time_api(cache: QsxtUserCache, node_id: str, course_id: str,
                          study_time: int, is_finish: bool,
                          retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/submitStudyTime"
    data = {
        "nodeId": node_id, "courseId": course_id,
        "studyTime": str(study_time),
        "isFinish": "true" if is_finish else "false",
    }
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()


def work_list_api(cache: QsxtUserCache, course_id: str,
                  retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/workList?courseId={course_id}"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def write_work_api(cache: QsxtUserCache, work_id: str, answer: str,
                   retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/writeWork"
    data = {"workId": work_id, "answer": answer}
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()

# ============ App端API (api.qingshuxuetang.com/v25_10, 2026-10-15) ============

_QS_APP_BASE = "https://api.qingshuxuetang.com/v25_10"

def _qs_app_headers(cache: QsxtUserCache) -> dict:
    """青书App端请求头(Authorization-QS 等, 对齐Go)"""
    return {
        "User-Agent": "okhttp/4.2.2",
        "Connection": "Keep-Alive",
        "Authorization-QS": cache.token or "",
        "Device-Trace-Id-QS": "b0afcf7e-a8ae-48f2-b438-66982a13dc16",
        "Device-Info-QS": ("{\"appType\":1,\"appVersion\":\"25.10.0\",\"clientType\":2,"
                           "\"deviceName\":\"xiaomi MI 5X\",\"netType\":1,\"osVersion\":\"8.1.0\"}"),
        "User-Agent-QS": "QSXT",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "*/*",
    }


def pull_work_list_app_api(cache: QsxtUserCache, period_id: str, class_id: str,
                           school_id: str, course_id: str,
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """App拉作业列表: GET /quiz/search?periodId=&classId=&schoolId=&type=2&courseId="""
    url = (f"{_QS_APP_BASE}/quiz/search?periodId={period_id}&classId={class_id}"
           f"&schoolId={school_id}&type=2&courseId={course_id}")
    import httpx as _hx
    try:
        r = _hx.get(url, headers=_qs_app_headers(cache), timeout=30, verify=False)
        return r.text, None
    except Exception as e:
        return "", e


def pull_work_question_list_api(cache: QsxtUserCache, class_id: str, quiz_id: str,
                                school_id: str, course_id: str,
                                retry: int = 3) -> Tuple[str, Optional[Any]]:
    """App拉题目(含solution答案!): GET /quiz/detail?classId=&quizId=&schoolId=&courseId="""
    url = (f"{_QS_APP_BASE}/quiz/detail?classId={class_id}&quizId={quiz_id}"
           f"&schoolId={school_id}&courseId={course_id}")
    import httpx as _hx
    try:
        r = _hx.get(url, headers=_qs_app_headers(cache), timeout=30, verify=False)
        return r.text, None
    except Exception as e:
        return "", e


def submit_answer_api(cache: QsxtUserCache, answer: str, question_id: str,
                      quiz_id: str, school_id: str,
                      retry: int = 5) -> Tuple[str, Optional[Any]]:
    """App逐题提交: POST /quiz/question/answer"""
    url = f"{_QS_APP_BASE}/quiz/question/answer"
    body = {"questionAnswers": [{"answer": answer, "questionId": question_id}],
            "quizId": quiz_id, "schoolId": int(school_id) if str(school_id).isdigit() else school_id}
    import httpx as _hx
    try:
        r = _hx.post(url, json=body, headers=_qs_app_headers(cache), timeout=30, verify=False)
        return r.text, None
    except Exception as e:
        return "", e


def save_answer_api(cache: QsxtUserCache, answers_json: str,
                    retry: int = 3) -> Tuple[str, Optional[Any]]:
    """App整卷保存/提交: POST /quiz/submit"""
    url = f"{_QS_APP_BASE}/quiz/submit"
    import httpx as _hx
    try:
        r = _hx.post(url, content=answers_json.encode("utf-8"),
                     headers=_qs_app_headers(cache), timeout=30, verify=False)
        return r.text, None
    except Exception as e:
        return "", e

def app_login_api(cache: QsxtUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """青书App登录(算式验证码OCR, 2026-10-15 移植Go QsxtLoginAction)

    流程: getValidationCode(拿图+sessionId) -> OCR识别算式 -> 计算 -> login -> data.token
    成功后 cache.token = App令牌(供Authorization-QS/作业链使用)
    """
    import httpx as _hx
    import base64 as _b64
    from logic.core.ocr_utils import ocr_bytes
    base = "https://api.qingshuxuetang.com/v25_10"
    for _try in range(max(1, retry)):
        try:
            # 1. 拿验证码(图+sessionId)
            r = _hx.post(f"{base}/account/getValidationCode",
                         json={}, timeout=30, verify=False,
                         headers={"Content-Type": "application/json; charset=UTF-8"})
            j = r.json()
            data = (j or {}).get("data") or {}
            session_id = str(data.get("sessionId", "") or "")
            code_b64 = str(data.get("code", "") or "")
            if not session_id or not code_b64:
                return r.text, None
            # 2. OCR识别算式
            img = _b64.b64decode(code_b64.split(",")[-1])
            text = (ocr_bytes(img) or "").strip()
            # 3. 计算(支持 3+5 / 12-4 / 2x3 等; 安全解析)
            import re as _re
            expr = text.replace("×", "*").replace("x", "*").replace("X", "*").replace("÷", "/")
            m = _re.fullmatch(r"\s*(\d+)\s*([+\-*/])\s*(\d+)\s*", expr)
            if not m:
                continue  # OCR失败重试
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            val = (a + b) if op == "+" else (a - b) if op == "-" else (a * b) if op == "*" else (a // b if b else 0)
            # 4. 登录
            body = {"name": cache.account, "password": cache.password, "type": 1,
                    "validation": {"sessionId": session_id, "type": 3, "userInput": str(val)}}
            lr = _hx.post(f"{base}/account/login", json=body, timeout=30, verify=False,
                          headers={"Content-Type": "application/json; charset=UTF-8"})
            lj = lr.json()
            msg = str((lj or {}).get("message", "") or "")
            if "验证码" in msg or "答案错误" in msg:
                continue  # 重试
            token = str(((lj or {}).get("data") or {}).get("token", "") or "")
            if token:
                cache.token = token
                return lr.text, None
            return lr.text, None
        except Exception:
            continue
    return "", Exception("青书App登录失败(重试耗尽)")

