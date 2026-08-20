# -*- coding: utf-8 -*-
"""学习通 API 接口层 - 对应 Go 项目的 api/xuexitong/
完整重写：AES加密登录、移动端UA、正确的课程/章节/卡片/视频API
"""
from urllib.parse import quote as _url_quote
import json as _json
import uuid as _uuid_mod
import hashlib as _hashlib
import secrets
import hashlib
import re
import time
import math
import random
from typing import Tuple, Optional, Any, Dict, List
from urllib.parse import urlencode, quote, quote_plus

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad as aes_pad
import base64

from logic.core.http_client import HttpClient
from logic.xuexitong.models import XueXiTUserCache
from logic.core.models import safe_json_parse
import requests as _requests_lib
import uuid as _uuid_lib
import http.client as _http_client
import ssl as _ssl_lib
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============ 常量 ============

_AES_KEY = b"u2oh6Vu^HWe4_AES"
APP_VERSION = "6.7.2"
BUILD = "10941_314"
DEVICE_VENDOR = "MI10"
ANDROID_VERSION = "Android 16"

# 生成随机 IMEI（32位hex）
_IMEI = secrets.token_hex(16)


# ============ 辅助函数 ============

def _aes_encrypt(text: str) -> str:
    """AES-CBC 加密（PKCS7 pad → AES-CBC → base64），与 Go 原版一致"""
    cipher = AES.new(_AES_KEY, AES.MODE_CBC, _AES_KEY)
    padded = aes_pad(text.encode("utf-8"), AES.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode()


def _mobile_ua_sign(model: str, locale: str, version: str, build: str, imei: str) -> str:
    """计算移动端 UA 签名 (MD5)"""
    raw = " ".join([
        "(schild:ipL$TkeiEmfy1gTXb2XHrdLN0a@7c^vu)",
        f"(device:{model})",
        f"Language/{locale}",
        f"com.chaoxing.mobile/ChaoXingStudy_3_{version}_android_phone_{build}",
        f"(@Kalimdor)_{imei}",
    ])
    return hashlib.md5(raw.encode()).hexdigest()


def get_ua(ua_type: str = "mobile") -> str:
    """构建 User-Agent，对应 Go 的 GetUA()"""
    if ua_type == "mobile":
        sign = _mobile_ua_sign(DEVICE_VENDOR, "zh_CN",
                               APP_VERSION, BUILD, _IMEI)
        return " ".join([
            f"Mozilla/5.0 (Linux; {ANDROID_VERSION}; {DEVICE_VENDOR} Build/OPM1.171019.019; wv)",
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/71.0.3578.99 Mobile Safari/537.36",
            f"(schild:{sign})",
            f"(device:{DEVICE_VENDOR})",
            "Language/zh_CN",
            f"com.chaoxing.mobile/ChaoXingStudy_3_{APP_VERSION}_android_phone_{BUILD}",
            f"(@Kalimdor)_{_IMEI}",
        ])
    elif ua_type == "iphone":
        # 对应 Go GetUA("iphone") - 用于考试API的iPhone UA
        return "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
    elif ua_type == "web":
        return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 Edg/107.0.1418.35")
    return ""


# 专门用于考试API的UA - 对应 Go XXTEXAMUA
# 初始为mobile UA，遇到"访问异常"时切换为iphone UA
XXTEXAMUA: str = get_ua("mobile")


def _build_client(cache: XueXiTUserCache, ua: str = "mobile", custom_ua: str = "") -> HttpClient:
    """构建带学习通移动UA的HTTP客户端
    :param custom_ua: 如果提供，使用自定义UA字符串代替默认UA
    """
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    # 设置UA: custom_ua > get_ua(ua)
    client._ua = custom_ua if custom_ua else get_ua(ua)
    # 从 cache 恢复会话 Cookie
    if cache.cookie_dict:
        client.load_cookies(cache.cookie_dict)
    return client


# ============ PE模式Cookie白名单 (完全对齐Go CookiesFiltration) ============
_PE_COOKIE_WHITELIST = {
    "fid", "k8s", "route", "fanyamoocs", "_uid", "UID", "vc3",
    "uf", "cx_p_token", "p_auth_token", "xxtenc", "DSSTASH_LOG",
    "jrose", "thirdRegist", "videojs_id",
}


def _build_client_pe(cache: XueXiTUserCache, ua: str = "mobile") -> HttpClient:
    """构建PE模式客户端 - 只发送白名单Cookie (对齐Go的CookiesFiltration)
    Go PE API 使用 CookiesFiltration 过滤cookie，只发送白名单中的cookie，
    发送多余cookie可能导致403。
    """
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    client._ua = get_ua(ua)
    # 只加载白名单cookie (对齐Go的CookiesFiltration)
    if cache.cookie_dict:
        for name, value in list(cache.cookie_dict.items()):
            if name in _PE_COOKIE_WHITELIST:
                client.cookies.set(name, value)
    return client


def _build_client_with_ua(client: HttpClient) -> HttpClient:
    """给已构建的客户端附加 UA 到请求头"""
    return client


def _extract_cookies(client: HttpClient, cache: XueXiTUserCache):
    """从客户端提取 Cookie 并保存到 cache"""
    try:
        for name in list(client.cookies.keys()):
            try:
                value = client.cookies.get(name)
                if value:
                    cache.cookie_dict[name] = value
            except Exception:
                # CookieConflict - 多个同名 cookie，取第一个
                pass
    except Exception:
        pass


def _do_get(client: HttpClient, url: str, headers: Optional[Dict] = None,
            retry: int = 8) -> Tuple[str, Optional[Any]]:
    """GET 请求，自动附加学习通UA"""
    hdrs = {"User-Agent": client._ua}
    if headers:
        hdrs.update(headers)
    return client.get(url, headers=hdrs, retry=retry)


def _do_post_form(client: HttpClient, url: str, data,
                  headers: Optional[Dict] = None, retry: int = 8,
                  use_multipart: bool = False) -> Tuple[str, Optional[Any]]:
    """POST 表单请求，自动附加学习通UA"""
    hdrs = {"User-Agent": client._ua}
    if headers:
        hdrs.update(headers)
    return client.post_form(url, data, headers=hdrs, retry=retry,
                            use_multipart=use_multipart)


# ============ 登录 ============

def login_api(cache: XueXiTUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """密码登录 - AES 加密与 Go 原版一致"""
    url = "https://passport2.chaoxing.com/fanyalogin"
    phone_enc = _aes_encrypt(cache.account)
    pass_enc = _aes_encrypt(cache.password)
    data = {
        "fid": "-1",
        "uname": phone_enc,
        "password": pass_enc,
        "refer": "http%3A%2F%2Fi.mooc.chaoxing.com",
        "t": "true",
        "forbidotherlogin": "0",
        "validate": "",
        "doubleFactorLogin": "0",
        "independentId": "0",
        "independentNameId": "0",
    }
    client = _build_client(cache)
    try:
        body, resp = _do_post_form(client, url, data, retry=retry,
                                   use_multipart=False)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def cookie_login_set(cache: XueXiTUserCache):
    """Cookie 登录 - 直接设置 Cookie"""
    # 从 cookie 字符串解析并设置
    for part in cache.cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cache.cookie_dict[name.strip()] = value.strip()


# ============ 课程 ============

def course_list_api(cache: XueXiTUserCache, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取课程列表"""
    url = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata"
    client = _build_client(cache)
    try:
        body, resp = _do_get(client, url, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def course_complete_status_api(cache: XueXiTUserCache,
                               course_list_data: str,
                               retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取课程完成度状态 - 对应 Go 的 CourseCompleteStatusApi"""
    encoded = quote(course_list_data)
    url = (f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu-job-info"
           f"?clazzPersonStr={encoded}")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Host": "mooc2-ans.chaoxing.com",
            "X-Requested-With": "XMLHttpRequest",
        }
        return _do_get(client, url, headers=hdrs, retry=retry)
    finally:
        client.close()


# ============ 章节 ============

_CHAPTER_FIELDS = (
    "id,bbsid,classscore,isstart,allowdownload,chatid,name,state,isfiled,"
    "visiblescore,hideclazz,begindate,forbidintoclazz,"
    "coursesetting.fields(id,courseid,hiddencoursecover,coursefacecheck),"
    "course.fields(id,belongschoolid,name,infocontent,objectid,app,bulletformat,"
    "mappingcourseid,imageurl,teacherfactor,jobcount,"
    "knowledge.fields(id,name,indexOrder,parentnodeid,status,isReview,layer,label,"
    "jobcount,begintime,endtime,attachment.fields(id,type,objectid,extension).type(video)))"
)


def pull_chapter_api(cache: XueXiTUserCache, key: int, cpi: int,
                     retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取课程章节列表 - 对应 Go 的 PullChapter"""
    params = {
        "id": str(key),
        "personid": str(cpi),
        "fields": _CHAPTER_FIELDS,
        "view": "json",
    }
    url = "https://mooc1-api.chaoxing.com/gas/clazz?" + urlencode(params)
    client = _build_client(cache)
    try:
        body, resp = _do_get(client, url, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def fetch_chapter_point_status(cache: XueXiTUserCache,
                               nodes: List[int],
                               class_id: int, user_id: int,
                               cpi: int, course_id: int,
                               retry: int = 8) -> Tuple[str, Optional[Any]]:
    """获取章节节点完成状态 - 对应 Go 的 FetchChapterPointStatus"""
    url = "https://mooc1-api.chaoxing.com/job/myjobsnodesmap"
    ts = str(int(time.time() * 1000))
    data = {
        "view": "json",
        "nodes": ",".join(str(n) for n in nodes),
        "clazzid": str(class_id),
        "time": ts,
        "userid": str(user_id),
        "cpi": str(cpi),
        "courseid": str(course_id),
    }
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body, resp = _do_post_form(client, url, data, headers=hdrs,
                                   retry=retry, use_multipart=False)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ 卡片 / 任务点 ============

_KNOWLEDGE_FIELDS = (
    "id,parentnodeid,indexorder,label,layer,name,begintime,createtime,"
    "lastmodifytime,status,jobUnfinishedCount,clickcount,openlock,"
    "card.fields(id,knowledgeid,title,knowledgeTitile,description,cardorder)"
    ".contentcard(all)"
)


def fetch_chapter_cords(cache: XueXiTUserCache,
                        node_id: int, course_id: int,
                        retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取章节卡片资源 (API 1) - 对应 Go 的 FetchChapterCords
    返回 JSON，data[0].card.data 包含各卡片及其 description (iframe HTML)
    """
    params = {
        "id": str(node_id),
        "courseid": str(course_id),
        "fields": _KNOWLEDGE_FIELDS,
        "view": "json",
        "token": "4faa8662c59590c6f43ae9fe5b002b42",
        "_time": str(int(time.time() * 1000)),
    }
    url = "https://mooc1-api.chaoxing.com/gas/knowledge?" + urlencode(params)
    client = _build_client(cache)
    try:
        body, resp = _do_get(client, url, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def fetch_chapter_cords2(cache: XueXiTUserCache,
                         class_id: str, course_id: str,
                         knowledge_id: str, cpi: str,
                         retry: int = 8) -> Tuple[str, Optional[Any]]:
    """拉取章节卡片 HTML 页面 (API 2) - 对应 Go 的 FetchChapterCords2
    返回 HTML，需要用正则 mArg = ([^;]{6,}) 提取 JSON
    从中解析 attachments 数组获取视频参数
    """
    url = (f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"
           f"?clazzid={class_id}&courseid={course_id}"
           f"&knowledgeid={knowledge_id}&num=0&ut=s"
           f"&cpi={cpi}&v=2025-0424-1038-3&mooc2=1"
           f"&isMicroCourse=false&editorPreview=0")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def parse_marg_json(html_body: str) -> Optional[Dict]:
    """从 FetchChapterCords2 返回的 HTML 中提取 mArg JSON"""
    if not html_body:
        return None
    match = re.search(r'mArg\s*=\s*([^;]{6,})', html_body)
    if match:
        import json
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    return None


# ============ 视频 ============

def video_dto_fetch(cache: XueXiTUserCache, object_id: str, fid: str,
                    retry: int = 8) -> Tuple[str, Optional[Any]]:
    """预获取视频元数据 - 对应 Go 的 VideoDtoFetch
    返回 dtoken, duration 等
    """
    params = {
        "k": str(fid),
        "flag": "normal",
        "_dc": str(int(time.time() * 1000)),
    }
    url = f"https://mooc1-api.chaoxing.com/ananas/status/{object_id}?" + urlencode(
        params)
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://mooc1-api.chaoxing.com/ananas/modules/video/index_wap.html?v=372024-1121-1947",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def _compute_enc(class_id: str, user_id: str, job_id: str,
                 object_id: str, playing_time: int, duration: int) -> str:
    """计算视频提交 enc (MD5) - 与 Go 原版一致"""
    clip_time = f"0_{duration}"
    raw = (f"[{class_id}][{user_id}][{job_id}][{object_id}]"
           f"[{playing_time * 1000}][d_yHJ!$pdA~5][{duration * 1000}][{clip_time}]")
    return hashlib.md5(raw.encode()).hexdigest()


def video_submit_study_time_api(cache: XueXiTUserCache,
                                p,  # PointVideoDto
                                playing_time: int,
                                isdrag: int = 0,
                                retry: int = 8) -> Tuple[str, Optional[Any]]:
    """CP端视频学时提交 - 对应 Go 的 VideoSubmitStudyTimeApi
    URL: https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/<cpi>/<dtoken>
    """
    enc = _compute_enc(p.class_id, cache.user_id, p.job_id,
                       p.object_id, playing_time, p.duration)
    clip_time = f"0_{p.duration}"
    t_ms = str(int(time.time() * 1000))

    url = (
        f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/{p.cpi}/{p.dtoken}"
        f"?clazzId={p.class_id}"
        f"&playingTime={playing_time}"
        f"&duration={p.duration}"
        f"&clipTime={clip_time}"
        f"&objectId={p.object_id}"
        f"&otherInfo={p.other_info}"
        f"&courseId={p.course_id}"
        f"&jobid={p.job_id}"
        f"&userid={cache.user_id}"
        f"&isdrag={isdrag}"
        f"&view=pc"
        f"&enc={enc}"
        f"&rt={p.rt:.2f}"
        f"&videoFaceCaptureEnc={p.video_face_capture_enc}"
        f"&dtype=Video"
        f"&_t={t_ms}"
        f"&attDuration={p.duration}"
        f"&attDurationEnc={p.att_duration_enc}"
    )

    client = _build_client(cache)
    try:
        # 添加额外 cookie
        client.cookies.set("fanyamoocs", "11401F839C536D9E")
        client.cookies.set("thirdRegist", "0")
        client.cookies.set("videojs_id", "1778753")
        hdrs = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0"),
            "Accept": "*/*",
            "Host": "mooc1.chaoxing.com",
            "Content-Type": "application/json",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def audio_submit_api(cache: XueXiTUserCache,
                     p,  # PointVideoDto (audio uses same struct)
                     playing_time: int,
                     isdrag: int = 4,
                     retry: int = 8) -> Tuple[str, Optional[Any]]:
    """移动端音频学时提交 - 对应 Go 的 AudioPhoneSubmitTimeApi"""
    enc = _compute_enc(p.class_id, cache.user_id, p.job_id,
                       p.object_id, playing_time, p.duration)
    t_ms = str(int(time.time() * 1000))

    url = (
        f"https://mooc1-api.chaoxing.com/mooc-ans/multimedia/log"
        f"?objectId={p.object_id}"
        f"&clazzId={p.class_id}"
        f"&userid={cache.user_id}"
        f"&jobid={p.job_id}"
        f"&duration={p.duration}"
        f"&otherInfo={p.other_info}"
        f"&courseId={p.course_id}"
        f"&dtype=Audio"
        f"&view=json"
        f"&playingTime={playing_time}"
        f"&isdrag={isdrag}"
        f"&enc={enc}"
        f"&_dc={t_ms}"
    )

    client = _build_client(cache)
    try:
        hdrs = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "zh-CN,en-US;q=0.9",
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ 文档/外链/讨论 ============

def document_read_report_api(cache: XueXiTUserCache, job_id: str,
                             knowledge_id: str, course_id: str,
                             class_id: str, jtoken: str,
                             retry: int = 8) -> Tuple[str, Optional[Any]]:
    """文档任务点完成上报 - 对应 Go DocumentDtoReadingReport
    URL: https://mooc1.chaoxing.com/ananas/job/document
         ?jobid=...&knowledgeid=...&courseid=...&clazzid=...&jtoken=...&_dc=...
    注意: 旧实现调用 ananas/status/{objectid} 只返回status:true但不会被服务器
    计为任务点完成，导致课程进度卡住。此处完全对齐 Go。
    """
    dc = str(int(time.time() * 1000))
    url = (f"https://mooc1.chaoxing.com/ananas/job/document"
           f"?jobid={job_id}"
           f"&knowledgeid={knowledge_id}"
           f"&courseid={course_id}"
           f"&clazzid={class_id}"
           f"&jtoken={jtoken}"
           f"&_dc={dc}")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def document_book_report_api(cache: XueXiTUserCache, job_id: str,
                             knowledge_id: str, course_id: str,
                             class_id: str, jtoken: str,
                             retry: int = 8) -> Tuple[str, Optional[Any]]:
    """图书类型文档任务点上报 - 对应 Go DocumentDtoReadingBookReport
    URL: https://mooc1.chaoxing.com/ananas/job?jobid=...&...
    """
    dc = str(int(time.time() * 1000))
    url = (f"https://mooc1.chaoxing.com/ananas/job"
           f"?jobid={job_id}"
           f"&knowledgeid={knowledge_id}"
           f"&courseid={course_id}"
           f"&clazzid={class_id}"
           f"&jtoken={jtoken}"
           f"&_dc={dc}")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def document_readv2_report_api(cache: XueXiTUserCache, job_id: str,
                               knowledge_id: str, course_id: str,
                               class_id: str, jtoken: str,
                               retry: int = 8) -> Tuple[str, Optional[Any]]:
    """readv2类型文档任务点上报 - 对应 Go ReadV2PointPeReport
    URL: https://mooc1-api.chaoxing.com/ananas/job/readv2?jobid=...&...
    """
    dc = str(int(time.time() * 1000))
    url = (f"https://mooc1-api.chaoxing.com/ananas/job/readv2"
           f"?jobid={job_id}"
           f"&knowledgeid={knowledge_id}"
           f"&courseid={course_id}"
           f"&clazzid={class_id}"
           f"&jtoken={jtoken}"
           f"&checkMicroTopic=true&microTopicId=0&_dc={dc}")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "zh-CN,en-US;q=0.9",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def hyperlink_submit_api(cache: XueXiTUserCache, job_id: str,
                         knowledge_id: int, course_id: str,
                         class_id: str, jtoken: str,
                         retry: int = 8) -> Tuple[str, Optional[Any]]:
    """外链任务点提交 - 对应 Go HyperlinkDtoCompleteReport
    URL: https://mooc1.chaoxing.com/ananas/job/hyperlink?jobid=...&knowledgeid=...&courseid=...&clazzid=...&jtoken=...
    """
    import time as _time
    dc = str(int(_time.time() * 1000))
    url = (f"https://mooc1.chaoxing.com/ananas/job/hyperlink"
           f"?jobid={job_id}"
           f"&knowledgeid={knowledge_id}"
           f"&courseid={course_id}"
           f"&clazzid={class_id}"
           f"&jtoken={jtoken}"
           f"&checkMicroTopic=true"
           f"&microTopicId=undefined"
           f"&_dc={dc}")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1.chaoxing.com",
            "Connection": "keep-alive",
        }
        return _do_get(client, url, headers=hdrs, retry=retry)
    finally:
        client.close()


def bbs_submit_api(cache: XueXiTUserCache, topic_id: str,
                   course_id: str, class_id: str,
                   retry: int = 8) -> Tuple[str, Optional[Any]]:
    """讨论任务点提交"""
    url = (f"https://mooc1.chaoxing.com/bbscircle/grouptopic"
           f"?topicId={topic_id}&courseId={course_id}&classId={class_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


# ============ 章节前置调用 ============

def enter_chapter_forward_call_api(cache: XueXiTUserCache,
                                   course_id: str, class_id: str,
                                   chapter_id: str, cpi: str,
                                   retry: int = 8) -> Optional[Exception]:
    """进入章节前置调用 - 对应 Go 的 EnterChapterForwardCallApi
    零任务点章节需要调用此接口标记完成
    """
    url = (f"https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax"
           f"?courseId={course_id}&clazzid={class_id}"
           f"&chapterId={chapter_id}&cpi={cpi}"
           f"&verificationcode=&mooc2=1"
           f"&toComputer=false&microTopicId=0")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1.chaoxing.com",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        if resp and resp.status_code != 200:
            return Exception(f"status code: {resp.status_code}")
        return None
    except Exception as e:
        return e
    finally:
        client.close()


# ============ 章测/作业/考试 ============

def chapter_test_api(cache: XueXiTUserCache, course_id: str, class_id: str,
                     knowledge_id: str, retry: int = 8) -> Tuple[str, Optional[Any]]:
    url = (f"https://mooc1-api.chaoxing.com/work/getWork"
           f"?courseId={course_id}&classId={class_id}"
           f"&knowledgeId={knowledge_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


# ============ 移动端卡片 (PageMobileChapterCard) ============

def page_mobile_chapter_card_api(cache: XueXiTUserCache,
                                 class_id: int, course_id: int,
                                 knowledge_id: int, card_index: int,
                                 cpi: int,
                                 retry: int = 8) -> Tuple[str, Optional[Any]]:
    """移动端章节卡片API - 对应 Go 的 PageMobileChapterCard
    URL: https://mooc1-api.chaoxing.com/knowledge/cards
    参数含 isPhone=1&control=true
    返回 HTML，需提取 window.AttachmentSetting JSON 和 enc
    """
    params = {
        "clazzid": str(class_id),
        "courseid": str(course_id),
        "knowledgeid": str(knowledge_id),
        "num": str(card_index),
        "isPhone": "1",
        "control": "true",
        "cpi": str(cpi),
    }
    url = "https://mooc1-api.chaoxing.com/knowledge/cards?" + urlencode(params)
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def parse_attachment_setting(html_body: str) -> Tuple[Optional[Dict], str]:
    """从 PageMobileChapterCard HTML 中提取 window.AttachmentSetting JSON 和 enc
    返回 (attachment_dict, enc_string)
    """
    import json as _json
    if not html_body:
        return None, ""

    # 检查章节未开放
    if '章节未开放' in html_body:
        return None, ""

    # 检查验证码
    if '请输入验证码' in html_body or '请输入图片中的验证码' in html_body:
        return None, "CAPTCHA"

    # 检查人脸识别
    if 'title : "人脸识别"' in html_body:
        return None, "FACE"

    # 提取 window.AttachmentSetting JSON
    att_match = re.search(
        r'window\.AttachmentSetting\s*=\s*(\{.*?\});',
        html_body, re.DOTALL)
    if not att_match:
        # 尝试从 <script type="text/javascript"> 中提取
        script_match = re.search(
            r'<script\s+type="text/javascript">(.*?)</script>',
            html_body, re.DOTALL)
        if script_match:
            script_content = script_match.group(1)
            att_match = re.search(
                r'window\.AttachmentSetting\s*=\s*(\{.*?\});',
                script_content, re.DOTALL)

    attachment = None
    if att_match:
        try:
            attachment = _json.loads(att_match.group(1))
        except Exception:
            attachment = None

    # 提取 enc: <input type="hidden" id="from" value="xxx_yyy_zzz_ENC"/>
    enc = ""
    enc_match = re.search(
        r'<input\s+type="hidden"\s+id="from"\s+value="[^_]+_[^_]+_[^_]+_([^"]+)"/>',
        html_body)
    if enc_match:
        enc = enc_match.group(1)
        if attachment:
            attachment["enc"] = enc

    return attachment, enc


# ============ 视频提交 PE 模式 ============

def video_submit_study_time_pe_api(cache: XueXiTUserCache,
                                   p,  # PointVideoDto
                                   playing_time: int,
                                   isdrag: int = 0,
                                   retry: int = 8) -> Tuple[str, Optional[Any]]:
    """PE(移动端)模式视频学时提交 - 对应 Go 的 VideoSubmitStudyTimePEApi
    与 PC 端唯一区别: view=json + 移动端UA
    """
    enc = _compute_enc(p.class_id, cache.user_id, p.job_id,
                       p.object_id, playing_time, p.duration)
    clip_time = f"0_{p.duration}"
    t_ms = str(int(time.time() * 1000))

    url = (
        f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/{p.cpi}/{p.dtoken}"
        f"?clazzId={p.class_id}"
        f"&playingTime={playing_time}"
        f"&duration={p.duration}"
        f"&clipTime={clip_time}"
        f"&objectId={p.object_id}"
        f"&otherInfo={p.other_info}"
        f"&courseId={p.course_id}"
        f"&jobid={p.job_id}"
        f"&userid={cache.user_id}"
        f"&isdrag={isdrag}"
        f"&view=json"
        f"&enc={enc}"
        f"&rt={p.rt:.2f}"
        f"&videoFaceCaptureEnc={p.video_face_capture_enc}"
        f"&dtype=Video"
        f"&_t={t_ms}"
        f"&attDuration={p.duration}"
        f"&attDurationEnc={p.att_duration_enc}"
    )

    # PE模式：使用Cookie过滤的客户端(只发白名单Cookie，防止403)
    client = _build_client_pe(cache, ua="mobile")
    try:
        client.cookies.set("fanyamoocs", "11401F839C536D9E")
        client.cookies.set("thirdRegist", "0")
        client.cookies.set("videojs_id", "1778753")
        # 请求头完全对齐Go原版(无X-Requested-With)
        hdrs = {
            "Accept": "*/*",
            "Host": "mooc1.chaoxing.com",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "Sec-Ch-Ua-Platform": "Windows",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Pragma": "no-cache",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ iframe 解析 ============

# 实现已移至轻量模块 logic/core/parse_utils.py（供进程池子进程调用，
# 避免 Windows spawn 时子进程加载本模块的重依赖），此处保持兼容导出
from logic.core.parse_utils import parse_iframe_data  # noqa: E402,F401


# ============ 重登录 ============

def relogin(cache: XueXiTUserCache) -> Optional[Exception]:
    """重新登录 - 对应 Go 的 ReLogin
    清空cookies → 重新登录 → 拉取课程列表获取新Cookie
    """
    if cache.is_cookie_login:
        return None  # Cookie 登录无法重登
    # 清空cookies
    cache.cookie_dict.clear()
    body, _ = login_api(cache, retry=3)
    if not body:
        return Exception("重登录响应为空")
    import json
    try:
        data = json.loads(body)
        if data.get("status") is True:
            # 拉取课程列表以获取最新cookies
            course_list_api(cache, retry=3)
            return None
    except Exception:
        pass
    return Exception("重登录失败")


# ============ 人脸识别 API - 完全对齐 Go XueXiTongFaceApi.go ============

def _html_input_value_get(html: str, elem_id: str) -> str:
    """从HTML中提取指定id的input的value - 对齐 Go goquery doc.Find(#id).Attr("value")"""
    if not html:
        return ""
    m = re.search(r'id=["\']' + re.escape(elem_id) +
                  r'["\'][^>]*value=["\']([^"\']*)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'value=["\']([^"\']*)["\'][^>]*id=["\']' +
                      re.escape(elem_id) + r'["\']', html, re.IGNORECASE)
    return m.group(1) if m else ""


def get_history_face_img(cache: XueXiTUserCache,
                         retry: int = 3) -> Tuple[Optional[bytes], Optional[Exception]]:
    """获取历史人脸图片 - 对齐新版APP api/getUserFaceid
    URL: https://passport2-api.chaoxing.com/api/getUserFaceid
         ?enc=md5(uid+"uWwjeEKsri")&token=4faa8662c59590c6f43ae9fe5b002b42&_time=...
    响应 {"result":1,"data":{"http":"历史照片URL","objectid":"历史基准id"}}
    result==1 时从 data.http 下载历史人脸图片
    返回: (图片bytes, 错误)
    """
    uid = cache.uid or cache.cookie_dict.get(
        "UID", cache.cookie_dict.get("_uid", ""))
    if not uid:
        return None, Exception("未获取到uid，无法拉取历史人脸")
    enc = _hashlib.md5((uid + "uWwjeEKsri").encode("utf-8")).hexdigest()
    url = (f"https://passport2-api.chaoxing.com/api/getUserFaceid"
           f"?enc={enc}&token=4faa8662c59590c6f43ae9fe5b002b42"
           f"&_time={int(time.time())}")
    client = _build_client(cache)
    try:
        body, _ = _do_get(client, url, retry=retry)
        data = safe_json_parse(body) if body else None
        if not data or str(data.get("result")) != "1":
            return None, Exception("没有历史人脸")
        d = data.get("data")
        face_url = d.get("http", "") if isinstance(d, dict) else ""
        if not face_url:
            return None, Exception("没有历史人脸")
        img_bytes, _ = client.get_image(face_url, retry=3)
        if not img_bytes:
            return None, Exception("历史人脸图片下载失败")
        return img_bytes, None
    finally:
        client.close()


def change_faceid_api(cache: XueXiTUserCache, object_id: str,
                      retry: int = 3) -> Tuple[str, Optional[Any]]:
    """更换服务器基准FaceId - 对齐新版APP api/changefaceid
    GET https://passport2-api.chaoxing.com/api/changefaceid?objectid={上传照片的objectId}
    上传照片后调用此接口，将人脸比对基准换成刚上传的照片
    (新版APP过人脸的核心: 先换基准再比对，绕过历史基准照片)
    响应 {"result":1,"errorMsg":""} 即成功
    """
    url = (f"https://passport2-api.chaoxing.com/api/changefaceid"
           f"?objectid={object_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def get_face_upload_token(cache: XueXiTUserCache,
                          retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取人脸上传token - 对齐 Go GetFaceUpLoadToken
    URL: https://pan-yz.chaoxing.com/api/token/uservalid
    返回原始响应体(调用方解析 _token)
    """
    url = "https://pan-yz.chaoxing.com/api/token/uservalid"
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def get_face_qr_code_api3(cache: XueXiTUserCache, course_id: str,
                          class_id: str, knowledge_id: str,
                          cpi: str = "", enc: str = "", job_id: str = "",
                          object_id: str = "", retry: int = 3
                          ) -> Tuple[str, str]:
    """获取人脸QR必要数据 - 对齐 Go GetFaceQrCodeApi3(两步)
    ① mooc-ans/mycourse/studentstudy 解析 uuid/qrcEnc(视频取videouuid/videoqrcEnc)
    ② mooc-ans/qr/produce 用 uuid+qrcEnc 换 newUuid/newEnc
    返回: (new_uuid, new_enc)
    """
    url1 = (f"https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudy"
            f"?chapterId={knowledge_id}&courseId={course_id}"
            f"&clazzid={class_id}&enc={enc}")
    client = _build_client(cache)
    try:
        body1, _ = _do_get(client, url1, retry=retry)
        if not body1:
            return "", ""
        uuid_val = _html_input_value_get(body1, "uuid")
        qrc_enc = _html_input_value_get(body1, "qrcEnc")
        if not uuid_val:
            uuid_val = _html_input_value_get(body1, "videouuid")
        if not qrc_enc:
            qrc_enc = _html_input_value_get(body1, "videoqrcEnc")
        if not uuid_val or not qrc_enc:
            return "", ""
        url2 = (f"https://mooc1.chaoxing.com/mooc-ans/qr/produce"
                f"?uuid={uuid_val}&enc={qrc_enc}&clazzid={class_id}"
                f"&videojobid={job_id}&chaptervideoobjectid={object_id}"
                f"&videoCollectTime=0")
        body2, _ = _do_get(client, url2, retry=retry)
        data = safe_json_parse(body2) if body2 else None
        if not data or data.get("status") is not True:
            return "", ""
        return str(data.get("newUuid", "")), str(data.get("newEnc", ""))
    finally:
        client.close()


def upload_face_image_api(cache: XueXiTUserCache, token: str,
                          image_data: bytes,
                          retry: int = 3) -> Tuple[str, Optional[Any]]:
    """上传人脸图片 - 对齐 Go UploadFaceImageApi
    POST https://pan-yz.chaoxing.com/upload
    multipart字段: uploadtype=face, _token=token, puid=uid, file={时间戳}.jpg
    响应 result==true 时由调用方取 objectId
    """
    uid = cache.uid or cache.cookie_dict.get(
        "UID", cache.cookie_dict.get("_uid", ""))
    url = "https://pan-yz.chaoxing.com/upload"
    client = _build_client(cache)
    try:
        hdrs = {"User-Agent": client._ua}
        data = {"uploadtype": "face", "_token": token, "puid": uid}
        files = {"file": (
            f"{int(time.time() * 1000)}.jpg", image_data, "image/jpeg")}
        body, resp = client.request("POST", url, data=data, headers=hdrs,
                                    files=files, retry=retry,
                                    use_multipart=True)
        return body, resp
    finally:
        client.close()


def pass_face_qr_plan_phone_new_api(cache: XueXiTUserCache, class_id: str,
                                    course_id: str, knowledge_id: str,
                                    cpi: str, object_id: str,
                                    retry: int = 3) -> Tuple[str, Optional[Any]]:
    """手机端过人脸(新接口) - 对齐 Go PassFaceQrPlanPhoneNewApi
    GET https://mooc1-api.chaoxing.com/mooc-ans/facephoto/clientfacecheckstatus
    """
    url = (f"https://mooc1-api.chaoxing.com/mooc-ans/facephoto/clientfacecheckstatus"
           f"?courseId={course_id}&clazzId={class_id}&cpi={cpi}"
           f"&chapterId={knowledge_id}&objectId={object_id}"
           f"&liveDetectionStatus=1&signt=&signk=&cxtime=&cxcid=&type=1")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def pass_face_qr_plan_phone_old_api(cache: XueXiTUserCache, class_id: str,
                                    course_id: str, knowledge_id: str,
                                    object_id: str,
                                    retry: int = 3) -> Tuple[str, Optional[Any]]:
    """手机端过人脸(老接口) - 对齐 Go PassFaceQrPlanPhoneOldApi
    POST https://mooc1-api.chaoxing.com/mooc-ans/knowledge/uploadInfo
    """
    url = "https://mooc1-api.chaoxing.com/mooc-ans/knowledge/uploadInfo"
    data = {
        "clazzId": class_id,
        "courseId": course_id,
        "knowledgeId": knowledge_id,
        "uuid": "",
        "qrcEnc": "",
        "objectId": object_id,
    }
    client = _build_client(cache)
    try:
        return _do_post_form(client, url, data, retry=retry)
    finally:
        client.close()


def get_course_face_qr_plan3_api(cache: XueXiTUserCache, class_id: str,
                                 course_id: str, uuid: str, qrc_enc: str,
                                 cpi: str, object_id: str,
                                 retry: int = 3) -> Tuple[str, Optional[Any]]:
    """PC端过人脸 - 对齐 Go GetCourseFaceQrPlan3Api
    POST https://mooc1-api.chaoxing.com/qr/updateqrstatus?uuid2=..&clazzId2=..
    """
    url = (f"https://mooc1-api.chaoxing.com/qr/updateqrstatus"
           f"?uuid2={uuid}&clazzId2={class_id}")
    payload = (f"clazzId={class_id}&courseId={course_id}&uuid={uuid}"
               f"&qrcEnc={qrc_enc}&cpi={cpi}&liveDetectionStatus=0"
               f"&signt=&signk=&cxtime=&cxcid=&knowledgeid=0"
               f"&objectId={object_id}&videojobid=&videoCollectTime=0"
               f"&chaptervideoobjectid=")
    client = _build_client(cache)
    try:
        return _do_post_form(client, url, payload, retry=retry)
    finally:
        client.close()


def get_course_face_qr_state_api(cache: XueXiTUserCache, uuid: str, enc: str,
                                 class_id: str, course_id: str, cpi: str,
                                 mid: str = "", object_id: str = "",
                                 random_capture_time: str = "",
                                 knowledge_id: str = "",
                                 retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取人脸状态 - 对齐 Go GetCourseFaceQrStateApi
    GET https://mooc1.chaoxing.com/mooc-ans/qr/getqrstatus
    """
    url = (f"https://mooc1.chaoxing.com/mooc-ans/qr/getqrstatus"
           f"?uuid={uuid}&enc={enc}&clazzid={class_id}&courseid={course_id}"
           f"&cpi={cpi}&collectionTime=0&mid={mid}&videoObjectId={object_id}"
           f"&videoRandomCollectTime={random_capture_time}"
           f"&chapterId={knowledge_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def _face_image_rgb_disturb(image_data: bytes) -> bytes:
    """人脸图片RGB LSB像素扰动 - 对齐 Go utils.ImageRGBDisturb
    每个像素RGB的最低bit随机化，避免服务器识别出与历史照片完全一致
    """
    import io as _io
    from PIL import Image
    img = Image.open(_io.BytesIO(image_data)).convert("RGB")
    # 构建256项随机LSB查找表(对齐 Go 逐像素 r8=(r8&0xFE)|rand(0,1))
    table = [(i & 0xFE) | random.randint(0, 1) for i in range(256)]
    out = img.point(table * 3)  # RGB三通道共用一张表
    buf = _io.BytesIO()
    out.save(buf, format="JPEG")
    return buf.getvalue()


def _face_load_image(cache: XueXiTUserCache):
    """拉取人脸图片: 本地缓存优先(./assets/faces/{account}.jpg)，否则拉历史人脸 - 对齐 Go PassFacePhoneAction"""
    import os as _os
    local_path = f"./assets/faces/{cache.account}.jpg"
    if _os.path.exists(local_path):
        try:
            with open(local_path, "rb") as f:
                return f.read(), None
        except Exception:
            pass
    return get_history_face_img(cache)


def pass_face_phone_action(cache: XueXiTUserCache, course_id: str,
                           class_id: str, cpi: str,
                           knowledge_id: str) -> Optional[Exception]:
    """手机端过人脸 - 对齐 Go PassFacePhoneAction + XueXiTongCardAction 重试/回退
    流程: 历史人脸(或本地图片) → RGB扰动 → 上传token → 上传人脸 →
          clientfacecheckstatus 验证
    失败("用户图片信息出错")最多重试8次; 仍失败回退老接口 uploadInfo
    """

    def _one_try() -> Optional[Exception]:
        face_img, err = _face_load_image(cache)
        if err:
            return err
        disturb_img = _face_image_rgb_disturb(face_img)

        token_body, _ = get_face_upload_token(cache)
        token_data = safe_json_parse(token_body) if token_body else None
        token = token_data.get("_token", "") if token_data else ""
        if not token:
            return Exception("获取上传token失败")

        time.sleep(1)  # 对齐 Go: 隔一下
        upload_body, _ = upload_face_image_api(cache, token, disturb_img)
        upload_data = safe_json_parse(upload_body) if upload_body else None
        if not upload_data or upload_data.get("result") is not True:
            return Exception("上传人脸失败")
        object_id = str(upload_data.get("objectId", ""))
        if not object_id:
            return Exception("ObjectId为空")

        time.sleep(1)
        # 更换基准FaceId为新上传的照片 - 对齐新版APP api/changefaceid
        # (先换基准再比对，绕过历史基准照片限制)
        change_body, _ = change_faceid_api(cache, object_id)
        change_data = safe_json_parse(change_body) if change_body else None
        if not change_data or str(change_data.get("result")) != "1":
            return Exception(f"更换基准FaceId失败: {(change_body or '')[:200]}")

        time.sleep(1)  # 对齐 Go: 隔一下
        plan_body, _ = pass_face_qr_plan_phone_new_api(
            cache, class_id, course_id, knowledge_id, cpi, object_id)
        plan_str = plan_body or ""
        if "活体检测不通过" in plan_str:
            return Exception("活体检测不通过")
        if "用户图片信息出错" in plan_str:
            return Exception("用户图片信息出错")
        pass_data = safe_json_parse(plan_str)
        msg = pass_data.get("msg") if pass_data else None
        if msg is not None and msg not in ("通过", "识别通过"):
            return Exception(f"人脸验证失败: {plan_str[:200]}")
        return None

    err = _one_try()
    # "用户图片信息出错" 重试机制 - 对齐 Go for i <= 8
    for _ in range(8):
        if err and "用户图片信息出错" in str(err):
            time.sleep(1)
            err = _one_try()
        else:
            break
    # 新接口彻底失败 → 回退老接口 uploadInfo - 对齐 Go PassFacePhoneOldAction
    if err and "用户图片信息出错" in str(err):
        # 老接口需要先上传拿到objectId(与Go一致: 重新拉图上传)
        try:
            face_img, err2 = _face_load_image(cache)
            if err2:
                return err2
            disturb_img = _face_image_rgb_disturb(face_img)
            token_body, _ = get_face_upload_token(cache)
            token_data = safe_json_parse(token_body) if token_body else None
            token = token_data.get("_token", "") if token_data else ""
            if not token:
                return Exception("获取上传token失败")
            upload_body, _ = upload_face_image_api(cache, token, disturb_img)
            upload_data = safe_json_parse(upload_body) if upload_body else None
            if not upload_data or upload_data.get("result") is not True:
                return Exception("上传人脸失败")
            object_id = str(upload_data.get("objectId", ""))
            if not object_id:
                return Exception("ObjectId为空")
            # 更换基准FaceId - 对齐新版APP api/changefaceid
            change_body, _ = change_faceid_api(cache, object_id)
            change_data = safe_json_parse(change_body) if change_body else None
            if not change_data or str(change_data.get("result")) != "1":
                return Exception(f"更换基准FaceId失败: {(change_body or '')[:200]}")
            old_body, _ = pass_face_qr_plan_phone_old_api(
                cache, class_id, course_id, knowledge_id, object_id)
            old_str = old_body or ""
            if "活体检测不通过" in old_str:
                return Exception("活体检测不通过")
            old_data = safe_json_parse(old_str)
            msg = old_data.get("msg") if old_data else None
            if msg is not None and msg not in ("通过", "识别通过"):
                return Exception(f"老接口人脸验证失败: {old_str[:200]}")
            err = None
        except Exception as e:
            return Exception(f"老接口人脸验证异常: {e}")
    return err


def pass_face_pc_action(cache: XueXiTUserCache,
                        course_id: str, class_id: str, cpi: str,
                        knowledge_id: str, enc: str, job_id: str,
                        object_id: str, mid: str,
                        random_capture_time: str) -> Optional[Exception]:
    """PC端人脸绕过流程 - 对应 Go PassFacePCAction(视频403触发)
    流程: 历史人脸(本地优先) → GetFaceQrCodeApi3(两步) → GetFaceUpLoadToken →
          UploadFaceImage → changefaceid换基准 → GetCourseFaceQrPlan3(updateqrstatus) →
          GetCourseFaceQrState(getqrstatus)
    """
    # 1. 获取历史人脸(本地照片优先) + RGB扰动
    face_img, err = _face_load_image(cache)
    if err:
        return err
    disturb_img = _face_image_rgb_disturb(face_img)

    # 2. 获取人脸QR必要数据(uuid/qrcEnc) - 两步
    uuid_val, qrc_enc = get_face_qr_code_api3(
        cache, course_id, class_id, knowledge_id, cpi=cpi,
        enc=enc, job_id=job_id, object_id=object_id)
    if not uuid_val or not qrc_enc:
        return Exception("uuid或qrEnc为空")

    # 3. 获取上传token
    token_body, _ = get_face_upload_token(cache)
    token_data = safe_json_parse(token_body) if token_body else None
    token = token_data.get("_token", "") if token_data else ""
    if not token:
        return Exception("获取上传token失败")

    # 4. 上传人脸图片
    upload_body, _ = upload_face_image_api(cache, token, disturb_img)
    upload_data = safe_json_parse(upload_body) if upload_body else None
    if not upload_data or upload_data.get("result") is not True:
        return Exception("上传人脸失败")
    new_object_id = str(upload_data.get("objectId", ""))
    if not new_object_id:
        return Exception("ObjectId为空")

    # 更换基准FaceId为新上传的照片 - 对齐新版APP api/changefaceid
    change_body, _ = change_faceid_api(cache, new_object_id)
    change_data = safe_json_parse(change_body) if change_body else None
    if not change_data or str(change_data.get("result")) != "1":
        return Exception(f"更换基准FaceId失败: {(change_body or '')[:200]}")

    # 5. 过人脸(PC端 updateqrstatus)
    plan_body, _ = get_course_face_qr_plan3_api(
        cache, class_id, course_id, uuid_val, qrc_enc, cpi, new_object_id)
    plan_data = safe_json_parse(plan_body) if plan_body else None
    msg = plan_data.get("msg") if plan_data else None
    if msg is not None and msg != "通过":
        return Exception(f"人脸验证失败: {(plan_body or '')[:200]}")

    # 6. 检查状态
    state_body, _ = get_course_face_qr_state_api(
        cache, uuid_val, qrc_enc, class_id, course_id, cpi,
        mid=mid, object_id=job_id, random_capture_time=random_capture_time,
        knowledge_id=knowledge_id)
    state_data = safe_json_parse(state_body) if state_body else None
    if state_data and state_data.get("status") == 2:
        return None  # 人脸验证成功

    return None  # 状态未知时也视为成功(对齐Go: 状态接口仅记录)


# ============ 验证码 API ============

def verification_code_api(cache: XueXiTUserCache, t: int = 7,
                          retry: int = 3) -> Tuple[Optional[bytes], Optional[Exception]]:
    """获取验证码图片 - 对应 Go XueXiTVerificationCodeApi
    返回图片字节数据
    """
    url = f"https://passport2.chaoxing.com/processVerifyCode?t={t}&_dc={int(time.time()*1000)}"
    client = _build_client(cache)
    try:
        hdrs = {"User-Agent": client._ua}
        body, resp = client.get(url, headers=hdrs, retry=retry)
        if resp and resp.status_code == 200:
            return resp.content if hasattr(resp, 'content') else body.encode() if body else None, None
        return None, Exception(f"获取验证码失败 status={resp.status_code if resp else 'N/A'}")
    finally:
        client.close()


def pass_verification_code_api(cache: XueXiTUserCache, code: str,
                               t: int = 7,
                               retry: int = 3) -> Tuple[bool, Optional[Exception]]:
    """提交验证码 - 对应 Go XueXiTPassVerificationCode"""
    url = "https://passport2.chaoxing.com/validateVerificationCode"
    data = {"code": code, "t": str(t)}
    client = _build_client(cache)
    try:
        body, resp = _do_post_form(client, url, data, retry=retry)
        resp_data = safe_json_parse(body) if body else None
        if resp_data and resp_data.get("status") is True:
            return True, None
        return False, Exception(f"验证码错误: {body}")
    finally:
        client.close()


# ============ 章测/作业/考试 API ============

def work_fetch_question_api(cache: XueXiTUserCache, work_point,
                            retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取章测/作业题目页面 - 对应 Go WorkFetchQuestion
    URL: https://mooc1-api.chaoxing.com/android/mworkspecial
    Headers: Host: mooc1-api.chaoxing.com, Accept: */*, Connection: keep-alive
    """
    school_id = work_point.school_id or "0"
    workid_val = f"{school_id}-{work_point.work_id}" if school_id != "0" else work_point.work_id
    params = {
        "courseid": work_point.course_id,
        "workid": workid_val,
        "jobid": work_point.job_id,
        "needRedirect": "true",
        "knowledgeid": str(work_point.knowledge_id),
        "userid": work_point.puid,
        "ut": "s",
        "clazzId": work_point.class_id,
        "cpi": work_point.cpi,
        "ktoken": work_point.k_token,
        "enc": work_point.enc,
    }
    url = "https://mooc1-api.chaoxing.com/android/mworkspecial?" + \
        "&".join(f"{k}={v}" for k, v in params.items())
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        if body and "无效的权限,code=2" in body:
            # Fallback: WorkFetch2Question
            return work_fetch2_question_api(cache, work_point, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def work_fetch2_question_api(cache: XueXiTUserCache, work_point,
                             retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取章测题目(Fallback) - 对应 Go WorkFetch2Question
    URL: https://mooc1-api.chaoxing.com/mooc-ans/work/phone/work
    """
    params = {
        "workId": work_point.work_id,
        "courseId": work_point.course_id,
        "clazzId": work_point.class_id,
        "knowledgeId": str(work_point.knowledge_id),
        "jobId": "",
        "enc": work_point.enc,
        "cpi": work_point.cpi,
        "originJobId": work_point.job_id,
    }
    url = "https://mooc1-api.chaoxing.com/mooc-ans/work/phone/work?" + \
        "&".join(f"{k}={v}" for k, v in params.items())
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def work_new_submit_answer_api(cache: XueXiTUserCache,
                               course_id: str, class_id: str,
                               knowledge_id: str, work_id: str,
                               answer_data: Dict,
                               retry: int = 3) -> Tuple[str, Optional[Any]]:
    """提交章测/作业答案 - 对应 Go WorkNewSubmitAnswer
    URL: https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew
    *** 使用http.client标准库发送,完全控制HTTP请求的每个细节 ***
    不使用requests/httpx,避免任何自动header注入或body编码
    """
    enc_work = answer_data.get("enc_work", "")
    total_q = answer_data.get("totalQuestionNum", "")
    path = (f"/mooc-ans/work/addStudentWorkNew"
            f"?_classId={class_id}&courseid={course_id}"
            f"&token={enc_work}&totalQuestionNum={total_q}"
            f"&ua=pc&formType=post&saveStatus=1&version=1&tempsave=1")

    # 获取mobile UA (与Go一致)
    mobile_ua = get_ua("mobile")

    # 手动构建multipart body (与Go multipart.Writer完全一致)
    boundary = _uuid_lib.uuid4().hex
    lines: list = []
    items = list(answer_data.items()) if isinstance(
        answer_data, dict) else list(answer_data)
    for k, v in items:
        lines.append(f"--{boundary}")
        lines.append(f'Content-Disposition: form-data; name="{k}"')
        lines.append("")
        lines.append(str(v))
    lines.append(f"--{boundary}--")
    lines.append("")
    body = "\r\n".join(lines).encode()

    # 构建Cookie字符串
    cookie_str = "; ".join(
        f"{k}={v}" for k, v in list(cache.cookie_dict.items()))

    # 请求头 - 完全对齐Go multipart.Writer.FormDataContentType()
    # Go标准库 FormDataContentType() = "multipart/form-data; boundary=xxx" (不含charset!)
    # 关键: 不要在hdrs中放Host header! Python http.client.putrequest()自动添加Host,
    # 如果hdrs中也有Host,会产生重复的Host header(违反HTTP协议),导致服务器返回code-2
    # Go的net/http会自动过滤掉header中的Host,只使用req.Host,所以Go没有这个问题
    hdrs = {
        "User-Agent": mobile_ua,
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
        "Cookie": cookie_str,
    }

    # 使用http.client发送
    body_text = ""
    resp_status = 0
    resp_headers = {}
    ctx = _ssl_lib.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl_lib.CERT_NONE

    for attempt in range(max(1, retry)):
        try:
            conn = _http_client.HTTPSConnection(
                "mooc1.chaoxing.com", 443, timeout=30, context=ctx)
            conn.request("POST", path, body=body, headers=hdrs)
            resp = conn.getresponse()
            resp_status = resp.status
            resp_headers = dict(resp.getheaders())
            raw_body = resp.read()
            body_text = raw_body.decode("utf-8", errors="replace")
            conn.close()

            # 提取Set-Cookie到cache
            for hdr_name, hdr_val in resp.getheaders():
                if hdr_name.lower() == "set-cookie":
                    # 简单解析cookie: name=value
                    parts = hdr_val.split(";")[0].strip()
                    if "=" in parts:
                        cname, cval = parts.split("=", 1)
                        cache.cookie_dict[cname.strip()] = cval.strip()

            if "502 Bad Gateway" in body_text or "504 Gateway Time-out" in body_text:
                time.sleep(0.3)
                continue
            break
        except Exception as e:
            body_text = f'{{"error":"{str(e)}"}}'
            time.sleep(0.3)

    # 构建SimpleResp对象
    class SimpleResp:
        def __init__(self, status, headers):
            self.status_code = status
            self.headers = headers
    return body_text, SimpleResp(resp_status, resp_headers)


# ============ 直播 API ============

def pull_live_info_api(cache: XueXiTUserCache, live_id: str,
                       course_id: str, class_id: str,
                       retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取直播信息 - 对应 Go PullLiveInfo"""
    url = (f"https://mooc1.chaoxing.com/live/getLiveInfo"
           f"?liveId={live_id}&courseId={course_id}&classId={class_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def live_create_relation_api(cache: XueXiTUserCache,
                             live_id: str, course_id: str,
                             class_id: str, knowledge_id: str,
                             retry: int = 3) -> Tuple[str, Optional[Any]]:
    """建立直播联系 - 对应 Go LiveCreateRelation"""
    url = (f"https://mooc1.chaoxing.com/live/createRelation"
           f"?liveId={live_id}&courseId={course_id}"
           f"&classId={class_id}&knowledgeId={knowledge_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


# ============ 讨论(BBS) API - 对齐Go XueXiTongBBsApi.go ============


_BBS_TOKEN = "4faa8662c59590c6f43ae9fe5b002b42"
_DES_KEY = "Z(AfY@XS"


def _inf_enc_sign(params: dict, order: list) -> str:
    """移动端inf_enc签名 - 对齐Go InfEncSign"""
    parts = []
    for k in order:
        v = params.get(k)
        if v is None:
            continue
        parts.append(f"{k}={_url_quote(str(v), safe='')}")
    query = "&".join(parts) + f"&DESKey={_DES_KEY}"
    return _hashlib.md5(query.encode()).hexdigest()


def _param_c_0() -> str:
    """移动端_c_0参数生成 - 对齐Go ParamFor_c_0_Generete"""
    return str(_uuid_mod.uuid4()).replace("-", "")


def pull_phone_bbs_info_api(cache: XueXiTUserCache,
                            mid: str, job_id: str,
                            knowledge_id: int, course_id: str,
                            class_id: str,
                            retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取讨论章节页面HTML - 对齐Go PullPhoneBbsInfoApi
    返回HTML, 需要从中提取groupId/bbsId/topicId/classId/courseId等"""
    url = (f"https://mooc1-api.chaoxing.com/mooc-ans/bbscircle/chapter"
           f"?mtopicid={mid}"
           f"&jobid={job_id}"
           f"&isPortal=false"
           f"&knowledgeid={knowledge_id}"
           f"&ut=s"
           f"&clazzId={class_id}"
           f"&enc"
           f"&utenc=undefined"
           f"&courseid={course_id}"
           f"&isJob=true"
           f"&isMobile=true")
    client = _build_client(cache)
    try:
        hdrs = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Accept-Language": "zh-CN,en-US;q=0.9",
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        return _do_get(client, url, headers=hdrs, retry=retry)
    finally:
        client.close()


def pull_phone_bbs_detail_api(cache: XueXiTUserCache,
                              topic_id: str,
                              retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取讨论主题详细信息JSON - 对齐Go PullPhoneBbsDetailApi
    返回JSON: {"data": {"title": ..., "text_content": ..., "uuid": ...}}"""
    c_0 = _param_c_0()
    t = str(int(__import__('time').time() * 1000))
    puid = cache.cookie_dict.get("UID", "")
    inf_enc = _inf_enc_sign(
        {"_c_0_": c_0, "token": _BBS_TOKEN, "_time": t},
        ["_c_0_", "token", "_time"])
    url = (f"https://groupyd.chaoxing.com/apis/topic/getTopic"
           f"?_c_0_={c_0}"
           f"&token={_BBS_TOKEN}"
           f"&_time={t}"
           f"&inf_enc={inf_enc}")
    client = _build_client(cache)
    try:
        hdrs = {
            "Connection": "Keep-Alive",
            "Accept-Language": "zh_CN",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Host": "groupyd.chaoxing.com",
        }
        body, _resp = client.post_form(
            url, f"puid={puid}&maxW=1080&topicId={topic_id}",
            headers={"User-Agent": client._ua, **hdrs}, retry=retry,
            use_multipart=False)
        return body, None
    finally:
        client.close()


def answer_phone_bbs_api(cache: XueXiTUserCache,
                         class_id: str, topic_uuid: str,
                         content: str,
                         retry: int = 3) -> Tuple[str, Optional[Any]]:
    """手机端回复讨论 - 对齐Go AnswerPhoneBbsApi"""
    c_0 = _param_c_0()
    t = str(int(__import__('time').time() * 1000))
    puid = cache.cookie_dict.get("UID", "")
    new_uuid = str(_uuid_mod.uuid4())
    inf_enc = _inf_enc_sign(
        {"token": _BBS_TOKEN, "_time": t, "_c_0_": c_0,
         "puid": puid, "uuid": new_uuid,
         "tag": f"classId{class_id}", "maxW": "1080",
         "topicUUID": topic_uuid, "anonymous": "0"},
        ["token", "_time", "_c_0_", "puid", "uuid",
         "tag", "maxW", "topicUUID", "anonymous"])
    url = (f"https://groupyd.chaoxing.com/apis/invitation/addReply"
           f"?token={_BBS_TOKEN}"
           f"&_time={t}"
           f"&_c_0_={c_0}"
           f"&puid={puid}"
           f"&uuid={new_uuid}"
           f"&tag=classId{class_id}"
           f"&maxW=1080"
           f"&topicUUID={topic_uuid}"
           f"&anonymous=0"
           f"&inf_enc={inf_enc}")
    client = _build_client(cache)
    try:
        from urllib.parse import quote as _q
        payload = f"content={_q(content, safe='')}"
        hdrs = {
            "Connection": "Keep-Alive",
            "Accept-Language": "zh_CN",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Host": "groupyd.chaoxing.com",
        }
        body, _resp = client.post_form(
            url, payload,
            headers={"User-Agent": client._ua, **hdrs}, retry=retry,
            use_multipart=False)
        return body, None
    finally:
        client.close()


# ============ 直播提交 API ============

def live_submit_api(cache: XueXiTUserCache,
                    live_id: str, course_id: str,
                    class_id: str, knowledge_id: str,
                    vdoid: str, stream_name: str,
                    aid: str, playing_time: int = 30,
                    retry: int = 3) -> Tuple[str, Optional[Any]]:
    """提交直播学习进度 - 对应 Go point.ExecuteLive"""
    url = (f"https://mooc1.chaoxing.com/live/submitLiveProgress"
           f"?liveId={live_id}&courseId={course_id}"
           f"&classId={class_id}&knowledgeId={knowledge_id}"
           f"&vdoid={vdoid}&streamName={stream_name}"
           f"&aid={aid}&playingTime={playing_time}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


# ============ 滑块验证码 API ============

def slider_captcha_api(cache: XueXiTUserCache,
                       retry: int = 3) -> Tuple[Optional[Dict], Optional[Exception]]:
    """获取滑块验证码信息 - 对应 Go XueXiTSliderApi"""
    url = "https://passport2.chaoxing.com/processVerifyCode?type=slider"
    client = _build_client(cache)
    try:
        body, resp = client.get(
            url, headers={"User-Agent": client._ua}, retry=retry)
        data = safe_json_parse(body) if body else None
        if data:
            return data, None
        return None, Exception(f"获取滑块验证码失败")
    finally:
        client.close()


def pass_slider_api(cache: XueXiTUserCache,
                    x_position: int, token: str = "",
                    retry: int = 3) -> Tuple[bool, Optional[Exception]]:
    """提交滑块验证 - 对应 Go XueXiTPassSlider"""
    url = "https://passport2.chaoxing.com/validateVerificationCode"
    data = {"type": "slider", "x": str(x_position), "token": token}
    client = _build_client(cache)
    try:
        body, resp = _do_post_form(client, url, data, retry=retry)
        resp_data = safe_json_parse(body) if body else None
        if resp_data and resp_data.get("status") is True:
            return True, None
        return False, Exception(f"滑块验证失败: {body}")
    finally:
        client.close()


# ============ 作业 API ============

def pull_work_list_api(cache: XueXiTUserCache,
                       course_id: str, class_id: str,
                       cpi: str, retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取作业列表 - 对应 Go PullWorkListHtmlApi
    URL: https://mooc1-api.chaoxing.com/work/task-list
    """
    url = (f"https://mooc1-api.chaoxing.com/work/task-list"
           f"?courseId={course_id}&classId={class_id}&cpi={cpi}")
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "accept-language": "zh_CN",
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def enter_work_api(cache: XueXiTUserCache,
                   work_id: str, enc: str,
                   course_id: str, class_id: str,
                   cpi: str, retry: int = 3) -> Tuple[str, Optional[Any]]:
    """进入作业 - 对应 Go PullWorkEnterInformHtmlApi
    URL: https://mooc1-api.chaoxing.com/android/mtaskmsgspecial
    """
    user_id = cache.cookie_dict.get("_uid", cache.uid)
    url = (f"https://mooc1-api.chaoxing.com/android/mtaskmsgspecial"
           f"?taskrefId={work_id}&msgId=0&courseId={course_id}"
           f"&userId={user_id}&clazzId={class_id}&type=work&enc_task={enc}")
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "accept-language": "zh_CN",
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def pull_work_question_api(cache: XueXiTUserCache,
                           course_id: str, class_id: str,
                           work_id: str, question_index: int,
                           cpi: str, work_answer_id: str = "",
                           enc: str = "", msg_id: str = "0",
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取作业题目 - 对应 Go PullWorkQuestionApi
    URL: https://mooc1-api.chaoxing.com/mooc-ans/work/phone/doHomeWork
    """
    url = (f"https://mooc1-api.chaoxing.com/mooc-ans/work/phone/doHomeWork"
           f"?courseId={course_id}&workId={work_id}&cpi={cpi}"
           f"&workAnswerId={work_answer_id}&classId={class_id}"
           f"&oldWorkId&mooc=1&msgId={msg_id}&source=0"
           f"&checkIntegrity=true&enc={enc}"
           f"&keyboardDisplayRequiresUserAction=1"
           f"&index={question_index}")
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "accept-language": "zh_CN",
            "Referer": (f"https://mooc1-api.chaoxing.com/mooc-ans/work/phone/task-work"
                        f"?taskrefId={work_id}&courseId={course_id}&classId={class_id}"
                        f"&userId={cache.cookie_dict.get('_uid', cache.uid)}"
                        f"&role=&source=0&enc_task=&cpi={cpi}&vx=0&fromGroup=0"),
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def submit_work_answer_api(cache: XueXiTUserCache,
                           answer_data,
                           is_submit: bool = False,
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """提交作业答案 - 对应 Go SubmitWorkAnswerApi
    URL: https://mooc1-api.chaoxing.com/mooc-ans/work/phone/doNormalHomeWorkSubmit
    answer_data: Dict或List[tuple]，Go中courseId/workRelationId/classId重复添加两次
    """
    # Go: SubmitWorkAnswerApi(question, !isSubmit) → tempSave = NOT is_submit
    # is_submit=True(提交) → tempSave=false; is_submit=False(暂存) → tempSave=true
    temp_save_str = str(not is_submit).lower()
    url = f"https://mooc1-api.chaoxing.com/mooc-ans/work/phone/doNormalHomeWorkSubmit?tempSave={temp_save_str}"
    # 添加tempSave到form body
    if isinstance(answer_data, list):
        answer_data.append(("tempSave", temp_save_str))
    else:
        answer_data["tempSave"] = temp_save_str
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://mooc1-api.chaoxing.com",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "zh-CN,en-US;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = _do_post_form(client, url, answer_data, headers=hdrs,
                                   retry=retry, use_multipart=False)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ 考试 API ============

def pull_exam_list_api(cache: XueXiTUserCache,
                       course_id: str, class_id: str,
                       cpi: str, retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取考试列表 - 对应 Go PullExamListHtmlApi
    URL: https://mooc1-api.chaoxing.com/mooc-ans/exam/phone/task-list
    """
    url = (f"https://mooc1-api.chaoxing.com/mooc-ans/exam/phone/task-list"
           f"?courseId={course_id}&classId={class_id}&cpi={cpi}")
    client = _build_client(cache, custom_ua=XXTEXAMUA)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "accept-language": "zh_CN",
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def enter_exam_api(cache: XueXiTUserCache,
                   exam_id: str, enc: str,
                   course_id: str, class_id: str,
                   cpi: str, retry: int = 3) -> Tuple[str, Optional[Any]]:
    """进入考试 - 对应 Go PullExamEnterInformHtmlApi
    URL: https://mooc1-api.chaoxing.com/exam-ans/android/mtaskmsgspecial
    """
    user_id = cache.cookie_dict.get("_uid", cache.uid)
    url = (f"https://mooc1-api.chaoxing.com/exam-ans/android/mtaskmsgspecial"
           f"?taskrefId={exam_id}&msgId=0&courseId={course_id}"
           f"&userId={user_id}&clazzId={class_id}&type=exam&enc_task={enc}")
    client = _build_client(cache, custom_ua=XXTEXAMUA)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "accept-language": "zh_CN",
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ cx_captcha 滑块验证码 (对应 Go api/xuexitong/XueXiTongVerCodeApi.go 268-470行) ============

# Go PassSliderApi 专用固定UA (Android MI 5X，与 GetUA("mobile") 不同，不可替换)
_CX_CAPTCHA_SLIDER_UA = (
    "Mozilla/5.0 (Linux; Android 8.1.0; MI 5X Build/OPM1.171019.019; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/71.0.3578.99 "
    "Mobile Safari/537.36 (schild:ce5175d20950c8ee955fb03246f762da) (device:MI 5X) "
    "Language/zh_CN com.chaoxing.mobile/ChaoXingStudy_3_6.7.2_android_phone_10936_311 "
    "(@Kalimdor)_76c82452584d47e39ab79aa54ea86554"
)

_CX_CAPTCHA_HDRS = {
    "Accept-Language": "zh-CN,en-US;q=0.9",
    "X-Requested-With": "com.chaoxing.mobile",
    "Accept": "*/*",
    "Connection": "keep-alive",
    # 注意: 不可手动设置Host头 — 图片实际位于captcha-b.chaoxing.com等CDN主机，
    # httpx会按URL自动设置正确的Host，手动覆盖会导致CDN 404
}

# tls_client: 模拟Chrome TLS指纹。超星check/verification/result接口已启用
# TLS指纹风控 — httpx/requests的OpenSSL指纹会被拒(verification error[r])，
# 必须用浏览器指纹才能通过。未安装时回退httpx(会被风控拒绝)。
try:
    import tls_client as _tls_client_mod
    _HAS_TLS_CLIENT = True
except ImportError:
    _tls_client_mod = None
    _HAS_TLS_CLIENT = False


def _tls_spoof_get(url: str, headers: Dict, proxy_ip: str = "",
                   timeout: float = 30.0, retry: int = 3) -> str:
    """TLS指纹伪装的GET请求(仅用于超星滑块check接口)
    优先tls_client(chrome指纹)，不可用时回退httpx裸请求
    """
    last_err = "未知错误"
    for _ in range(max(0, retry) + 1):
        try:
            if _HAS_TLS_CLIENT:
                # 注意: 部分tls_client版本不支持timeout_seconds参数，
                # 探针验证的成功写法仅传client_identifier与
                # random_tls_extension_order，此处用try/except兼容
                try:
                    sess = _tls_client_mod.Session(
                        client_identifier="chrome_120",
                        random_tls_extension_order=False,
                        timeout_seconds=int(timeout))
                except TypeError:
                    sess = _tls_client_mod.Session(
                        client_identifier="chrome_120",
                        random_tls_extension_order=False)
                if proxy_ip:
                    sess.proxies = {"http": f"http://{proxy_ip}",
                                    "https": f"http://{proxy_ip}"}
                resp = sess.get(url, headers=headers)
                return resp.text
            # 回退: httpx裸请求(无cookie)，会被TLS风控拒绝，仅作兼容保底
            client = HttpClient(proxy_ip=proxy_ip or None,
                                verify_ssl=False, timeout=timeout)
            try:
                body, _ = client.get(url, headers=headers, retry=0)
                return body
            finally:
                client.close()
        except Exception as e:
            last_err = str(e)
            time.sleep(0.3)
    raise RuntimeError(f"滑块校验请求失败: {last_err}")


def cx_captcha_conf_api(cache: XueXiTUserCache, captcha_id: str,
                        retry: int = 3) -> str:
    """获取滑块验证码配置(服务器时间t) - 对应 Go XueXiTSliderVerificationCodeApi
    返回形如: cx_captcha_function({"t":1764584640340,"captchaId":"..."})
    """
    url = ("https://captcha.chaoxing.com/captcha/get/conf"
           f"?callback=cx_captcha_function&captchaId={captcha_id}"
           f"&_={int(time.time() * 1000)}")
    client = _build_client(cache)
    try:
        hdrs = dict(_CX_CAPTCHA_HDRS)
        hdrs["User-Agent"] = client._ua
        body, _ = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body
    finally:
        client.close()


def cx_captcha_img_api(cache: XueXiTUserCache, captcha_id: str,
                       server_time: str, referer: str,
                       iv: str = "", retry: int = 3) -> str:
    """获取滑块验证码图片信息(token/背景图/裁剪图) - 对应 Go XueXiTSliderVerificationImgApi
    captchaKey = md5(serverTime + uuid)
    token = md5(serverTime + captchaId + "slide" + captchaKey) + ":" + (serverTime + 300000)
    iv: 动态值 md5(captchaId+"slide"+当前毫秒+uuid)，服务器记录后要求check时一致
    """
    captcha_key = hashlib.md5(
        (server_time + str(_uuid_mod.uuid4())).encode()).hexdigest()
    md5hex = hashlib.md5(
        (server_time + captcha_id + "slide" + captcha_key).encode()).hexdigest()
    token = f"{md5hex}:{int(server_time) + 300000}"
    url = ("https://captcha.chaoxing.com/captcha/get/verification/image"
           f"?callback=cx_captcha_function&captchaId={captcha_id}"
           f"&type=slide&version=1.1.20&captchaKey={captcha_key}"
           f"&token={token}&referer={quote_plus(referer, safe='')}")
    if iv:
        url += f"&iv={iv}&_={int(time.time() * 1000)}"
    client = _build_client(cache)
    try:
        hdrs = dict(_CX_CAPTCHA_HDRS)
        hdrs["User-Agent"] = client._ua
        # 浏览器请求image接口时自带来源页Referer头
        hdrs["Referer"] = referer
        body, _ = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body
    finally:
        client.close()


def pull_cx_slider_img_api(cache: XueXiTUserCache, img_url: str,
                           retry: int = 5) -> bytes:
    """下载验证码图片字节(禁止重定向) - 对应 Go PullSliderImgApi"""
    client = _build_client(cache)
    try:
        hdrs = dict(_CX_CAPTCHA_HDRS)
        hdrs["User-Agent"] = client._ua
        last_err = None
        for _ in range(max(0, retry) + 1):
            try:
                resp = client._get_client().get(
                    img_url, headers=hdrs, follow_redirects=False)
                if resp.status_code == 200:
                    return resp.content
                last_err = f"HTTP 状态码异常: {resp.status_code}"
            except Exception as e:
                last_err = str(e)
            time.sleep(0.15)
        raise RuntimeError(f"验证码图片下载失败: {last_err}")
    finally:
        client.close()


def pass_cx_slider_api(cache: XueXiTUserCache, captcha_id: str,
                       token: str, x_point: int,
                       iv: str = "", referer: str = "",
                       retry: int = 3) -> str:
    """提交滑块偏移量校验 - 对应 Go PassSliderApi (runEnv=10 web)
    注意: t/_ 参数与Go保持一致；iv必须与image接口传入的同一iv一致
    (官方前端JS: iv=md5(captchaId+"slide"+当前毫秒+uuid)，image与check复用)，
    服务器已强制校验iv一致性，写死旧值会报 verification error
    """
    text_click = '[{"x":' + str(int(x_point)) + '}]'
    if not iv:
        iv = "cdd9bfb9e7805d0d2d5f1ad4498f70e1"
    url = ("https://captcha.chaoxing.com/captcha/check/verification/result"
           f"?callback=cx_captcha_function&captchaId={captcha_id}"
           f"&type=slide&token={token}"
           f"&textClickArr={quote_plus(text_click, safe='')}"
           f"&coordinate={quote_plus('[]', safe='')}"
           "&runEnv=10&version=1.1.20&t=a"
           f"&iv={iv}&_={int(time.time() * 1000)}")
    # 对齐Go PassSliderApi: 该请求不携带任何cookie(仅代理+UA)。
    # 另外check接口启TLS指纹风控，必须用tls_client伪装Chrome指纹
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    hdrs = dict(_CX_CAPTCHA_HDRS)
    hdrs["User-Agent"] = _CX_CAPTCHA_SLIDER_UA
    if referer:
        # 浏览器发起check时会自动携带来源页Referer
        hdrs["Referer"] = referer
    return _tls_spoof_get(url, hdrs, proxy_ip=proxy or "", retry=retry)


def pull_exam_paper_api(cache: XueXiTUserCache,
                        course_id: str, class_id: str,
                        exam_id: str, cpi: str,
                        exam_answer_id: str = "",
                        imei: str = "", captcha_validate: str = "",
                        jt: str = "0",
                        redo: bool = False,
                        retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取考试试卷页面 - 对应 Go PullExamPaperHtmlApi / PullReDoExamPaperHtmlApi
    URL: https://mooc1-api.chaoxing.com/exam-ans/exam/phone/start
    redo=True时对应 Go PullReDoExamPaperHtmlApi，追加&redo=1
    """
    if not imei:
        imei = _IMEI
    url = (f"https://mooc1-api.chaoxing.com/exam-ans/exam/phone/start"
           f"?courseId={course_id}&classId={class_id}"
           f"&examId={exam_id}&source=0"
           f"&examAnswerId={exam_answer_id}&cpi={cpi}"
           f"&keyboardDisplayRequiresUserAction=1"
           f"&imei={imei}&faceDetectionResult"
           f"&captchavalidate={captcha_validate}&jt={jt}"
           f"&_v=0.3868294515418076"
           f"&cxcid&cxtime&signt&_signcode=3&_signc=0&_signe=3-1&signk")
    if redo:
        url += "&redo=1"
    client = _build_client(cache, custom_ua=XXTEXAMUA)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Accept-Language": "zh-CN,en-US;q=0.9",
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def pull_exam_question_api(cache: XueXiTUserCache,
                           course_id: str, class_id: str,
                           t_id: str, answer_id: str,
                           cpi: str, remain_time_param: str,
                           enc: str,
                           relation_answer_last_update_time: str = "",
                           index: int = 0,
                           imei: str = "",
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取考试题目 - 对应 Go PullExamQuestionApi
    URL: https://mooc1-api.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew
    """
    if not imei:
        imei = _IMEI
    if not relation_answer_last_update_time:
        relation_answer_last_update_time = str(int(time.time() * 1000))
    url = (f"https://mooc1-api.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew"
           f"?keyboardDisplayRequiresUserAction=1"
           f"&courseId={course_id}&classId={class_id}"
           f"&source=0&imei={imei}"
           f"&tId={t_id}&id={answer_id}&p=1"
           f"&start={index}&cpi={cpi}"
           f"&isphone=true&monitorStatus=0&monitorOp=-1"
           f"&remainTimeParam={remain_time_param}"
           f"&relationAnswerLastUpdateTime={relation_answer_last_update_time}"
           f"&enc={enc}")
    client = _build_client(cache, custom_ua=XXTEXAMUA)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Accept-Language": "zh-CN,en-US;q=0.9",
            "X-Requested-With": "com.chaoxing.mobile",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


def get_exam_signature(uid: str, qid: str, x: int, y: int) -> Dict[str, Any]:
    """计算考试签名 - 对应 Go GetExamSignature
    Returns: {"pos": str, "rd": float, "value": str, "_edt": str}
    """
    ts = str(int(time.time() * 1000))
    r1 = random.randint(0, 8)
    r2 = random.randint(0, 8)

    a = f"{secrets.token_hex(16)}{ts[4:]}{r1}{r2}"
    if qid:
        a += qid

    temp = 0
    for ch in a:
        temp = ((temp << 5) - temp + ord(ch)) & 0xFFFFFFFFFFFFFFFF
        # Keep as 64-bit signed
        if temp >= (1 << 63):
            temp -= (1 << 64)

    salt = f"{r1}{r2}{(0x7fffffff & temp) % 10}"

    enc_val = uid
    if qid:
        enc_val += "_" + qid
    enc_val += "|" + salt

    enc_val2 = "".join(str(ord(c)) for c in enc_val)

    b = len(enc_val2) // 5
    c_str = enc_val2[b] + enc_val2[2 * b] + enc_val2[3 * b] + enc_val2[4 * b]
    c = int(c_str)

    d = len(enc_val) // 2 + 1

    first10 = int(enc_val2[:10])
    e = (c * first10 + d) % 0x7FFFFFFF

    pos = f"({x}|{y})"

    result = ""
    for ch in pos:
        key = int(math.floor(e / 0x7FFFFFFF * 0xFF))
        v = ord(ch) ^ key
        result += f"{v:02x}"
        e = (c * e + d) % 0x7FFFFFFF

    return {
        "pos": result + secrets.token_hex(4),
        "rd": random.random(),
        "value": pos,
        "_edt": ts + salt,
    }


def submit_exam_answer_api(cache: XueXiTUserCache,
                           answer_data: Dict,
                           is_submit: bool = False,
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """提交考试答案 - 对应 Go SubmitExamAnswerApi
    URL: https://mooc1-api.chaoxing.com/exam-ans/exam/test/reVersionSubmitTestNew
    answer_data must contain: courseId, testPaperId, testUserRelationId,
    classId, cpi, userId, enc, encRemainTime, encLastUpdateTime,
    remainTime, enterPageTime, questionId, questionTypeCode,
    questionTypeStr, score, tid, answerId, remainTimeParam, imei
    """
    qid = answer_data.get("questionId", "")
    uid = answer_data.get("userId", cache.cookie_dict.get("_uid", cache.uid))
    x = random.randint(0, 99) + 900
    y = random.randint(0, 899) + 100
    sig = get_exam_signature(uid, qid, x, y)

    # Go: SubmitExamAnswerApi(question, !isSubmit) → tempSave = NOT is_submit
    # is_submit=True(提交) → tempSave=false; is_submit=False(暂存) → tempSave=true
    temp_save_str = str(not is_submit).lower()
    imei_val = answer_data.get("imei", _IMEI)

    url = (f"https://mooc1-api.chaoxing.com/exam-ans/exam/test/reVersionSubmitTestNew"
           f"?classId={answer_data.get('classId', '')}"
           f"&courseId={answer_data.get('courseId', '')}"
           f"&testPaperId={answer_data.get('testPaperId', '')}"
           f"&testUserRelationId={answer_data.get('testUserRelationId', '')}"
           f"&cpi={answer_data.get('cpi', '')}"
           f"&version=1&tempSave={temp_save_str}"
           f"&pos={sig['pos']}"
           f"&rd={sig['rd']:.16f}"
           f"&value={quote(sig['value'])}"
           f"&qid={qid}"
           f"&_edt={sig['_edt']}"
           f"&_csign=1&_signcode=3&_signc=0&_signe=3-1&_signk"
           f"&_cxcid&_cxtime&_signt")

    # Build form body
    form = {
        "courseId": answer_data.get("courseId", ""),
        "testPaperId": answer_data.get("testPaperId", ""),
        "testUserRelationId": answer_data.get("testUserRelationId", ""),
        "classId": answer_data.get("classId", ""),
        "type": "0",
        "isphone": "true",
        "imei": imei_val,
        "subCount": "",
        "remainTime": answer_data.get("remainTime", ""),
        "tempSave": temp_save_str,
        "timeOver": "false",
        "encRemainTime": answer_data.get("encRemainTime", ""),
        "encLastUpdateTime": answer_data.get("encLastUpdateTime", ""),
        "enc": answer_data.get("enc", ""),
        "userId": uid,
        "start": "0",
        "enterPageTime": answer_data.get("enterPageTime", ""),
        "randomOptions": "false",
        "questionId": qid,
        "monitorforcesubmit": "0",
        "answeredView": "0",
        "exitdtime": "0",
        "paperGroupId": "0",
    }
    # Add score+qid
    score_val = answer_data.get("score", "")
    if score_val:
        form[f"score{qid}"] = score_val

    # Add type-specific answer fields
    qtype_code = answer_data.get("questionTypeCode", "0")
    qtype_str = answer_data.get("questionTypeStr", "")
    answer_text = answer_data.get("answer", "")
    form[f"type{qid}"] = qtype_code
    form[f"typeName{qid}"] = qtype_str

    if qtype_code == "0":  # 单选
        form["hidetext"] = ""
        form[f"answer{qid}"] = answer_text
    elif qtype_code == "1":  # 多选
        form["hidetext"] = ""
        form[f"answers{qid}"] = answer_text
    elif qtype_code == "3":  # 判断
        form[f"answer{qid}"] = answer_text
    elif qtype_code == "2":  # 填空
        form[f"answerEditor{qid}1"] = answer_text
        form[f"blankNum{qid}"] = "1,"
    elif qtype_code in ("4", "6"):  # 简答/论述
        form[f"answer{qid}"] = answer_text

    # Referer header
    referer_url = (f"https://mooc1-api.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew"
                   f"?keyboardDisplayRequiresUserAction=1"
                   f"&courseId={answer_data.get('courseId', '')}"
                   f"&classId={answer_data.get('classId', '')}"
                   f"&source=0&imei={imei_val}"
                   f"&tId={answer_data.get('tid', '')}"
                   f"&id={answer_data.get('answerId', '')}"
                   f"&p=1&start=1"
                   f"&cpi={answer_data.get('cpi', '')}"
                   f"&isphone=true&monitorStatus=0&monitorOp=-1"
                   f"&remainTimeParam={answer_data.get('remainTimeParam', '')}"
                   f"&relationAnswerLastUpdateTime={int(time.time() * 1000)}"
                   f"&enc={answer_data.get('enc', '')}")

    client = _build_client(cache, custom_ua=XXTEXAMUA)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://mooc1-api.chaoxing.com",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "zh-CN,en-US;q=0.9",
            "Referer": referer_url,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Host": "mooc1-api.chaoxing.com",
            "Connection": "keep-alive",
        }
        body, resp = _do_post_form(client, url, form, headers=hdrs,
                                   retry=retry, use_multipart=False)
        _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ 学习通内置 AI ============

# ============ 学习通内置AI (autoExam=3) - 完全对齐 Go XueXiTongAIApi.go ============

_XXT_AI_PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0")
_XXT_AI_BOT_ID = "7438777570621653018"
_XXT_AI_APP_ID = "1192651262850"

# 按课程加锁，防止过于频繁调用（对齐 Go courseLocks/lockByCourse）
_xxt_ai_course_locks: Dict[str, Any] = {}
_xxt_ai_locks_guard = __import__("threading").Lock()


def _xxt_ai_lock_course(course_id: str):
    with _xxt_ai_locks_guard:
        lk = _xxt_ai_course_locks.get(course_id)
        if lk is None:
            lk = __import__("threading").Lock()
            _xxt_ai_course_locks[course_id] = lk
    lk.acquire()
    return lk


def _xxt_ai_inform_api(cache: XueXiTUserCache, class_id: str,
                       course_id: str, cpi: str, retry: int = 3) -> str:
    """拉取学习通AI必要参数页面 - 对齐 Go xxtAiInformApi"""
    if retry < 0:
        return ""
    url = ("https://stat2-ans.chaoxing.com/bot/index?fromWorkbench=true&upload=true"
           "&clazzid=" + str(class_id) +
           "&showToolbox=false&bgColorNone=true&app_id=" + _XXT_AI_APP_ID +
           "&courseid=" + str(course_id) + "&cpi=" + str(cpi) +
           "&bot_id=" + _XXT_AI_BOT_ID + "&ut=s")
    headers = {
        "User-Agent": _XXT_AI_PC_UA,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                   "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"),
        "Cache-Control": "max-age=0",
        "sec-ch-ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Host": "stat2-ans.chaoxing.com",
        "Connection": "keep-alive",
        "Cookie": "; ".join(f"{k}={v}" for k, v in list(cache.cookie_dict.items())),
    }
    try:
        resp = _requests_lib.get(url, headers=headers,
                                 verify=False, timeout=30)
        return resp.text
    except Exception:
        time.sleep(0.1)
        return _xxt_ai_inform_api(cache, class_id, course_id, cpi, retry - 1)


def _xxt_ai_answer_api(cache: XueXiTUserCache, coze_enc: str, user_id: str,
                       course_id: str, class_id: str, conversation_id: str,
                       course_name: str, student_name: str, person_id: str,
                       content: str, retry: int = 5) -> str:
    """请求学习通AI获取答复（流式） - 对齐 Go xxtAiAnswerApi"""
    if retry < 0:
        return ""
    url = ("https://stat2-ans.chaoxing.com/stat2/bot/talk-v1?cozeEnc=" + coze_enc +
           "&botId=" + _XXT_AI_BOT_ID + "&userId=" + user_id +
           "&appId=" + _XXT_AI_APP_ID + "&courseid=" + str(course_id) +
           "&clazzid=" + str(class_id) + "&ut=s")
    body = ('[{"role":"user","content":"' + content +
            '","baseData":{"conversationId":"' + conversation_id +
            '","userId":"' + user_id + '","appId":"' + _XXT_AI_APP_ID +
            '","botId":"' + _XXT_AI_BOT_ID +
            '","custom_variables":{"courseName":"' + course_name +
            '","studentName":"' + student_name +
            '","weakKnowledgePoint":"{}"},"shortcut_command":{},"sourceInfo":"",'
            '"sdkFlag":"false","courseid":"' + str(course_id) +
            '","clazzid":"' + str(class_id) +
            '","personid":"' + person_id + '"}}]')
    headers = {
        "User-Agent": _XXT_AI_PC_UA,
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "Origin": "https://stat2-ans.chaoxing.com",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Host": "stat2-ans.chaoxing.com",
        "Connection": "keep-alive",
        "Cookie": "; ".join(f"{k}={v}" for k, v in list(cache.cookie_dict.items())),
    }
    try:
        resp = _requests_lib.post(url, data=body.encode("utf-8"),
                                  headers=headers, verify=False,
                                  stream=True, timeout=(30, None))
        final_answer = ""
        # 流式按行读取，每段 chunk 以 $_$ 分割，只拼接 type=coreAnswer 的内容
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line:
                continue
            for p in line.split("$_$"):
                p = p.strip()
                if (not p or p == "server-heartbeat"
                        or p.startswith("server-current-chatid")):
                    continue
                try:
                    chunk = _json.loads(p)
                except Exception:
                    continue
                if isinstance(chunk, dict) and chunk.get("type") == "coreAnswer":
                    final_answer += str(chunk.get("content", ""))
        resp.close()
        # 替换非法字符（对齐 Go）
        final_answer = final_answer.replace("&quot;", '"')
        final_answer = final_answer.replace("&nbsp;", " ")
        final_answer = final_answer.replace("&amp;", "&")
        final_answer = final_answer.replace("&lt;", "<")
        final_answer = final_answer.replace("&gt;", ">")
        # json格式检查：非 JSON 数组则追加纠正语重试（对齐 Go）
        try:
            parsed = _json.loads(final_answer)
            if not isinstance(parsed, list):
                raise ValueError
        except Exception:
            content += "\n\n你刚才生成的回复未严格遵循json格式，我无法正常解析，请你重新生成！！！"
            return _xxt_ai_answer_api(cache, coze_enc, user_id, course_id,
                                      class_id, conversation_id, course_name,
                                      student_name, person_id, content, retry - 1)
        return final_answer
    except Exception:
        time.sleep(0.1)
        return _xxt_ai_answer_api(cache, coze_enc, user_id, course_id,
                                  class_id, conversation_id, course_name,
                                  student_name, person_id, content, retry - 1)


def xxt_ai_api(cache: XueXiTUserCache,
               question: str, course_id: str = "",
               class_id: str = "", cpi: str = "",
               options: Optional[List[str]] = None, q_type: str = "",
               retry: int = 3) -> Tuple[str, Optional[Any]]:
    """学习通内置 AI 答题 - 对应 Go XueXiTongAIAggregation
    参数顺序保持兼容: (cache, question, course_id, class_id, cpi)
    返回: (答案文本, None)
    """
    return _xxt_ai_aggregation(cache, question, class_id, course_id, cpi,
                               options=options, q_type=q_type)


def _xxt_ai_aggregation(cache: XueXiTUserCache, question: str,
                        class_id: str, course_id: str, cpi: str,
                        options: Optional[List[str]] = None,
                        q_type: str = "") -> Tuple[str, Optional[Any]]:
    """学习通AI包装 - 对齐 Go XueXiTongAIAggregation"""
    lk = _xxt_ai_lock_course(str(course_id))
    try:
        # 构建结构化提问（对齐 Go AIProblemMessage 的 system+user 拼接）
        try:
            from logic.core.ai_client import _build_question_prompt
            system_prompt, user_content = _build_question_prompt(
                q_type, question, options)
            content = system_prompt + user_content
        except Exception:
            content = question
        # JSON 转义后去前后引号（对齐 Go json.Marshal + trimQuotes）
        content = _json.dumps(content, ensure_ascii=False)[1:-1]

        inform_html = _xxt_ai_inform_api(cache, class_id, course_id, cpi)
        if not inform_html:
            return "", Exception("内置AI参数页拉取失败")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(inform_html, "html.parser")

        def get_val(fid: str) -> str:
            el = soup.find(id=fid)
            return el.get("value", "") if el else ""

        m = re.search(r'"studentName"\s*:\s*"([^"]+)"', inform_html)
        student_name = m.group(1) if m else ""

        answer = _xxt_ai_answer_api(
            cache, get_val("cozeEnc"), get_val("userId"),
            get_val("courseId"), get_val("clazzId"),
            get_val("conversationId"), get_val("courseName"),
            student_name, get_val("personId"), content)
        return answer, None
    except Exception as e:
        return "", e
    finally:
        lk.release()
