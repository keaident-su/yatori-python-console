# -*- coding: utf-8 -*-
"""
英华学堂聚合层 - 对应 Go 项目的 aggregation/yinghua/
将 API 调用组合成完整的业务操作
"""
import json
import os
import re
import sys
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

from logic.yinghua import api as yinghua_api
from logic.yinghua.models import (
    YingHuaUserCache, YingHuaCourse, YingHuaNode,
    YingHuaExam, YingHuaWork, YingHuaExamTopic, YingHuaQuestion
)
from logic.core.models import safe_json_parse, json_get
from logic.core.ai_client import ai_problem_message
from logic.core.external_que import search_api_que
from utils.log import log_print, INFO, DEBUG, Green, Red, BoldRed, BoldGreen, Yellow, Default


def _try_ocr_verification(image_path: str) -> str:
    """
    尝试 OCR 识别验证码 - 简化实现
    在实际使用中可对接 ddddocr 或其他 OCR 服务
    """
    try:
        import ddddocr
        ocr = ddddocr.DdddOcr(show_ad=False)
        with open(image_path, "rb") as f:
            img_bytes = f.read()
        result = ocr.classification(img_bytes)
        return result
    except ImportError:
        # 如果 ddddocr 未安装，使用简单模拟（实际需要安装）
        log_print(INFO, Yellow, "ddddocr 未安装，请手动安装: pip install ddddocr")
        return ""
    except Exception as e:
        log_print(INFO, BoldRed, f"OCR 识别失败: {e}")
        return ""


# ============ 登录聚合 ============

def ying_hua_login_action(cache: YingHuaUserCache) -> Optional[Exception]:
    """
    登录聚合操作 - 对应 YingHuaLoginAction
    包含：获取验证码 -> OCR识别 -> 登录 -> 设置Token
    """
    max_attempts = 20
    for attempt in range(max_attempts):
        # 获取验证码
        path, _ = yinghua_api.verification_code_api(cache, retry=10)
        if not path:
            return Exception("无法正常获取对应网站验证码，请检查对应url是否正常")

        # OCR 识别验证码
        code_result = _try_ocr_verification(path)
        if os.path.exists(path):
            os.remove(path)

        cache.ver_code = code_result

        # 执行登录
        json_str, _ = yinghua_api.login_api(cache, retry=10)
        log_print(DEBUG, f"[{cache.account}] LoginAction---{json_str}")

        data = safe_json_parse(json_str)
        if data is None:
            continue

        msg = data.get("msg", "")

        if msg == "验证码有误！":
            continue
        elif ">选择学校<" in json_str:
            return Exception("请填写正确的url链接，英华的url可能首页和登录后的是不一样的，以登录后的url为准。")
        elif "redirect" not in data:
            if msg:
                return Exception(msg)
            continue

        # 提取 Token 和 Sign
        redirect_url = data.get("redirect", "")
        token_match = re.search(r'token=([^&]+)', redirect_url)
        sign_match = re.search(r'&sign=(.+)', redirect_url)

        if token_match:
            cache.token = token_match.group(1)
        if sign_match:
            cache.sign = sign_match.group(1)

        return None  # 登录成功

    return Exception("登录重试次数过多")


def login_timeout_afresh_action(cache: YingHuaUserCache, back_json: str):
    """超时重登逻辑 - 对应 LoginTimeoutAfreshAction"""
    if "账号登录超时，请重新登录" not in back_json:
        return
    log_print(INFO, f"[{cache.account}] ", BoldRed, "检测到登录超时，正在进行重新登录逻辑...")
    err = ying_hua_login_action(cache)
    if err:
        log_print(INFO, f"[{cache.account}] ", BoldRed, "超时重登失败")
        sys.exit(0)
    log_print(INFO, f"[{cache.account}] ", BoldGreen, "超时重登成功")


# ============ 课程聚合 ============

