# -*- coding: utf-8 -*-
"""重庆工程学院 API 接口层"""
from typing import Tuple, Optional, Any
from logic.core.http_client import HttpClient
from logic.cqie.models import CqieUserCache


def _build_client(cache: CqieUserCache) -> HttpClient:
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    if cache.cookie_dict:
        client.load_cookies(cache.cookie_dict)
    return client


def _extract_cookies(client: HttpClient, cache):
    for name, value in client.cookies.items():
        cache.cookie_dict[name] = value


def login_api(cache: CqieUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
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


def course_list_api(cache: CqieUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/courseList"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def video_list_api(cache: CqieUserCache, course_id: str,
                   retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/videoList?courseId={course_id}"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def save_video_study_time_api(cache: CqieUserCache, video_id: str,
                              start_pos: int, stop_pos: int,
                              retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/saveVideoStudyTime"
    data = {"videoId": video_id, "startPos": str(
        start_pos), "stopPos": str(stop_pos)}
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()


def submit_study_time_api(cache: CqieUserCache, video_id: str,
                          study_id: str, start_time: str,
                          start_pos: int, stop_pos: int, max_pos: int,
                          retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/submitStudyTime"
    data = {
        "videoId": video_id, "studyId": study_id,
        "startTime": start_time,
        "startPos": str(start_pos), "stopPos": str(stop_pos), "maxPos": str(max_pos),
    }
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()

# ============ App链API (study.cqie.edu.cn, 2026-10-15, 移植Go) ============

_CQIE_APP = "https://study.cqie.edu.cn/gateway/study"

def pull_video_work_paper_api(cache: CqieUserCache, knowledge_node_id: str,
                              student_course_id: str, unit_id: str,
                              retry: int = 5) -> Tuple[str, Optional[Any]]:
    """拉视频作业卷: POST /studyKnowledgeExerciseRecord/exercisesList"""
    url = f"{_CQIE_APP}/studyKnowledgeExerciseRecord/exercisesList"
    body = {"knowledgeNodeId": knowledge_node_id,
            "studentCourseId": student_course_id, "unitId": unit_id}
    import httpx as _hx
    try:
        r = _hx.post(url, json=body, timeout=30, verify=False, headers={
            "authorization": cache.access_token or "",
            "origin": "https://study.cqie.edu.cn",
            "content-type": "application/json;charset=UTF-8;"})
        return r.text, None
    except Exception as e:
        return "", e


def submit_work_answer_api(cache: CqieUserCache, answer_json: str,
                           retry: int = 5) -> Tuple[str, Optional[Any]]:
    """提交作业答案: POST /studyKnowledgeExerciseSummaryRecord/createList"""
    url = f"{_CQIE_APP}/studyKnowledgeExerciseSummaryRecord/createList"
    import httpx as _hx
    try:
        r = _hx.post(url, content=answer_json.encode("utf-8"), timeout=30,
                     verify=False, headers={
                         "authorization": cache.access_token or "",
                         "origin": "https://study.cqie.edu.cn",
                         "content-type": "application/json;charset=UTF-8;"})
        return r.text, None
    except Exception as e:
        return "", e

def app_login_api(cache: CqieUserCache, retry: int = 6) -> Tuple[str, Optional[Any]]:
    """重庆App登录(2026-10-15 移植Go CqieLoginAction)

    流程: createCaptcha(uuid) -> OCR -> login(account/password经SM4加密hex) -> data.access_token
    成功后 cache.access_token / student_id 等填充(供作业链)
    """
    import httpx as _hx
    import uuid as _uuid
    import json as _json
    from logic.cqie.sm4_pure import cqie_encrypt
    from logic.core.ocr_utils import ocr_bytes
    base = "https://study.cqie.edu.cn/gateway"
    for _try in range(max(1, retry)):
        try:
            _uid = str(_uuid.uuid4())
            # 1. 验证码
            cr = _hx.get(f"{base}/auth/createCaptcha?uuid={_uid}", timeout=30, verify=False)
            code_text = (ocr_bytes(cr.content) or "").strip().replace(" ", "")
            if not code_text:
                continue
            # 2. 登录(SM4加密账号密码, hex)
            acc = cqie_encrypt(cache.account).hex()
            pwd = cqie_encrypt(cache.password).hex()
            body = {"account": acc, "password": pwd, "code": code_text,
                    "status": 0, "uuid": _uid, "student": True}
            lr = _hx.post(f"{base}/auth/login", timeout=30, verify=False,
                          json=body, headers={"Content-Type": "application/json"})
            lj = lr.json()
            if not (lj or {}).get("status") and not ((lj or {}).get("data") or {}).get("access_token"):
                msg = str((lj or {}).get("msg", "") or "")
                if "验证码" in msg:
                    continue
            data = (lj or {}).get("data") or {}
            tok = str(data.get("access_token", "") or "")
            if tok:
                cache.access_token = tok
                _u = data.get("user") or {}
                cache.student_id = str(_u.get("studentId", "") or _u.get("id", "") or "")
                cache.dept_id = str(_u.get("deptId", "") or "")
                cache.major_id = str(_u.get("majorId", "") or _u.get("orgMajorId", "") or "")
                cache.org_id = str(_u.get("orgId", "") or "")
                return lr.text, None
            return lr.text, None
        except Exception:
            continue
    return "", Exception("重庆App登录失败(重试耗尽)")

