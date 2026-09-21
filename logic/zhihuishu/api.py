# -*- coding: utf-8 -*-
"""
智慧树平台 API 层 - 移植自外部项目 zhihuishu_sdk(fuckzhs) 并适配本工程

包含:
- ManagedSession: 统一 HTTP 会话(自动重试/代理透传/CASLOGC uuid 提取)
- ZhsAPIClientBase: 模板方法基类(准备请求 → 发送 → 解析响应)
- HikeAPIClient: 共享课(SPOC) API(含 MD5 签名)
- PolymasAPIClient: 新版 AI 课 API(Bearer Token/CAS Cookie)
- login_password: 密码登录(验证/额外验证检查/完成登录)

签名盐值与接口参数均为对 SDK 逆向结果的忠实移植, 日志统一接入项目日志体系。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta
from hashlib import md5
from typing import Any
from urllib.parse import unquote_plus

import requests
from requests.adapters import HTTPAdapter, Retry
from requests.cookies import RequestsCookieJar, create_cookie
from requests.utils import cookiejar_from_dict

from logic.platform_common import get_simple_logger
from logic.zhihuishu.models import (
    ZhsAPIError, ZhsAuthError, ZhsCaptchaError, ZhsTokenExpired,
)

logger = get_simple_logger("[智慧树]")

# Polymas Token 持久化文件(相对项目根目录; 目录不存在时自动创建)
POLYMAS_TOKEN_FILE = os.path.join("assets", "zhs_polymas_token.json")


# ============ HTTP 会话 ============

def cookie_jar_to_list(cookie_jar: RequestsCookieJar) -> list:
    """将 CookieJar 序列化为可 JSON 序列化的字典列表"""
    cookies_list = []
    for cookie in cookie_jar:
        cookies_list.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "port": cookie.port,
            "path": cookie.path,
            "expires": cookie.expires,
            "secure": cookie.secure,
            "rest": cookie.__dict__.get("_rest", {}),
            "version": cookie.version,
            "comment": cookie.comment,
            "comment_url": cookie.comment_url,
            "rfc2109": cookie.rfc2109,
            "discard": cookie.discard,
        })
    return cookies_list


def list_to_cookie_jar(cookies_list: list) -> RequestsCookieJar:
    """将字典列表反序列化回 CookieJar"""
    jar = RequestsCookieJar()
    for cd in cookies_list:
        cookie = create_cookie(
            name=cd["name"], value=cd["value"],
            domain=cd.get("domain", ""), port=cd.get("port", None),
            path=cd.get("path", "/"), expires=cd.get("expires", None),
            secure=cd.get("secure", False),
            rest=cd.get("rest", {"HttpOnly": None}),
            version=cd.get("version", 0), comment=cd.get("comment", None),
            comment_url=cd.get("comment_url", None),
            rfc2109=cd.get("rfc2109", False),
            discard=cd.get("discard", True),
        )
        jar.set_cookie(cookie)
    return jar


class ManagedSession:
    """统一 HTTP 会话管理 - 移植自 SDK core/session.py

    核心特性:
    1. 自动重试: 500/502/503/504 最多重试 5 次(指数退避)
    2. Cookie 管理: 支持 dict / list[dict] / CookieJar, 自动从 CASLOGC 提取 uuid/userId
    3. 代理: 手动传入优先, 否则沿用系统环境变量代理(与原 SDK 行为一致)
    """

    # 默认请求头, 模拟 Chrome 浏览器特征(降低被反爬识别的风险)
    DEFAULT_HEADERS = {
        "Accept": "*/*",
        "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="101", "Google Chrome";v="101"',
        "sec-ch-ua-mobile": "?0",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/100.0.4896.127 Safari/537.36"
        ),
        "sec-ch-ua-platform": "macOS",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    def __init__(self, cookies=None, proxies=None, headers=None) -> None:
        self.session = requests.Session()
        # 重试策略: 仅对服务端错误码重试, 指数退避
        retry = Retry(total=5, backoff_factor=0.1, raise_on_status=True,
                      status_forcelist=[500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(self.DEFAULT_HEADERS)
        if headers:
            self.session.headers.update(headers)
        # 代理优先级: 手动传入 > 系统代理自动检测
        self.proxies = proxies or urllib.request.getproxies()
        self._uuid: str | None = None
        self._user_id: str = ""
        if cookies:
            self.cookies = cookies

    @property
    def cookies(self) -> RequestsCookieJar:
        return self.session.cookies

    @cookies.setter
    def cookies(self, value) -> None:
        """设置 Cookie(dict/list[dict]/CookieJar), 并从 CASLOGC 提取 uuid/userId"""
        if isinstance(value, dict):
            jar = cookiejar_from_dict(value)
        elif isinstance(value, list):
            jar = list_to_cookie_jar(value)
        else:
            jar = value
        self.session.cookies.clear()
        for c in jar:
            self.session.cookies.set_cookie(c)
        try:
            flat = jar.get_dict()
            cas_log_c = flat.get("CASLOGC") or flat.get("cas_log_c", "")
            if cas_log_c:
                cas_data = json.loads(unquote_plus(cas_log_c))
                self._uuid = cas_data.get("uuid")
                self._user_id = str(cas_data.get("userId", ""))
        except (KeyError, json.JSONDecodeError):
            logger.warning("无法从 Cookie 提取 uuid(CASLOGC 缺失或格式异常)")
        # 设置退出记录标记 Cookie(通知服务端已建立会话)
        if self._uuid:
            self.session.cookies.set(f"exitRecod_{self._uuid}", "2")

    @property
    def uuid(self) -> str | None:
        return self._uuid

    def get_cas_user_id(self) -> str:
        """从当前 cookies 直接读取 CAS userId(登录后由 requests 直写底层 Cookie)"""
        try:
            flat = self.session.cookies.get_dict()
            cas = flat.get("CASLOGC") or flat.get("cas_log_c", "")
            if cas:
                return str(json.loads(unquote_plus(cas)).get("userId", ""))
        except Exception:
            pass
        return ""

    @property
    def proxies(self) -> dict:
        return self.session.proxies

    @proxies.setter
    def proxies(self, value: dict) -> None:
        self.session.proxies.update(value)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        if "proxies" not in kwargs or kwargs.get("proxies") is None:
            kwargs["proxies"] = self.proxies
        if "timeout" not in kwargs:
            kwargs["timeout"] = 10
        logger.debug("%s %s", method.upper(), url)
        return self.session.request(method, url, **kwargs)

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def fork(self) -> "ManagedSession":
        """创建共享 Cookie/代理的子会话(并发场景用)"""
        return ManagedSession(cookies=self.cookies, proxies=dict(self.proxies),
                              headers=dict(self.session.headers))

    def close(self) -> None:
        self.session.close()


# ============ 客户端基类 ============

class ZhsAPIClientBase:
    """智慧树 API 客户端基类(模板方法: 准备请求 → 发送 → 解析响应)

    智慧树系大部分接口使用 {"code": ..., "message": ...} 响应格式;
    code == -12 表示触发人机验证(抛出 ZhsCaptchaError)。
    """

    # 智慧树 API 约定的"成功"状态码
    EXPECTED_OK_CODES: tuple = (0, 200)

    def __init__(self, session: ManagedSession) -> None:
        self._session = session

    def _prepare_request(self, method: str, url: str, data: dict | None = None):
        """子类实现: 加工 URL 与请求参数"""
        raise NotImplementedError

    def _parse_response(self, resp: requests.Response):
        """默认解析: 校验 code 字段(-12=验证码; 其他非成功码抛 API 异常)"""
        body = resp.json()
        if not isinstance(body, dict):
            return body
        code = body.get("code")
        if code is not None and code not in self.EXPECTED_OK_CODES:
            msg = body.get("message") or json.dumps(body, ensure_ascii=False)
            logger.error("API error %s: %s", code, msg)
            if code == -12:
                raise ZhsCaptchaError(msg)
            raise ZhsAPIError(f"[{code}] {msg}")
        return body

    def request(self, method: str, url: str, data: dict | None = None):
        url, kwargs = self._prepare_request(method, url, data)
        resp = self._session.request(method, url, **kwargs)
        return self._parse_response(resp)

    def get(self, url: str, data: dict | None = None):
        return self.request("GET", url, data)

    def post(self, url: str, data: dict | None = None):
        return self.request("POST", url, data)


# ============ Hike(共享课) API ============

# Hike saveStuStudyRecord 的 MD5 签名盐值(逆向结果, 详见 SDK README 后记)
SALT = "o6xpt3b#Qy$Z"


def sign(p: dict) -> str:
    """生成 Hike 教学 API 所需的 MD5 签名

    签名规则(逆向): SALT + 参数按固定顺序拼接 + uuid 尾部重复, 再取 MD5。
    顺序: uuid, courseId, fileId, studyTotalTime, startDate,
          endDate, endWatchTime, startWatchTime, uuid
    所有参数必须为字符串。
    """
    raw = (SALT + p["uuid"] + p["courseId"] + p["fileId"]
           + p["studyTotalTime"] + p["startDate"] + p["endDate"]
           + p["endWatchTime"] + p["startWatchTime"] + p["uuid"])
    return md5(raw.encode()).hexdigest()


class HikeAPIClient(ZhsAPIClientBase):
    """Hike 子系统 API 客户端(共享课)

    接口: 课程列表 / 资源菜单树 / 文件播放信息 / 学习记录保存(带签名);
    所有请求通过 URL 参数传递, 每次自动附加毫秒时间戳 ``_`` 防缓存。
    """

    def __init__(self, session: ManagedSession, uuid: str | None = None) -> None:
        super().__init__(session)
        self._uuid = uuid or self._extract_uuid()

    def _extract_uuid(self) -> str:
        try:
            flat = self._session.session.cookies.get_dict()
            cas = flat.get("CASLOGC") or flat.get("cas_log_c", "")
            if cas:
                return str(json.loads(unquote_plus(cas)).get("uuid", ""))
        except Exception:
            pass
        return ""

    @property
    def uuid(self) -> str:
        if not self._uuid:
            self._uuid = self._extract_uuid()
        return self._uuid or ""

    def _prepare_request(self, method, url, data=None):
        if data is None:
            return url, {}
        params = dict(data)
        if "_" not in params:
            params["_"] = int(time.time() * 1000)
        if method.upper() == "POST":
            return url, {"data": params}
        return url, {"params": params}

    def _parse_response(self, resp):
        # Hike 部分接口响应格式不统一(rt/code), 直接返回 JSON 由调用方处理
        return resp.json()

    def _signed_params(self, course_id, file_id, study_total_time,
                       start_watch_time, end_watch_time, start_date, end_date):
        """构建带 MD5 签名的请求参数(值全部转字符串)"""
        params = {
            "uuid": self.uuid,
            "courseId": str(course_id),
            "fileId": str(file_id),
            "studyTotalTime": str(study_total_time),
            "startWatchTime": str(start_watch_time),
            "endWatchTime": str(end_watch_time),
            "startDate": str(start_date),
            "endDate": str(end_date),
        }
        params["signature"] = sign(params)
        return params

    def get_course_list(self) -> list:
        """获取进行中的共享课列表"""
        url = "https://hikeservice.zhihuishu.com/student/course/aided/getMyCourseList"
        params = {
            "uuid": self._uuid or "",
            "data": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + "000Z",
        }
        body = self.get(url, params)
        return (body.get("result", {}) or {}).get("startInngcourseList", [])

    def query_resource_menu_tree(self, course_id: str) -> Any:
        """查询课程资源菜单树(实际数据在 rt 字段)"""
        url = ("https://studyresources.zhihuishu.com/studyResources/"
               "stuResouce/queryResourceMenuTree")
        return self.get(url, {"courseId": course_id}).get("rt", {})

    def stu_view_file(self, course_id: str, file_id: str) -> Any:
        """标记开始观看文件(返回播放信息)"""
        url = ("https://studyresources.zhihuishu.com/studyResources/"
               "stuResouce/stuViewFile")
        return self.get(url, {"courseId": course_id, "fileId": file_id}).get("rt", {})

    def save_study_record(self, course_id, file_id, played_time,
                          prev_time, start_date) -> int:
        """保存学习记录并返回服务端确认的学习时长(秒)"""
        url = "https://hike-teaching.zhihuishu.com/stuStudy/saveStuStudyRecord"
        params = self._signed_params(
            course_id=course_id, file_id=file_id,
            study_total_time=played_time - prev_time,
            start_watch_time=prev_time, end_watch_time=played_time,
            start_date=start_date, end_date=int(time.time() * 1000),
        )
        body = self.get(url, params)
        rt = body.get("rt")
        if rt is None:
            logger.warning("saveStuStudyRecord 响应异常: %s", body)
            raise ZhsAPIError(f"saveStuStudyRecord returned None: {body}")
        return int(rt)


# ============ Polymas(新版 AI 课) API ============

class PolymasAPIClient(ZhsAPIClientBase):
    """Polymas 教学平台 API 客户端(cloudapi.polymas.com)

    认证: 独立 Bearer Token(ai-poly Cookie) 或 CAS Cookie(.polymas.com 域)
    Token 获取策略: 内存 → 本地文件 → CAS 单点登录 → 手动输入(兜底)
    """

    BASE = "https://cloudapi.polymas.com"

    def __init__(self, session: ManagedSession, token: str = "",
                 uid: str = "", user_nid: str = "") -> None:
        # Polymas 使用独立 requests.Session(与智慧树 CAS Cookie 认证解耦)
        self._poly_session = requests.Session()
        self._poly_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
        })
        self._zhs_session = session
        self.token = token
        self.uid = uid or "851311065"       # 默认值兜底(与原 SDK 一致)
        self.user_nid = user_nid or "u7KXVdcHzQ"

    # ── Token 管理 ────────────────────────────────────────────

    def ensure_token(self, expected_user_id: str = "") -> tuple:
        """确保拥有有效 Token, 返回 (token, uid, user_nid)

        多级获取(优先级递减): 内存 → 本地文件 → CAS SSO → 手动输入;
        全部失败抛 ZhsTokenExpired。
        """
        if self._token_is_valid() and self._uid_matches(expected_user_id):
            return self.token, self.uid, self.user_nid

        saved = self._load_saved_token()
        if saved and self._uid_matches(expected_user_id, saved):
            if self._check_token(saved["token"]):
                self.token = saved["token"]
                self.uid = saved.get("uid", self.uid)
                self.user_nid = saved.get("user_nid", self.user_nid)
                return self.token, self.uid, self.user_nid

        if saved and expected_user_id:
            logger.info("Polymas token 属于其他用户，已清除")
            self._delete_saved_token()

        token = self._cas_login()
        if token:
            self.token = token
            self._check_token(token)  # 验证并更新 uid/user_nid
            self._save_token()
            return self.token, self.uid, self.user_nid

        token = self._manual_token_prompt()
        if not token:
            raise ZhsTokenExpired("无法获取 Polymas token(自动获取失败且无人工输入)")
        self.token = token
        self._save_token()
        return self.token, self.uid, self.user_nid

    def _uid_matches(self, expected: str, saved: dict | None = None) -> bool:
        """校验当前/保存的 token uid 是否属于期望用户(防换号串号)"""
        if not expected:
            return True
        uid = (saved or {}).get("uid") if saved else self.uid
        return not uid or uid == expected

    def _token_is_valid(self) -> bool:
        if not self.token:
            return False
        return self._check_token(self.token)

    def _check_token(self, token: str) -> bool:
        """向服务端验证 Token(CAS 模式用 _poly_session 的 Cookie 验证)"""
        try:
            if token == "cas-auth":
                r = self._poly_session.get(
                    f"{self.BASE}/teachingCenterAi/user/getLoginUserInfo", timeout=10)
            else:
                s = requests.Session()
                s.headers.update({"Authorization": token})
                s.cookies.update({"ai-poly": token})
                r = s.get(
                    f"{self.BASE}/teachingCenterAi/user/getLoginUserInfo", timeout=10)
            if r.status_code == 200 and r.json().get("code") == "200":
                data = r.json().get("data", {})
                self.uid = str(data.get("zhsUid", self.uid))
                self.user_nid = str(data.get("userId", self.user_nid))
                return True
        except Exception:
            pass
        return False

    def _load_saved_token(self) -> dict | None:
        path = POLYMAS_TOKEN_FILE
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _delete_saved_token(self) -> None:
        path = POLYMAS_TOKEN_FILE
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _save_token(self) -> None:
        try:
            os.makedirs(os.path.dirname(POLYMAS_TOKEN_FILE), exist_ok=True)
            with open(POLYMAS_TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump({"token": self.token, "uid": self.uid,
                           "user_nid": self.user_nid,
                           "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                          f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _cas_login(self) -> str | None:
        """通过 CAS 会话设置 Polymas 认证(CASLOGC/CASTGC/jt-cas 复制到 .polymas.com 域)"""
        cas_session = self._zhs_session.session
        cas_cookies: dict = {}
        try:
            flat = cas_session.cookies.get_dict()
            for name in ("CASLOGC", "CASTGC", "jt-cas"):
                val = flat.get(name, "")
                if val:
                    cas_cookies[name] = val
        except Exception:
            pass
        if not cas_cookies:
            logger.debug("CAS cookies 不存在")
            return None
        for name, value in cas_cookies.items():
            try:
                self._poly_session.cookies.set_cookie(
                    create_cookie(name=name, value=value,
                                  domain=".polymas.com", path="/"))
            except Exception:
                pass
        try:
            r = self._poly_session.get(
                f"{self.BASE}/teachingCenterAi/user/getLoginUserInfo", timeout=30)
            if r.status_code == 200 and r.json().get("code") == "200":
                data = r.json().get("data", {})
                self.uid = str(data.get("zhsUid", self.uid))
                self.user_nid = str(data.get("userId", self.user_nid))
                logger.info("通过 CAS SSO 设置 Polymas 认证成功")
                return "cas-auth"
        except Exception:
            pass
        return None

    def _manual_token_prompt(self) -> str | None:
        """手动输入 Token 兜底(无交互环境直接放弃, 不阻塞)"""
        import sys
        try:
            if not sys.stdin.isatty():
                logger.warning("无交互环境, 无法手动输入 Polymas token")
                return None
        except Exception:
            return None
        print("\n无法自动获取 Polymas token。")
        print("1. 打开 https://hike-teaching-center.polymas.com/")
        print("2. 登录 → F12 → Application → Cookies → ai-poly")
        try:
            return input("粘贴 ai-poly token: ").strip() or None
        except (EOFError, KeyboardInterrupt):
            return None

    # ── 父类方法实现 ──────────────────────────────────────────

    def _prepare_request(self, method, url, data=None):
        """Polymas 风格 REST 请求: POST 用 JSON body, GET 用 URL 参数"""
        kwargs: dict = {}
        if data is not None and method.upper() == "POST":
            kwargs["json"] = data
        elif data is not None:
            kwargs["params"] = data
        return url, kwargs

    def _parse_response(self, resp):
        return resp.json()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """使用独立 _poly_session 发送请求(每次自动注入 Token/Cookie)"""
        if self.token and self.token != "cas-auth":
            self._poly_session.headers.update({"Authorization": self.token})
            self._poly_session.cookies.update({"ai-poly": self.token})
        if "timeout" not in kwargs:
            kwargs["timeout"] = 15
        return self._poly_session.request(method, url, **kwargs)

    # ── 业务接口 ──────────────────────────────────────────────

    def get_courses(self, school_id: str = "sGDwgZaYFK", status: int = 2) -> list:
        """获取学生课程列表(status: 0未开始/1进行中/2已结束/3全部)"""
        url = f"{self.BASE}/student-course/student/index/queryStudentCourse"
        data = {"keyword": "", "term": "", "schoolId": school_id,
                "status": status, "page": 1, "size": 24}
        resp = self._request("POST", url, json=data)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success"):
                course_list = result.get("data", {}).get("list", [])
                logger.info("Polymas get_courses: %d 门课程 (status=%d)",
                            len(course_list), status)
                return course_list
            logger.warning("Polymas get_courses 失败: code=%s msg=%s",
                           result.get("code"), result.get("msg", ""))
        else:
            logger.warning("Polymas get_courses HTTP %s: %s",
                           resp.status_code, resp.text[:200])
        return []

    def get_course_structure(self, course_id: str, class_id: str) -> tuple:
        """获取课程目录树(先查图书馆文件夹ID, 再查完整目录树)"""
        url = f"{self.BASE}/teacher-course/library/course/findStudyLibraryByCourseId"
        try:
            r = self._request("GET", f"{url}?courseId={course_id}")
            lib_id = course_id
            if r.status_code == 200 and r.json().get("success"):
                lib_id = str(r.json().get("data", course_id))
        except Exception:
            lib_id = course_id
        tree_url = f"{self.BASE}/student-course/study/student/resource/queryTree"
        resp = self._request("POST", tree_url,
                             json={"libraryFolderId": lib_id, "classId": class_id})
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success"):
                return result.get("data", []), lib_id
        return [], lib_id

    def report_progress(self, resource_id, course_id, start_time,
                        end_time, study_time):
        """上报视频学习进度, 返回完成率(失败返回 None)"""
        now = datetime.now()
        data = {
            "resourceId": resource_id,
            "courseId": course_id,
            "startWatchTime": start_time,
            "endWatchTime": end_time,
            "studyTotalTime": study_time,
            "startDate": (now - timedelta(seconds=study_time)).strftime("%Y-%m-%d %H:%M:%S"),
            "endDate": now.strftime("%Y-%m-%d %H:%M:%S"),
            "clientType": "Windows",
        }
        url = f"{self.BASE}/student-course/study/student/record/report"
        resp = self._request("POST", url, json=data)
        if resp.status_code == 200:
            try:
                r = resp.json()
            except ValueError:
                logger.warning("Polymas report_progress 返回非 JSON: %s", resp.text[:200])
                return None
            if r.get("success"):
                return (r.get("data") or {}).get("completeRate", 0)
        else:
            logger.warning("Polymas report_progress HTTP %s: %s",
                           resp.status_code, resp.text[:200])
        return None

    def event_track(self, resource_id, course_id, class_id) -> None:
        """学习事件追踪(即发即忘, 失败不影响主流程)"""
        data = {"eventTrackingList": [{
            "courseId": course_id,
            "term": 20262,
            "eventCode": "online_learning.study_resource",
            "userType": "student",
            "properties": {
                "studyTime": datetime.now().strftime("%Y/%m/%d %H:%M"),
                "id": resource_id,
                "classId": class_id,
                "userNid": self.user_nid,
            },
        }]}
        url = f"{self.BASE}/event-tracking/api/eventTracking/send"
        try:
            self._request("POST", url, json=data)
        except Exception:
            pass


# ============ 登录 ============

def login_password(session: ManagedSession, username: str, password: str) -> None:
    """智慧树密码登录

    三阶段: 访问登录页建会话 → 校验账号密码 → 完成登录(Cookie 落地)。
    - status == -2: 账号或密码错误
    - status == -4: 触发验证码(抛 ZhsCaptchaError)
    - status == -9: 需要短信验证
    - needAuth: 需要额外安全验证(需先用浏览器登录一次)
    """
    login_page = ("https://passport.zhihuishu.com/login"
                  "?service=https://onlineservice-api.zhihuishu.com/login/gologin")
    valid_url = "https://passport.zhihuishu.com/user/validateAccountAndPassword"
    check_url = ("https://appcomm-user.zhihuishu.com/app-commserv-user/userInfo/checkNeedAuth")

    # 第一步: 访问登录页, 获取服务端会话
    session.get(login_page)
    session.session.headers.update({
        "Origin": "https://passport.zhihuishu.com",
        "Referer": login_page,
    })

    # 第二步: 校验账号密码
    user_info = _api_query(session, valid_url,
                           {"account": username, "password": password})
    status = user_info.get("status")
    if status == -2:
        raise ZhsAuthError("用户名或密码错误")
    if status == -4:
        raise ZhsCaptchaError("多次尝试失败，需要验证码")
    if status == -9:
        raise ZhsAuthError("账户需要短信验证")

    uid = user_info.get("uuid")
    pwd = user_info.get("pwd")

    # 第三步: 检查是否需要额外安全验证(如异地登录检测)
    need_auth = _api_query(session, check_url, {"uuid": uid}) \
        .get("rt", {}).get("needAuth", False)
    if need_auth:
        raise ZhsAuthError("账户需要额外验证，请先使用浏览器登录一次")

    # 第四步: 使用凭据完成最终登录
    session.get(login_page, params={"account": username, "pwd": pwd, "validate": 0})
    if not session.cookies:
        raise ZhsAuthError("登录后未获得 Cookie")
    logger.info("密码登录成功")


def _api_query(session: ManagedSession, url: str, data: dict) -> dict:
    """认证接口通用 POST(固定 Origin/Referer, 失败返回空字典)"""
    session.session.headers.update({
        "Origin": "https://passport.zhihuishu.com",
        "Referer": "https://passport.zhihuishu.com/",
    })
    resp = session.post(url, data=data)
    try:
        return resp.json()
    except ValueError:
        return {}