def course_list_action(cache: YingHuaUserCache) -> Tuple[List[YingHuaCourse], Optional[Exception]]:
    """
    课程列表 - 对应 CourseListAction
    返回 (课程列表, 错误)
    """
    list_json, _ = yinghua_api.course_list_api(cache, retry=10)
    if not list_json:
        return [], Exception("获取数据失败: 响应为空")

    log_print(DEBUG, f"[{cache.account}] CourseListAction---{list_json}")
    login_timeout_afresh_action(cache, list_json)

    data = safe_json_parse(list_json)
    if data is None or data.get("msg") != "获取数据成功":
        return [], Exception(f"获取数据失败: {list_json}")

    courses = []
    result_list = json_get(data, "result", "list", default=[])
    if not isinstance(result_list, list):
        return courses, None

    for item in result_list:
        if not isinstance(item, dict):
            continue
        try:
            start_date = None
            end_date = None
            sd = item.get("startDate", "")
            ed = item.get("endDate", "")
            if sd:
                try:
                    start_date = datetime.strptime(sd, "%Y-%m-%d")
                except ValueError:
                    pass
            if ed:
                try:
                    end_date = datetime.strptime(ed, "%Y-%m-%d")
                except ValueError:
                    pass

            course = YingHuaCourse(
                id=str(int(item.get("id", 0))),
                name=item.get("name", ""),
                mode=int(item.get("mode", 0)),
                progress=float(item.get("progress", 0)),
                start_date=start_date,
                end_date=end_date,
                video_count=int(item.get("videoCount", 0)),
                video_learned=int(item.get("videoLearned", 0)),
            )
            courses.append(course)
        except (ValueError, TypeError, KeyError) as e:
            log_print(DEBUG, f"解析课程数据失败: {e}")
            continue

    return courses, None


def course_detail_action(cache: YingHuaUserCache,
                         course_id: str) -> Tuple[Optional[YingHuaCourse], Optional[Exception]]:
    """获取指定课程的信息 - 对应 CourseDetailAction"""
    detail_json, _ = yinghua_api.course_detail_api(cache, course_id, retry=30)
    if not detail_json:
        return None, Exception("获取数据失败: 响应为空")

    login_timeout_afresh_action(cache, detail_json)

    data = safe_json_parse(detail_json)
    if data is None or data.get("msg") != "获取数据成功":
        return None, Exception(f"获取数据失败: {detail_json}")

    obj = json_get(data, "result", "data", default={})
    if not isinstance(obj, dict):
        return None, None

    try:
        start_date = None
        end_date = None
        sd = obj.get("startDate", "")
        ed = obj.get("endDate", "")
        if sd:
            try:
                start_date = datetime.strptime(sd, "%Y-%m-%d")
            except ValueError:
                pass
        if ed:
            try:
                end_date = datetime.strptime(ed, "%Y-%m-%d")
            except ValueError:
                pass

        return YingHuaCourse(
            id=str(int(obj.get("id", 0))),
            name=obj.get("name", ""),
            mode=int(obj.get("mode", 0)),
            progress=float(obj.get("progress", 0)),
            start_date=start_date,
            end_date=end_date,
            video_count=int(obj.get("videoCount", 0)),
            video_learned=int(obj.get("videoLearned", 0)),
        ), None
    except (ValueError, TypeError, KeyError) as e:
        return None, Exception(f"解析课程详情失败: {e}")


# ============ 视频列表聚合 ============

