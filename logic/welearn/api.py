"""WeLearn API"""
from typing import Tuple, Optional, Any
from logic.core.http_client import HttpClient
from logic.welearn.models import WeLearnUserCache


def _build_client(cache: WeLearnUserCache) -> HttpClient:
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    if cache.cookie_dict:
        client.load_cookies(cache.cookie_dict)
    return client


def _extract_cookies(client: HttpClient, cache):
    for name, value in client.cookies.items():
        cache.cookie_dict[name] = value


def login_api(cache: WeLearnUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
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


def course_list_api(cache: WeLearnUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/courseList"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def study_plan_api(cache: WeLearnUserCache, course_id: str,
                   retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/studyPlan?courseId={course_id}"
    client = _build_client(cache)
    try:
        return client.get(url, retry=retry)
    finally:
        client.close()


def keep_point_session_api(cache: WeLearnUserCache, scorm_id: str,
                           study_time: int, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/keepPointSession"
    data = {"scormId": scorm_id, "studyTime": str(study_time)}
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()


def submit_study_plan_api(cache: WeLearnUserCache, scorm_id: str,
                          progress: int, study_time: int,
                          retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = f"{cache.pre_url}/api/student/submitStudyPlan2"
    data = {"scormId": scorm_id, "progress": str(
        progress), "studyTime": str(study_time)}
    client = _build_client(cache)
    try:
        return client.post_form(url, data, use_multipart=False, retry=retry)
    finally:
        client.close()
