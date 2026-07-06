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