def videos_list_action(cache: YingHuaUserCache,
                       course: YingHuaCourse) -> Tuple[List[YingHuaNode], Optional[Exception]]:
    """
    获取课程的视频列表 - 对应 VideosListAction
    综合三个接口的数据
    """
    video_list: List[YingHuaNode] = []
    video_index: Dict[str, int] = {}

    # 接口一：获取章节节点信息
    list_json, _ = yinghua_api.course_vide_list_api(cache, course.id, retry=30)
    if not list_json:
        return [], Exception("获取数据失败：响应为空")

    login_timeout_afresh_action(cache, list_json)
    data = safe_json_parse(list_json)
    if data is None or data.get("msg") != "获取数据成功":
        return [], Exception(f"获取数据失败：{list_json}")

    result_list = json_get(data, "result", "list", default=[])
    if isinstance(result_list, list):
        for chapter in result_list:
            if not isinstance(chapter, dict):
                continue
            node_list = chapter.get("nodeList", [])
            if not isinstance(node_list, list):
                continue
            for node in node_list:
                if not isinstance(node, dict):
                    continue
                try:
                    vd = int(node.get("videoDuration", "0") or "0")
                    unlock_time = None
                    ut = node.get("unlockTime", "")
                    if ut:
                        try:
                            unlock_time = datetime.strptime(
                                ut, "%Y-%m-%d %H:%M")
                        except ValueError:
                            pass
                    yinghua_node = YingHuaNode(
                        id=str(int(node.get("id", 0))),
                        name=node.get("name", ""),
                        video_duration=vd,
                        node_lock=int(node.get("nodeLock", 0)),
                        unlock_time=unlock_time,
                        tab_video=bool(node.get("tabVideo", False)),
                        tab_file=bool(node.get("tabFile", False)),
                        tab_exam=bool(node.get("tabExam", False)),
                        tab_work=bool(node.get("tabWork", False)),
                    )
                    video_list.append(yinghua_node)
                    video_index[yinghua_node.id] = len(video_list) - 1
                except (ValueError, TypeError) as e:
                    log_print(DEBUG, f"解析节点数据失败: {e}")
                    continue

    # 接口二：获取视频观看进度
    signal_set = set()
    last_page = 999
    for page in range(1, last_page + 1):
        page_json, _ = yinghua_api.vide_watch_recode_api(
            cache, course.id, page, retry=20)
        if not page_json:
            break
        page_data = safe_json_parse(page_json)
        if page_data is None:
            break

        page_count = json_get(page_data, "result", "pageInfo", "pageCount")
        if page_count is not None:
            last_page = int(page_count)

        items = json_get(page_data, "result", "list", default=[])
        if not isinstance(items, list) or len(items) == 0:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            node_id = str(int(item.get("id", 0)))
            if node_id in signal_set:
                break
            signal_set.add(node_id)
            idx = video_index.get(node_id)
            if idx is not None:
                video_list[idx].course_id = str(int(item.get("courseId", 0)))
                video_list[idx].progress = float(item.get("progress", 0))
                video_list[idx].viewed_duration = int(
                    item.get("viewedDuration", 0))
                video_list[idx].state = int(item.get("state", 0))

    # 接口三：PC端获取错误信息（标红检测）
    signal_set2 = set()
    last_page2 = 999
    for page in range(1, last_page2 + 1):
        pc_json, _ = yinghua_api.video_watch_recode_pc_api(
            cache, course.id, page, retry=20)
        if not pc_json:
            break
        pc_data = safe_json_parse(pc_json)
        if pc_data is None:
            break

        page_count = json_get(pc_data, "pageInfo", "pageCount")
        if page_count is not None:
            last_page2 = int(page_count)

        items = json_get(pc_data, "list", default=[])
        if not isinstance(items, list) or len(items) == 0:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("id", ""))
            if node_id in signal_set2:
                return video_list, None
            signal_set2.add(node_id)
            idx = video_index.get(node_id)
            if idx is not None:
                video_list[idx].error_code = int(item.get("error", 0))
                em = item.get("errorMessage")
                if em is not None:
                    video_list[idx].error_message = str(em)

    return video_list, None


# ============ 提交学时聚合 ============

def submit_study_time_action(cache: YingHuaUserCache, node_id: str,
                             study_id: str, study_time: int) -> Tuple[str, Optional[Exception]]:
    """提交学时 - 对应 SubmitStudyTimeAction"""
    sub, _ = yinghua_api.submit_study_time_api(
        cache, node_id, study_id, study_time, retry=20)
    if not sub:
        return "", Exception("提交学时失败: 响应为空")
    return sub, None


# ============ 考试聚合 ============

