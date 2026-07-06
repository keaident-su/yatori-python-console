# -*- coding: utf-8 -*-
"""
学习公社 API 接口层
"""
from typing import Tuple, Optional, Any, Dict
from logic.core.http_client import HttpClient
from logic.enaea.models import EnaeaUserCache


def _build_client(cache: EnaeaUserCache) -> HttpClient:
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    if cache.cookie_dict:
        client.load_cookies(cache.cookie_dict)
    return client


def _extract_cookies(client: HttpClient, cache):
    for name, value in client.cookies.items():
        cache.cookie_dict[name] = value


def login_api(cache: EnaeaUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """登录 POST https://study.enaea.cn/api/login"""
    url = f"{cache.pre_url}/api/login"
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


def project_list_api(cache: EnaeaUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """项目列表"""
    url = f"{cache.pre_url}/api/circle/myList.json"
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()


def course_list_api(cache: EnaeaUserCache, circle_id: str,
                    retry: int = 8) -> Tuple[str, Optional[Any]]:
    """课程列表"""
    url = f"{cache.pre_url}/api/course/myCourseList.json?circleId={circle_id}"
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()


def video_list_api(cache: EnaeaUserCache, course_id: str,
                   retry: int = 8) -> Tuple[str, Optional[Any]]:
    """视频列表"""
    url = f"{cache.pre_url}/api/course/courseDetail.json?courseId={course_id}"
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()


def statistic_tic_cc_video_api(cache: EnaeaUserCache, cc_video_id: str,
                               content_id: str, course_id: str,
                               retry: int = 8) -> Tuple[str, Optional[Any]]:
    """CC视频统计"""
    url = f"{cache.pre_url}/api/course/statisticTicForCCVide.json"
    data = {"ccVideoId": cc_video_id,
            "contentId": content_id, "courseId": course_id}
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=False, retry=retry)
        return body, resp
    finally:
        client.close()


def submit_study_time_api(cache: EnaeaUserCache, content_id: str,
                          course_id: str, study_time: int,
                          is_finish: int, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """提交学时"""
    url = f"{cache.pre_url}/api/course/submitStudyTime.json"
    data = {
        "contentId": content_id,
        "courseId": course_id,
        "studyTime": str(study_time),
        "isFinish": str(is_finish),
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=False, retry=retry)
        return body, resp
    finally:
        client.close()
