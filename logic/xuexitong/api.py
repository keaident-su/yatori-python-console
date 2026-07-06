# -*- coding: utf-8 -*-
"""学习通 API 接口层 - 对应 Go 项目的 api/xuexitong/
完整重写：AES加密登录、移动端UA、正确的课程/章节/卡片/视频API
"""
import secrets
import hashlib
import re
import time
from typing import Tuple, Optional, Any, Dict, List
from urllib.parse import urlencode, quote

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad as aes_pad
import base64

from logic.core.http_client import HttpClient
from logic.xuexitong.models import XueXiTUserCache
from logic.core.models import safe_json_parse

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
    elif ua_type == "web":
        return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 Edg/107.0.1418.35")
    return ""


def _build_client(cache: XueXiTUserCache, ua: str = "mobile") -> HttpClient:
    """构建带学习通移动UA的HTTP客户端"""
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    # 设置移动端 UA
    client._ua = get_ua(ua)
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
        for name, value in cache.cookie_dict.items():
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


def _do_post_form(client: HttpClient, url: str, data: Dict,
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
        f"&otherInfo={quote(p.other_info)}"
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
        f"&otherInfo={quote(p.other_info)}"
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
            "Accept": "*/*",
            "Host": "mooc1-api.chaoxing.com",
            "X-Requested-With": "XMLHttpRequest",
        }
        body, resp = _do_get(client, url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ 文档/外链/讨论 ============

def document_submit_api(cache: XueXiTUserCache, object_id: str,
                        knowledge_id: str, uid: str,
                        retry: int = 8) -> Tuple[str, Optional[Any]]:
    """文档任务点提交"""
    url = (f"https://mooc1.chaoxing.com/ananas/status/{object_id}"
           f"?k={knowledge_id}&_dc={uid}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def hyperlink_submit_api(cache: XueXiTUserCache, object_id: str,
                         knowledge_id: str, uid: str,
                         retry: int = 8) -> Tuple[str, Optional[Any]]:
    """外链任务点提交 - 对应 Go ExecuteHyperlink"""
    url = (f"https://mooc1.chaoxing.com/ananas/status/{object_id}"
           f"?k={knowledge_id}&_dc={uid}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
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
        f"&otherInfo={quote(p.other_info)}"
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
            "Sec-Fetch-Mode": " cors",
            "Sec-Fetch-Dest": " empty",
            "Pragma": "no-cache",
        }
        body, resp = client.get(url, headers=hdrs, retry=retry)
        if resp is not None:
            _extract_cookies(client, cache)
        return body, resp
    finally:
        client.close()


# ============ iframe 解析 ============

def parse_iframe_data(html_string: str) -> List[Dict]:
    """解析卡片 description HTML 中的 iframe 标签
    对应 Go 的 parseIframeData()
    返回: [{"data": {...}, "other": {"module": "...", ...}, "has_data": True}, ...]
    """
    import json as _json
    results = []
    if not html_string:
        return results

    # 匹配 iframe 标签及其属性
    iframe_pattern = re.compile(
        r'<iframe\s+([^>]*)>', re.IGNORECASE | re.DOTALL)
    # 匹配单个属性: key="value" 或 key='value'
    attr_pattern = re.compile(
        r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
        re.IGNORECASE)

    for iframe_match in iframe_pattern.finditer(html_string):
        attrs_str = iframe_match.group(1)
        iframe_attrs = {"data": {}, "other": {}, "has_data": False}

        for attr_match in attr_pattern.finditer(attrs_str):
            key = attr_match.group(1).lower()
            value = attr_match.group(2) if attr_match.group(
                2) is not None else attr_match.group(3)
            if value is None:
                value = ""

            if key == "data" and value.strip():
                iframe_attrs["has_data"] = True
                # 清理: 替换 &quot; 为 "，移除多余空白
                cleaned = value.replace("&quot;", '"')
                cleaned = re.sub(r'\s+', '', cleaned)
                try:
                    iframe_attrs["data"] = _json.loads(cleaned)
                except Exception:
                    pass
            else:
                iframe_attrs["other"][key] = value

        results.append(iframe_attrs)

    return results


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


# ============ 人脸识别 API ============

def get_face_qr_code_api3(cache: XueXiTUserCache, course_id: str,
                          class_id: str, cpi: str, knowledge_id: str,
                          retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取人脸QR码 - 对应 Go GetFaceQrCodeApi3"""
    url = (f"https://mobilelearn.chaoxing.com/faceIdentify/getFaceQrCode"
           f"?courseId={course_id}&classId={class_id}&cpi={cpi}"
           f"&knowledgeId={knowledge_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def get_face_upload_token(cache: XueXiTUserCache,
                          retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取人脸上传token - 对应 Go GetFaceUpLoadToken"""
    url = "https://pan-yz.chaoxing.com/token/upload"
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def upload_face_image_api(cache: XueXiTUserCache, token: str,
                          image_data: bytes,
                          retry: int = 3) -> Tuple[str, Optional[Any]]:
    """上传人脸图片 - 对应 Go UploadFaceImageApi"""
    url = f"https://pan-yz.chaoxing.com/upload?token={token}&puid={cache.uid}"
    client = _build_client(cache)
    try:
        hdrs = {"User-Agent": client._ua}
        files = {"file": ("face.jpg", image_data, "image/jpeg")}
        resp = client.session.post(url, headers=hdrs, files=files,
                                   verify=False, timeout=30)
        return resp.text if resp else "", resp
    finally:
        client.close()


def pass_face_qr_plan_phone_new_api(cache: XueXiTUserCache,
                                    qr_object_id: str,
                                    uuid: str,
                                    retry: int = 3) -> Tuple[str, Optional[Any]]:
    """手机端人脸验证 - 对应 Go PassFaceQrPlanPhoneNewApi"""
    url = (f"https://mobilelearn.chaoxing.com/faceIdentify/passFaceQrPlanPhoneNew"
           f"?qrObjectId={qr_object_id}&uuid={uuid}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def get_course_face_qr_state_api(cache: XueXiTUserCache,
                                 qr_object_id: str,
                                 retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取人脸状态 - 对应 Go GetCourseFaceQrStateApi"""
    url = (f"https://mobilelearn.chaoxing.com/faceIdentify/getCourseFaceQrState"
           f"?qrObjectId={qr_object_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def get_history_face_img(cache: XueXiTUserCache,
                         retry: int = 3) -> Tuple[str, Optional[bytes]]:
    """获取历史人脸图片 - 对应 Go GetHistoryFaceImg
    从学习通服务器拉取最近一次人脸识别的图片数据
    """
    url = "https://passport2.chaoxing.com/getFaceInfoByUid"
    client = _build_client(cache)
    try:
        body, resp = _do_get(client, url, retry=retry)
        data = safe_json_parse(body) if body else None
        if data and data.get("status") is True:
            face_url = data.get("result", {}).get("faceUrl", "")
            if face_url:
                # 下载人脸图片
                img_resp = client.session.get(
                    face_url, verify=False, timeout=30)
                if img_resp and img_resp.status_code == 200:
                    return body, img_resp.content
        return body, None
    finally:
        client.close()


def pass_face_pc_action(cache: XueXiTUserCache,
                        course_id: str, class_id: str, cpi: str,
                        knowledge_id: str, enc: str, job_id: str,
                        object_id: str, mid: str,
                        random_capture_time: str) -> Optional[Exception]:
    """PC端人脸绕过流程 - 对应 Go PassFacePCAction
    流程: GetHistoryFaceImg → GetFaceQrCode → UploadFace → PassFaceQrPlanPhoneNew → GetState
    """
    import json as _json

    # 1. 获取历史人脸
    _, img_data = get_history_face_img(cache)
    if img_data is None:
        return Exception("没有历史人脸数据")

    # 2. 获取QR码
    qr_body, _ = get_face_qr_code_api3(
        cache, course_id, class_id, cpi, knowledge_id)
    qr_data = safe_json_parse(qr_body) if qr_body else None
    if not qr_data:
        return Exception("获取人脸QR码失败")

    qr_object_id = qr_data.get("qrObjectId", "")
    uuid = qr_data.get("uuid", "")
    if not qr_object_id or not uuid:
        return Exception("QR码数据不完整")

    # 3. 获取上传token
    token_body, _ = get_face_upload_token(cache)
    token_data = safe_json_parse(token_body) if token_body else None
    token = token_data.get("token", "") if token_data else ""
    if not token:
        return Exception("获取上传token失败")

    # 4. 上传人脸图片
    upload_body, _ = upload_face_image_api(cache, token, img_data)
    upload_data = safe_json_parse(upload_body) if upload_body else None
    if not upload_data or upload_data.get("result") != "success":
        return Exception("上传人脸图片失败")

    # 5. 提交人脸验证
    pass_body, _ = pass_face_qr_plan_phone_new_api(
        cache, qr_object_id, uuid)
    pass_data = safe_json_parse(pass_body) if pass_body else None
    if not pass_data or pass_data.get("status") != 1:
        return Exception(f"人脸验证失败: {pass_body}")

    # 6. 检查状态
    time.sleep(2)
    state_body, _ = get_course_face_qr_state_api(cache, qr_object_id)
    state_data = safe_json_parse(state_body) if state_body else None
    if state_data and state_data.get("status") == 2:
        return None  # 人脸验证成功

    return None  # 假设成功


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
        resp = client.session.get(url, headers=hdrs, verify=False, timeout=30)
        if resp and resp.status_code == 200:
            return resp.content, None
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
    """获取章测/作业题目页面 - 对应 Go WorkFetchQuestion"""
    url = (f"https://mooc1.chaoxing.com/work/doWork"
           f"?courseId={work_point.course_id}"
           f"&classId={work_point.class_id}"
           f"&knowledgeId={work_point.knowledge_id}"
           f"&workId={work_point.work_id}"
           f"&jobId={work_point.job_id}"
           f"&schoolId={work_point.school_id}"
           f"&cpi={work_point.cpi}"
           f"&ktoken={work_point.k_token}"
           f"&enc={work_point.enc}"
           f"&puid={work_point.puid}"
           f"&ut=s")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def work_new_submit_answer_api(cache: XueXiTUserCache,
                               course_id: str, class_id: str,
                               knowledge_id: str, work_id: str,
                               answer_data: Dict,
                               retry: int = 3) -> Tuple[str, Optional[Any]]:
    """提交章测/作业答案 - 对应 Go WorkNewSubmitAnswer"""
    url = "https://mooc1.chaoxing.com/work/addStudentWorkNew"
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body, resp = _do_post_form(client, url, answer_data, headers=hdrs,
                                   retry=retry)
        return body, resp
    finally:
        client.close()


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


# ============ 讨论(BBS) API ============

def pull_phone_bbs_info_api(cache: XueXiTUserCache,
                            topic_id: str, course_id: str,
                            class_id: str,
                            retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取讨论主题信息 - 对应 Go PullPhoneBbsInfo"""
    url = (f"https://mooc1.chaoxing.com/bbscircle/grouptopic/getTopicDetail"
           f"?topicId={topic_id}&courseId={course_id}&classId={class_id}")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def bbs_reply_api(cache: XueXiTUserCache,
                  topic_id: str, course_id: str,
                  class_id: str, content: str,
                  retry: int = 3) -> Tuple[str, Optional[Any]]:
    """发表讨论回复 - 对应 Go BBSReply"""
    url = "https://mooc1.chaoxing.com/bbscircle/grouptopic/replyTopic"
    data = {
        "topicId": topic_id,
        "courseId": course_id,
        "classId": class_id,
        "content": content,
    }
    client = _build_client(cache)
    try:
        return _do_post_form(client, url, data, retry=retry)
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
        resp = client.session.get(url, verify=False, timeout=30)
        if resp and resp.status_code == 200:
            data = safe_json_parse(resp.text)
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
    """拉取作业列表 - 对应 Go PullWorkListAction"""
    url = (f"https://mooc1.chaoxing.com/work/getWorkList"
           f"?courseId={course_id}&classId={class_id}&cpi={cpi}&ut=s")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def enter_work_api(cache: XueXiTUserCache,
                   work_id: str, enc: str,
                   course_id: str, class_id: str,
                   cpi: str, retry: int = 3) -> Tuple[str, Optional[Any]]:
    """进入作业 - 对应 Go EnterWorkAction"""
    url = (f"https://mooc1.chaoxing.com/work/enterWork"
           f"?workId={work_id}&enc={enc}"
           f"&courseId={course_id}&classId={class_id}&cpi={cpi}&ut=s")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def pull_work_question_api(cache: XueXiTUserCache,
                           course_id: str, class_id: str,
                           work_id: str, question_index: int,
                           cpi: str, ktoken: str = "",
                           enc: str = "", job_id: str = "",
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取作业题目 - 对应 Go PullWorkQuestionAction"""
    url = (f"https://mooc1.chaoxing.com/work/doWork"
           f"?courseId={course_id}&classId={class_id}"
           f"&workId={work_id}&questionIndex={question_index}"
           f"&cpi={cpi}&ktoken={ktoken}&enc={enc}"
           f"&jobId={job_id}&ut=s")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def submit_work_answer_api(cache: XueXiTUserCache,
                           answer_data: Dict,
                           is_submit: bool = False,
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """提交作业答案 - 对应 Go SubmitWorkAnswerAction"""
    url = "https://mooc1.chaoxing.com/work/addStudentWorkNew"
    if is_submit:
        answer_data["submit"] = "true"
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body, resp = _do_post_form(client, url, answer_data, headers=hdrs,
                                   retry=retry)
        return body, resp
    finally:
        client.close()


# ============ 考试 API ============

def pull_exam_list_api(cache: XueXiTUserCache,
                       course_id: str, class_id: str,
                       cpi: str, retry: int = 3) -> Tuple[str, Optional[Any]]:
    """拉取考试列表 - 对应 Go PullExamListAction"""
    url = (f"https://mooc1.chaoxing.com/exam/getExamList"
           f"?courseId={course_id}&classId={class_id}&cpi={cpi}&ut=s")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def enter_exam_api(cache: XueXiTUserCache,
                   exam_id: str, enc: str,
                   course_id: str, class_id: str,
                   cpi: str, retry: int = 3) -> Tuple[str, Optional[Any]]:
    """进入考试 - 对应 Go EnterExamAction"""
    url = (f"https://mooc1.chaoxing.com/exam/enterExam"
           f"?examId={exam_id}&enc={enc}"
           f"&courseId={course_id}&classId={class_id}&cpi={cpi}&ut=s")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def pull_exam_question_api(cache: XueXiTUserCache,
                           course_id: str, class_id: str,
                           exam_id: str, question_index: int,
                           cpi: str, ktoken: str = "",
                           enc: str = "",
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """获取考试题目 - 对应 Go PullExamQuestionAction"""
    url = (f"https://mooc1.chaoxing.com/exam/doExam"
           f"?courseId={course_id}&classId={class_id}"
           f"&examId={exam_id}&questionIndex={question_index}"
           f"&cpi={cpi}&ktoken={ktoken}&enc={enc}&ut=s")
    client = _build_client(cache)
    try:
        return _do_get(client, url, retry=retry)
    finally:
        client.close()


def submit_exam_answer_api(cache: XueXiTUserCache,
                           answer_data: Dict,
                           is_submit: bool = False,
                           retry: int = 3) -> Tuple[str, Optional[Any]]:
    """提交考试答案 - 对应 Go SubmitExamAnswerAction"""
    url = "https://mooc1.chaoxing.com/exam/addStudentExamNew"
    if is_submit:
        answer_data["submit"] = "true"
    client = _build_client(cache)
    try:
        hdrs = {
            "User-Agent": client._ua,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body, resp = _do_post_form(client, url, answer_data, headers=hdrs,
                                   retry=retry)
        return body, resp
    finally:
        client.close()


# ============ 学习通内置 AI ============

def xxt_ai_api(cache: XueXiTUserCache,
               question: str, course_id: str = "",
               class_id: str = "", cpi: str = "",
               retry: int = 3) -> Tuple[str, Optional[Any]]:
    """学习通内置 AI 答题 - 对应 Go AnswerXXTAIGet"""
    url = "https://mooc1.chaoxing.com/ai/ask"
    data = {
        "question": question,
        "courseId": course_id,
        "classId": class_id,
        "cpi": cpi,
    }
    client = _build_client(cache)
    try:
        body, resp = _do_post_form(client, url, data, retry=retry)
        return body, resp
    finally:
        client.close()
