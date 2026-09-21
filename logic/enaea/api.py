# -*- coding: utf-8 -*-
"""
学习公社 API 接口层 - 对齐 yatori-go-core (api/enaea/EnaeaApi.go)
正确域名: study.enaea.edu.cn (学习) / passport.enaea.edu.cn (登录)
注意: 原实现使用的 study.enaea.cn 域名不存在, 且接口路径全部不符, 已按Go核心库重写
"""
import hashlib
import time
from typing import Tuple, Optional, Any, Dict

from logic.core.http_client import HttpClient
from logic.enaea.models import EnaeaUserCache

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _build_client(cache: EnaeaUserCache) -> HttpClient:
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    return client


def _md5_upper(text: str) -> str:
    """登录密码加密: MD5(密码) 转大写 (对齐Go getMD5Str)"""
    return hashlib.md5(text.encode("utf-8")).hexdigest().upper()


def _now_ms() -> int:
    return int(time.time() * 1000)


def login_api(cache: EnaeaUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """登录 - 对齐Go LoginApi

    GET https://passport.enaea.edu.cn/login.do?ajax=true&jsonp=ablesky_{ts}
        &j_username={账号}&j_password={MD5大写(密码)}
        &_acegi_security_remember_me=false&_={ts}
    成功后从响应Set-Cookie中提取 ASUSS 凭证
    """
    ts = str(_now_ms())
    url = (
        f"{cache.passport_url}/login.do?ajax=true&jsonp=ablesky_{ts}"
        f"&j_username={cache.account}&j_password={_md5_upper(cache.password)}"
        f"&_acegi_security_remember_me=false&_={ts}"
    )
    client = _build_client(cache)
    try:
        body, resp = client.get(url, headers={
            "User-Agent": _UA,
            "Referer": f"{cache.pre_url}/login.do",
            "Accept": "*/*",
        }, retry=retry)
        # 提取 ASUSS 凭证(响应Set-Cookie)
        if resp is not None:
            try:
                for cookie_name, cookie_value in resp.cookies.items():
                    if cookie_name == "ASUSS":
                        cache.asuss = cookie_value
                    cache.cookie_dict[cookie_name] = cookie_value
            except Exception:
                pass
        if not cache.asuss:
            try:
                asuss = client.cookies.get("ASUSS")
                if asuss:
                    cache.asuss = asuss
                    cache.cookie_dict["ASUSS"] = asuss
            except Exception:
                pass
        return body, resp
    finally:
        client.close()


def _study_get(cache: EnaeaUserCache, url: str,
               retry: int = 8) -> Tuple[str, Optional[Any]]:
    """学习站内 GET(携带 ASUSS 凭证)"""
    client = _build_client(cache)
    try:
        return client.get(url, headers={
            "User-Agent": _UA,
            "Accept": "*/*",
            "Cookie": f"ASUSS={cache.asuss};",
        }, retry=retry)
    finally:
        client.close()


def project_list_api(cache: EnaeaUserCache,
                     retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取项目列表 - 对齐Go PullProjectsApi"""
    url = (f"{cache.pre_url}/assessment.do?action=getMyCircleCourses"
           f"&start=0&limit=200&isFinished=false&_={_now_ms()}")
    return _study_get(cache, url, retry=retry)


def pull_course_html_api(cache: EnaeaUserCache, circle_id: str,
                         retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取项目页HTML(用于提取侧边栏课程菜单) - 对齐Go PullStudyCourseHTMLApi"""
    url = (f"{cache.pre_url}/circleIndexRedirect.do?action=toCircleIndex"
           f"&circleId={circle_id}&ct={_now_ms()}")
    return _study_get(cache, url, retry=retry)


def course_list_api(cache: EnaeaUserCache, circle_id: str, syllabus_id: str,
                    module: str = "", retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取课程列表 - 对齐Go PullStudyCourseListApi

    :param module: 侧边栏type后缀(如 courseCategory4jwu/exam), 空为getMyClass
    """
    action = f"getMyClassFor{module}" if module else "getMyClass"
    url = (f"{cache.pre_url}/circleIndex.do?action={action}"
           f"&start=0&limit=200&isCompleted=&circleId={circle_id}"
           f"&syllabusId={syllabus_id}&categoryRemark=all&_={_now_ms()}")
    return _study_get(cache, url, retry=retry)


def video_list_api(cache: EnaeaUserCache, circle_id: str, course_id: str,
                   retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取课程视频列表 - 对齐Go PullCourseVideoListApi"""
    url = (f"{cache.pre_url}/course.do?action=getCourseContentList"
           f"&courseId={course_id}&circleId={circle_id}&_={_now_ms()}")
    return _study_get(cache, url, retry=retry)


def pull_icourse_html_api(cache: EnaeaUserCache, circle_id: str, course_id: str,
                          retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取icourse外部课程页面 - 对齐Go PullICourseWorkHTMLApi"""
    url = (f"{cache.pre_url}/viewerforicourse.do"
           f"?courseId={course_id}&circleId={circle_id}")
    return _study_get(cache, url, retry=retry)


def statistic_tic_cc_video_api(cache: EnaeaUserCache, course_id: str,
                               course_content_id: str, circle_id: str,
                               retry: int = 8) -> Tuple[str, str, str, Optional[Any]]:
    """观看视频前调用(开始计时) - 对齐Go StatisticTicForCCVideApi

    :return: (响应体, SCFUCKP cookie名, SCFUCKP cookie值, 响应对象)
    """
    url = (f"{cache.pre_url}/course.do?action=statisticForCCVideo"
           f"&courseId={course_id}&coursecontentId={course_content_id}"
           f"&circleId={circle_id}&_={_now_ms()}")
    client = _build_client(cache)
    try:
        body, resp = client.get(url, headers={
            "User-Agent": _UA,
            "Accept": "*/*",
            "Cookie": f"ASUSS={cache.asuss};",
        }, retry=retry)
        scfuckp_key, scfuckp_value = "", ""
        if resp is not None:
            try:
                for cookie_name, cookie_value in resp.cookies.items():
                    if cookie_name.startswith("SCFUCKP"):
                        scfuckp_key, scfuckp_value = cookie_name, cookie_value
                        break
            except Exception:
                pass
        if scfuckp_key:
            cache.scfuckp_key = scfuckp_key
            cache.scfuckp_value = scfuckp_value
        return body or "", scfuckp_key, scfuckp_value, resp
    finally:
        client.close()


def _cookie_header(cache: EnaeaUserCache) -> str:
    """构建请求Cookie(ASUSS + 可选SCFUCKP)"""
    cookie = f"ASUSS={cache.asuss};"
    if cache.scfuckp_key:
        cookie += f"{cache.scfuckp_key}={cache.scfuckp_value}"
    return cookie


def _submit_study_log(cache: EnaeaUserCache, form: Dict[str, str],
                      retry: int = 8) -> Tuple[str, Optional[Any]]:
    """POST studyLog.do (普通/快速 共用的提交入口)"""
    url = f"{cache.pre_url}/studyLog.do"
    client = _build_client(cache)
    try:
        return client.post_form(
            url, form,
            headers={
                "User-Agent": _UA,
                "Accept": "*/*",
                "Cookie": _cookie_header(cache),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            retry=retry, use_multipart=False)
    finally:
        client.close()


def submit_study_time_api(cache: EnaeaUserCache, circle_id: str, video_id: str,
                          study_time: int, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """提交学时(普通模式) - 对齐Go SubmitStudyTimeApi

    :param study_time: 时间戳(毫秒)
    """
    form = {
        "id": video_id,
        "circleId": circle_id,
        "ct": str(study_time),
        "finish": "false",
    }
    return _submit_study_log(cache, form, retry=retry)


def submit_study_time_fast_api(cache: EnaeaUserCache, circle_id: str,
                               video_id: str, study_mins: int,
                               retry: int = 8) -> Tuple[str, Optional[Any]]:
    """提交学时(暴力模式/快速版) - 对齐Go SubmitStudyTimeFastApi

    :param study_mins: 一次性提交的学时(分钟), Go原版固定60
    """
    form = {
        "id": video_id,
        "circleId": circle_id,
        "ct": str(_now_ms()),
        "finish": "false",
        "studyMins": str(study_mins),
    }
    return _submit_study_log(cache, form, retry=retry)
