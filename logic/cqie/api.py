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
