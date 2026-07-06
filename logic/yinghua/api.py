# -*- coding: utf-8 -*-
"""
英华学堂 API 接口层 - 对应 Go 项目的 api/yinghua/YingHuaApi.go
使用 httpx 实现所有 HTTP 端点
"""
import os
import re
import random
import time
from typing import Optional, Tuple, List, Dict, Any

from logic.core.http_client import HttpClient
from logic.yinghua.models import YingHuaUserCache
from utils.log import log_print, INFO, DEBUG, BoldRed, Default


def _build_client(cache: YingHuaUserCache) -> HttpClient:
    """根据 UserCache 构建 HTTP 客户端"""
    proxy = cache.proxy_ip if cache.ip_proxy_sw else None
    client = HttpClient(proxy_ip=proxy, verify_ssl=False, timeout=30.0)
    if cache.cookie_dict:
        client.load_cookies(cache.cookie_dict)
    return client


# ============ 登录相关 ============

def verification_code_api(cache: YingHuaUserCache, retry: int = 10) -> Tuple[str, str]:
    """
    获取验证码图片
    返回 (文件路径, Set-Cookie字符串)
    """
    if retry < 0:
        return "", ""
    r = f"{random.random():.16f}"
    url = f"{cache.pre_url}/service/code?r={r}"
    client = _build_client(cache)
    try:
        img_bytes, resp = client.get_image(url, retry=retry)
        if img_bytes is None or resp is None:
            return "", ""
        # 保存验证码图片
        os.makedirs("./assets/code/", exist_ok=True)
        chars = "0123456789abcdefABCDEF"
        code_file = "code" + "".join(random.choices(chars, k=11)) + ".png"
        file_path = f"./assets/code/{code_file}"
        with open(file_path, "wb") as f:
            f.write(img_bytes)
        # 保存 cookie
        if resp.cookies:
            for name, value in resp.cookies.items():
                client.set_cookie(name, value)
                cache.cookie_dict[name] = value
        set_cookie = resp.headers.get("set-cookie", "")
        cache.cookie = set_cookie
        return file_path, set_cookie
    except Exception as e:
        log_print(DEBUG, f"获取验证码失败: {e}")
        return "", ""
    finally:
        client.close()


def login_api(cache: YingHuaUserCache, retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    登录接口
    POST {PreUrl}/user/login.json
    """
    if retry < 0:
        return "", None
    url = f"{cache.pre_url}/user/login.json"
    data = {
        "username": cache.account,
        "password": cache.password,
        "code": cache.ver_code,
        "redirect": cache.pre_url,
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        # 保存登录会话 Cookie
        if resp is not None:
            for name, value in client.cookies.items():
                cache.cookie_dict[name] = value
        return body, resp
    finally:
        client.close()


# ============ 保活 ============

def keep_alive_api(cache: YingHuaUserCache, retry: int = 8) -> str:
    """
    登录心跳保活
    POST {PreUrl}/api/online.json
    """
    url = f"{cache.pre_url}/api/online.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "token": cache.token,
    }
    client = _build_client(cache)
    try:
        body, _ = client.post_form(url, data, use_multipart=True, retry=retry)
        return body
    finally:
        client.close()


# ============ 课程相关 ============

def course_list_api(cache: YingHuaUserCache, retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    拉取课程列表
    POST {PreUrl}/api/course/list.json
    """
    url = f"{cache.pre_url}/api/course/list.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "type": "0",
        "token": cache.token,
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def course_detail_api(cache: YingHuaUserCache, course_id: str,
                      retry: int = 30) -> Tuple[str, Optional[Any]]:
    """
    获取课程详细信息
    POST {PreUrl}/api/course/detail.json
    """
    url = f"{cache.pre_url}/api/course/detail.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "courseId": course_id,
        "token": cache.token,
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def course_vide_list_api(cache: YingHuaUserCache, course_id: str,
                         retry: int = 30) -> Tuple[str, Optional[Any]]:
    """
    对应课程的视频列表（接口一）
    POST {PreUrl}/api/course/chapter.json
    """
    url = f"{cache.pre_url}/api/course/chapter.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "token": cache.token,
        "courseId": course_id,
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


# ============ 视频学习 ============

def submit_study_time_api(cache: YingHuaUserCache, node_id: str,
                          study_id: str, study_time: int,
                          retry: int = 20) -> Tuple[str, Optional[Any]]:
    """
    提交学时
    POST {PreUrl}/api/node/study.json
    """
    url = f"{cache.pre_url}/api/node/study.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "nodeId": node_id,
        "token": cache.token,
        "terminal": "Android",
        "studyTime": str(study_time),
        "studyId": study_id,
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def vide_study_time_api(cache: YingHuaUserCache, node_id: str,
                        retry: int = 8) -> str:
    """
    获取单个视频的学习进度
    POST {PreUrl}/api/node/video.json
    """
    url = f"{cache.pre_url}/api/node/video.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "nodeId": node_id,
        "token": cache.token,
    }
    client = _build_client(cache)
    try:
        body, _ = client.post_form(url, data, use_multipart=True, retry=retry)
        return body
    finally:
        client.close()


def vide_watch_recode_api(cache: YingHuaUserCache, course_id: str,
                          page: int, retry: int = 20) -> Tuple[str, Optional[Any]]:
    """
    获取指定课程视频观看记录（接口二）
    POST {PreUrl}/api/record/video.json
    """
    url = f"{cache.pre_url}/api/record/video.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "token": cache.token,
        "courseId": course_id,
        "page": str(page),
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def video_watch_recode_pc_api(cache: YingHuaUserCache, course_id: str,
                              page: int, retry: int = 20) -> Tuple[str, Optional[Any]]:
    """
    获取指定课程视频观看记录（接口三，PC端）
    GET {PreUrl}/user/study_record/video.json?courseId=...
    """
    ts = int(time.time())
    url = (f"{cache.pre_url}/user/study_record/video.json"
           f"?courseId={course_id}&_={ts}&page={page}")
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()


