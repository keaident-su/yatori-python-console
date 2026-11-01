# -*- coding: utf-8 -*-
"""海旗科技 API"""
from typing import Tuple, Optional, Any
from logic.core.http_client import HttpClient
from logic.haiqikeji.models import HqkjUserCache


def _build_client(cache: HqkjUserCache) -> HttpClient:
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    if cache.cookie_dict:
        client.load_cookies(cache.cookie_dict)
    return client


def _extract_cookies(client: HttpClient, cache):
    for name, value in client.cookies.items():
        cache.cookie_dict[name] = value


def login_api(cache: HqkjUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/user/login"
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


def course_list_api(cache: HqkjUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/courseList"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def node_list_api(cache: HqkjUserCache, course_id: str,
                  retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/nodeList?courseId={course_id}"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def start_study_api(cache: HqkjUserCache, video_id: str, course_id: str,
                    retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/startStudy"
    data = {"videoId": video_id, "courseId": course_id}
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()


def submit_study_time_api(cache: HqkjUserCache, video_id: str, course_id: str,
                          study_time: int, progress: int,
                          retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/submitStudyTime"
    data = {
        "videoId": video_id, "courseId": course_id,
        "studyTime": str(study_time), "progress": str(progress),
    }
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()


def end_study_api(cache: HqkjUserCache, video_id: str, course_id: str,
                  retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/endStudy"
    data = {"videoId": video_id, "courseId": course_id}
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()


def work_list_api(cache: HqkjUserCache, course_id: str,
                  retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/workList?courseId={course_id}"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def exam_list_api(cache: HqkjUserCache, course_id: str,
                  retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/examList?courseId={course_id}"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


# ==================== [V3.2.0 作业/考试写题] 对齐 core api/haiqikeji/HqkjWorkExamApi.go ====================
# 体系差异: 旧接口(/api/student/* 走 cookie) vs 新 yee_* 接口(走 authorization Token +
# schoolId/studentId)。本节全部使用 Token 头，复用预登录得到的 cache.token/school_id/user_id。

_TOKEN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")


def yee_work_list_api(cache: HqkjUserCache, course_id: str, node_id: str,
                      retry: int = 10) -> Tuple[str, Optional[Any]]:
    """yee 新版作业列表(带 nodeId, 对齐 core PullWorkInfoApi)"""
    url = (f"{cache.pre_url}/api/user/yee_course_student_work_list"
           f"?schoolId={cache.school_id}&studentId={cache.user_id}"
           f"&courseId={course_id}&nodeId={node_id}")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def yee_exam_list_api(cache: HqkjUserCache, course_id: str, node_id: str,
                      retry: int = 10) -> Tuple[str, Optional[Any]]:
    """yee 新版考试列表(带 nodeId, 对齐 core PullExamListApi)"""
    url = (f"{cache.pre_url}/api/user/yee_course_student_exam_list"
           f"?schoolId={cache.school_id}&studentId={cache.user_id}"
           f"&courseId={course_id}&nodeId={node_id}")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def _token_client(cache: HqkjUserCache) -> HttpClient:
    return _build_client(cache)


def _token_headers(cache: HqkjUserCache, json_body: bool = False) -> dict:
    h = {
        "accept": "application/json, text/plain, */*",
        "authorization": cache.token,
        "user-agent": _TOKEN_UA,
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }
    if json_body:
        h["content-type"] = "application/json"
        h["origin"] = cache.pre_url
    return h


def selectdomain_api(cache: HqkjUserCache, retry: int = 5) -> Tuple[str, Optional[Any]]:
    """通过域名拿学校 id(对齐 core PullSchoolInfoApi: data.id) - 登录前调用"""
    from urllib.parse import urlparse
    hostname = urlparse(cache.pre_url).hostname or ""
    url = f"{cache.pre_url}/api/course/selectdomain?domain={hostname}"
    client = _token_client(cache)
    try:
        return client.get(url, headers={"user-agent": _TOKEN_UA}, retry=retry)
    finally:
        client.close()


def student_info_api(cache: HqkjUserCache, retry: int = 5) -> Tuple[str, Optional[Any]]:
    """拉个人信息(对齐 core PullUserInfoApi: data.id → userId)"""
    url = f"{cache.pre_url}/api/user/yee_student_info"
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def work_detail_api(cache: HqkjUserCache, work_id: str, course_id: str,
                    title: str = "", retry: int = 10) -> Tuple[str, Optional[Any]]:
    from urllib.parse import quote
    url = (f"{cache.pre_url}/api/user/yee_course_student_work_detail"
           f"?schoolId={cache.school_id}&studentId={cache.user_id}"
           f"&workId={work_id}&courseId={course_id}&title={quote(title)}")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def exam_detail_api(cache: HqkjUserCache, exam_id: str, course_id: str,
                    title: str = "", retry: int = 10) -> Tuple[str, Optional[Any]]:
    from urllib.parse import quote
    url = (f"{cache.pre_url}/api/user/yee_course_student_exam_detail"
           f"?schoolId={cache.school_id}&studentId={cache.user_id}"
           f"&examId={exam_id}&courseId={course_id}&title={quote(title)}")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def _start_api(cache: HqkjUserCache, kind: str, quiz_id: str, course_id: str,
               paper_id: str, class_id: str, retry: int = 10) -> Tuple[str, Optional[Any]]:
    """work_start / exam_start(开考/开始作业拉题); paperId 为 0 也必须显式传 "0"""
    pid = paper_id or "0"
    if kind == "work":
        path = "yee_course_student_work_start"
        id_key = "workId"
    else:
        path = "yee_course_student_exam_start"
        id_key = "examId"
    url = (f"{cache.pre_url}/api/user/{path}"
           f"?schoolId={cache.school_id}&studentId={cache.user_id}"
           f"&courseId={course_id}&{id_key}={quiz_id}"
           f"&platform=pc&createUserId={cache.user_id}&state=1"
           f"&classId={class_id}&paperId={pid}"
           f"&random=&randData=%257B%257D&randNumber=")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def work_start_api(cache: HqkjUserCache, work_id: str, course_id: str,
                   paper_id: str, class_id: str,
                   retry: int = 10) -> Tuple[str, Optional[Any]]:
    return _start_api(cache, "work", work_id, course_id, paper_id, class_id, retry)


def exam_start_api(cache: HqkjUserCache, exam_id: str, course_id: str,
                   paper_id: str, class_id: str,
                   retry: int = 10) -> Tuple[str, Optional[Any]]:
    return _start_api(cache, "exam", exam_id, course_id, paper_id, class_id, retry)


def work_consult_api(cache: HqkjUserCache, record_id: str, course_id: str,
                     retry: int = 10) -> Tuple[str, Optional[Any]]:
    """yee_work_record_consult_list(老式作业回退拉题: 题目在 data.workResult[])"""
    url = (f"{cache.pre_url}/api/user/yee_work_record_consult_list"
           f"?schoolId={cache.school_id}&userId={cache.user_id}"
           f"&workId={record_id}&courseId={course_id}")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def exam_consult_api(cache: HqkjUserCache, record_id: str, course_id: str,
                     retry: int = 10) -> Tuple[str, Optional[Any]]:
    url = (f"{cache.pre_url}/api/user/yee_exam_record_consult_list"
           f"?schoolId={cache.school_id}&userId={cache.user_id}"
           f"&examId={record_id}&courseId={course_id}")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()


def submit_work_answer_api(cache: HqkjUserCache, course_id: str, work_id: str,
                           topic_id: str, record_id: str, q_type: str,
                           answers, retry: int = 10) -> Tuple[str, Optional[Any]]:
    import json
    payload = {
        "schoolId": int(cache.school_id or 0), "courseId": int(course_id or 0),
        "userId": int(cache.user_id or 0), "workId": int(work_id or 0),
        "topicId": int(topic_id or 0), "answer": list(answers or []),
        "recordId": int(record_id or 0), "type": int(q_type or 1),
    }
    url = f"{cache.pre_url}/api/user/yee_work_answer_add"
    client = _token_client(cache)
    try:
        return client.post_json(url, payload, headers=_token_headers(cache, True), retry=retry)
    finally:
        client.close()


def submit_exam_answer_api(cache: HqkjUserCache, course_id: str, exam_id: str,
                           topic_id: str, record_id: str, q_type: str,
                           answers, retry: int = 10) -> Tuple[str, Optional[Any]]:
    payload = {
        "schoolId": int(cache.school_id or 0), "courseId": int(course_id or 0),
        "userId": int(cache.user_id or 0), "examId": int(exam_id or 0),
        "topicId": int(topic_id or 0), "answer": list(answers or []),
        "recordId": int(record_id or 0), "type": int(q_type or 1),
    }
    url = f"{cache.pre_url}/api/user/yee_exam_answer_add"
    client = _token_client(cache)
    try:
        return client.post_json(url, payload, headers=_token_headers(cache, True), retry=retry)
    finally:
        client.close()


def finish_exam_answer_api(cache: HqkjUserCache, course_id: str, exam_id: str,
                           record_id: str, retry: int = 10) -> Tuple[str, Optional[Any]]:
    """交卷(yee_exam_answer_finish, state=2); 逐题 answer_add 仅暂存"""
    url = (f"{cache.pre_url}/api/user/yee_exam_answer_finish"
           f"?schoolId={cache.school_id}&studentId={cache.user_id}"
           f"&userId={cache.user_id}&workId={exam_id}&examId={exam_id}"
           f"&state=2&recordId={record_id or 0}&courseId={course_id}")
    client = _token_client(cache)
    try:
        return client.get(url, headers=_token_headers(cache), retry=retry)
    finally:
        client.close()