def exam_detail_action(cache: YingHuaUserCache,
                       node_id: str) -> Tuple[List[YingHuaExam], Optional[Exception]]:
    """获取考试节点信息 - 对应 ExamDetailAction"""
    json_str, _ = yinghua_api.exam_detail_api(cache, node_id, retry=20)
    if not json_str:
        return [], Exception("获取数据失败")

    login_timeout_afresh_action(cache, json_str)
    data = safe_json_parse(json_str)
    if data is None or data.get("msg") != "获取数据成功":
        return [], Exception(f"获取数据失败: {json_str}")

    exams = []
    items = json_get(data, "result", "list", default=[])
    if not isinstance(items, list):
        return exams, None

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            start_time = None
            end_time = None
            st = item.get("startTime", "")
            et = item.get("endTime", "")
            if st:
                try:
                    start_time = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            if et:
                try:
                    end_time = datetime.strptime(et, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass

            url_str = item.get("url", "")
            exam_id_match = re.search(r'examId=([^&]+)', url_str)
            exam_id = exam_id_match.group(1) if exam_id_match else ""

            exam = YingHuaExam(
                id=str(int(item.get("id", 0))),
                exam_id=exam_id,
                node_id=str(int(item.get("nodeId", 0))),
                course_id=str(int(item.get("courseId", 0))),
                title=item.get("title", ""),
                start_time=start_time,
                end_time=end_time,
                limited_time=float(item.get("limitedTime", 0)),
                score=float(item.get("score", 0)),
            )
            exams.append(exam)
        except (ValueError, TypeError) as e:
            log_print(DEBUG, f"解析考试数据失败: {e}")
            continue

    return exams, None


# ============ 作业聚合 ============

def work_detail_action(cache: YingHuaUserCache,
                       node_id: str) -> Tuple[List[YingHuaWork], Optional[Exception]]:
    """获取作业节点信息 - 对应 WorkDetailAction"""
    json_str, _ = yinghua_api.work_detail_api(cache, node_id, retry=20)
    if not json_str:
        return [], Exception("获取数据失败")

    login_timeout_afresh_action(cache, json_str)
    data = safe_json_parse(json_str)
    if data is None or data.get("msg") != "获取数据成功":
        return [], Exception(f"获取数据失败: {json_str}")

    works = []
    items = json_get(data, "result", "list", default=[])
    if not isinstance(items, list):
        return works, None

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            start_time = None
            end_time = None
            st = item.get("startTime", "")
            et = item.get("endTime", "")
            if st:
                try:
                    start_time = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            if et:
                try:
                    end_time = datetime.strptime(et, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass

            url_str = item.get("url", "")
            work_id_match = re.search(r'workId=([^&]+)', url_str)
            work_id = work_id_match.group(1) if work_id_match else ""

            work = YingHuaWork(
                id=str(int(item.get("id", 0))),
                work_id=work_id,
                node_id=str(int(item.get("nodeId", 0))),
                course_id=str(int(item.get("courseId", 0))),
                title=item.get("title", ""),
                start_time=start_time,
                end_time=end_time,
                score=float(item.get("score", 0)),
                allow=int(item.get("allow", 0)),
                frequency=int(item.get("frequency", 0)),
            )
            works.append(work)
        except (ValueError, TypeError) as e:
            log_print(DEBUG, f"解析作业数据失败: {e}")
            continue

    return works, None


# ============ 分数查询 ============

def exam_finally_score_action(cache: YingHuaUserCache,
                              exam: YingHuaExam) -> Tuple[float, Optional[Exception]]:
    """获取考试最终分数 - 对应 ExamFinallyScoreAction"""
    json_str, _ = yinghua_api.exam_finally_detail_api(
        cache, exam.node_id, exam.exam_id, retry=10)
    if not json_str:
        return 0.0, Exception("获取考试分数失败")
    data = safe_json_parse(json_str)
    if data is None:
        return 0.0, Exception("解析考试分数失败")
    score = json_get(data, "result", "score", default=0)
    return float(score), None


def worked_finally_score_action(cache: YingHuaUserCache,
                                work: YingHuaWork) -> Tuple[float, Optional[Exception]]:
    """获取作业最终分数 - 对应 WorkedFinallyScoreAction"""
    json_str, _ = yinghua_api.worked_finally_detail_api(
        cache, work.node_id, work.work_id, retry=10)
    if not json_str:
        return 0.0, Exception("获取作业分数失败")
    data = safe_json_parse(json_str)
    if data is None:
        return 0.0, Exception("解析作业分数失败")
    score = json_get(data, "result", "score", default=0)
    return float(score), None