# ============ 考试相关 ============

def exam_detail_api(cache: YingHuaUserCache, node_id: str,
                    retry: int = 20) -> Tuple[str, Optional[Any]]:
    """
    获取考试信息
    POST {PreUrl}/api/node/exam.json?nodeId=...
    """
    url = f"{cache.pre_url}/api/node/exam.json?nodeId={node_id}"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "nodeId": node_id,
        "token": cache.token,
        "terminal": "Android",
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def start_exam_api(cache: YingHuaUserCache, course_id: str,
                   node_id: str, exam_id: str,
                   retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    开始考试
    GET {PreUrl}/api/exam/start.json?nodeId=...&courseId=...&token=...&examId=...
    """
    url = (f"{cache.pre_url}/api/exam/start.json"
           f"?nodeId={node_id}&courseId={course_id}"
           f"&token={cache.token}&examId={exam_id}")
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()


def get_exam_topic_api(cache: YingHuaUserCache, node_id: str,
                       exam_id: str, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """
    获取考试题目（HTML格式）
    POST {PreUrl}/api/exam.json?nodeId=...&examId=...&token=...
    """
    url = (f"{cache.pre_url}/api/exam.json"
           f"?nodeId={node_id}&examId={exam_id}&token={cache.token}")
    client = _build_client(cache)
    try:
        body, resp = client.post_json(url, {}, retry=retry)
        return body, resp
    finally:
        client.close()


def submit_exam_api(cache: YingHuaUserCache, exam_id: str,
                    answer_id: str, question: Any, finish: str,
                    retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    提交考试答案/提交试卷
    POST {PreUrl}/api/exam/submit.json
    """
    url = f"{cache.pre_url}/api/exam/submit.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "examId": exam_id,
        "terminal": "Android",
        "answerId": answer_id,
        "finish": finish,
        "token": cache.token,
    }
    # 添加答案字段（可能是 answer 或 answer[]）
    if hasattr(question, 'answers') and question.answers:
        if len(question.answers) == 1:
            data["answer"] = question.answers[0]
        else:
            for i, ans in enumerate(question.answers):
                data[f"answer_{i}"] = ans
    elif isinstance(question, str):
        data["answer"] = question

    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def exam_finally_detail_api(cache: YingHuaUserCache, node_id: str,
                            exam_id: str, retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    获取考试最终详情
    GET {PreUrl}/api/exam.json?nodeId=...&examId=...&token=...
    """
    url = (f"{cache.pre_url}/api/exam.json"
           f"?nodeId={node_id}&examId={exam_id}&token={cache.token}")
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()


# ============ 作业相关 ============

def work_detail_api(cache: YingHuaUserCache, node_id: str,
                    retry: int = 20) -> Tuple[str, Optional[Any]]:
    """
    获取作业信息
    POST {PreUrl}/api/node/work.json?nodeId=...
    """
    url = f"{cache.pre_url}/api/node/work.json?nodeId={node_id}"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "nodeId": node_id,
        "token": cache.token,
        "terminal": "Android",
    }
    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def start_work_api(cache: YingHuaUserCache, course_id: str,
                   node_id: str, work_id: str,
                   retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    开始作业
    GET {PreUrl}/api/work/start.json?nodeId=...&courseId=...&token=...&workId=...
    """
    url = (f"{cache.pre_url}/api/work/start.json"
           f"?nodeId={node_id}&courseId={course_id}"
           f"&token={cache.token}&workId={work_id}")
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()


def get_work_api(cache: YingHuaUserCache, node_id: str,
                 work_id: str, retry: int = 8) -> Tuple[str, Optional[Any]]:
    """
    获取作业题目
    POST {PreUrl}/api/work.json?nodeId=...&workId=...&token=...
    """
    url = (f"{cache.pre_url}/api/work.json"
           f"?nodeId={node_id}&workId={work_id}&token={cache.token}")
    client = _build_client(cache)
    try:
        body, resp = client.post_json(url, {}, retry=retry)
        return body, resp
    finally:
        client.close()


def submit_work_api(cache: YingHuaUserCache, work_id: str,
                    answer_id: str, question: Any, finish: str,
                    retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    提交作业答案/提交作业
    POST {PreUrl}/api/work/submit.json
    """
    url = f"{cache.pre_url}/api/work/submit.json"
    data = {
        "platform": "Android",
        "version": "1.4.8",
        "workId": work_id,
        "terminal": "Android",
        "answerId": answer_id,
        "finish": finish,
        "token": cache.token,
    }
    if hasattr(question, 'answers') and question.answers:
        if len(question.answers) == 1:
            data["answer"] = question.answers[0]
        else:
            for i, ans in enumerate(question.answers):
                data[f"answer_{i}"] = ans
    elif isinstance(question, str):
        data["answer"] = question

    client = _build_client(cache)
    try:
        body, resp = client.post_form(
            url, data, use_multipart=True, retry=retry)
        return body, resp
    finally:
        client.close()


def worked_finally_detail_api(cache: YingHuaUserCache, node_id: str,
                              work_id: str,
                              retry: int = 10) -> Tuple[str, Optional[Any]]:
    """
    获取作业最终详情
    GET {PreUrl}/api/work.json?nodeId=...&workId=...&token=...
    """
    url = (f"{cache.pre_url}/api/work.json"
           f"?nodeId={node_id}&workId={work_id}&token={cache.token}")
    client = _build_client(cache)
    try:
        body, resp = client.get(url, retry=retry)
        return body, resp
    finally:
        client.close()
