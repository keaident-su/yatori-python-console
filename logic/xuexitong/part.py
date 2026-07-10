# -*- coding: utf-8 -*-
"""
学习通平台逻辑 - 完整重写对齐 Go 原版
对应 Go 项目的 logic/xuexitong/XueXiTongPart.go
完整实现：AES登录、课程解析(courseSquareUrl)、章节/卡片/视频提交
Go流程: ChapterFetchCardsAction → parseIframeData → ParsePointDto →
        PageMobileChapterCardAction → AttachmentsDetection → Execute*
"""
import copy
import json
import random
import re
import threading
import time
from typing import List, Any, Optional, Dict, Tuple
from urllib.parse import unquote, quote

from bs4 import BeautifulSoup

from config.config import User, Setting, JSONDataForConfig, cmp_course, display_account
from logic.xuexitong.models import (
    XueXiTUserCache, XueXiTCourse, XueXiTChapter, KnowledgeItem,
    PointVideoDto, PointWorkDto, PointDocumentDto,
    PointHyperlinkDto, PointBBsDto, PointLiveDto, PointDto
)
from logic.xuexitong import api as xxt_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, DEBUG,
    Green, Yellow, Red, Blue, Purple, Default, BoldRed, BoldGreen, DarkGray
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "XUEXITONG"

_users_lock = threading.Lock()
_model3_caches: Dict[str, List[XueXiTUserCache]] = {}


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


# ============ 登录 ============

def _login_action(cache: XueXiTUserCache) -> Optional[Exception]:
    """登录动作 - 对应 Go 的 XueXiTLoginAction / XueXiTCookieLoginAction"""
    if len(cache.password) >= 50:
        cache.is_cookie_login = True
        cache.cookie_str = cache.password
        xxt_api.cookie_login_set(cache)
        uid = cache.cookie_dict.get("UID", cache.cookie_dict.get("_uid", ""))
        if uid:
            cache.uid = uid
        return None

    body, _ = xxt_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    data = safe_json_parse(body)
    if data and data.get("status") is True:
        cache.uid = cache.cookie_dict.get(
            "UID", cache.cookie_dict.get("_uid", ""))
        return None
    msg = data.get("msg2", data.get("msg1", "未知错误")) if data else "解析失败"
    return Exception(f"登录失败: {msg}")


def user_login_operation(users: List[User]) -> List[XueXiTUserCache]:
    """登录模块"""
    user_caches = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = XueXiTUserCache(account=user.account, password=user.password)
        err = _login_action(cache)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, user.account, Default, "] ", Red, str(err))
            continue
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[" + cache.account + "] ", Green, "登录成功")
        user_caches.append(cache)
    return user_caches


# ============ 刷课 ============

def run_brush_operation(setting: Setting, users: List[User], user_caches: List[Any]):
    threads = []
    for i, cache in enumerate(user_caches):
        user_idx = i % max(len(users), 1)
        if user_idx >= len(users):
            break
        t = threading.Thread(target=_user_block, args=(
            setting, users[user_idx], cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def _user_block(setting: Setting, user: User, cache: XueXiTUserCache):
    """用户刷课块 - 对应 Go 的 UserBlock"""
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              "开始执行刷课任务扫描...")

    course_list = _pull_course_action(cache)
    if course_list is None:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  Red, "拉取课程失败")
        return

    cc = user.courses_custom
    # 调试：打印多任务点配置
    log_print(DEBUG, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              f"多任务点配置: video_model={cc.video_model}, cx_node={cc.cx_node}")
    if cc.video_model == 3:
        num = cc.cx_node or 3
        if num == -1:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      Yellow, "警告：使用多任务点无限制模式")
        else:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      Yellow, f"警告：多任务点模式，同时登录{num}次")
        if cache.account not in _model3_caches:
            _model3_caches[cache.account] = []
        for i in range(max(num, 1)):
            if i == 0:
                _model3_caches[cache.account].append(copy.deepcopy(cache))
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, display_account(
                              cache.account), Default, "] ",
                          Green, f"多任务点模式: 登录实例 {i+1}/{num} 就绪")
            else:
                c = copy.deepcopy(cache)
                xxt_api.relogin(c)
                _model3_caches[cache.account].append(c)
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, display_account(
                              cache.account), Default, "] ",
                          Green, f"多任务点模式: 登录实例 {i+1}/{num} 就绪")
                time.sleep(1)

    # Concurrent course execution for model 2/3 (Go uses goroutines)
    if user.courses_custom.video_model == 1:
        for course in course_list:
            _course_study(setting, user, cache, course)
    else:
        # 对齐Go: 每个goroutine有独立的HTTP客户端状态
        # Python版: 每个课程线程必须有独立的cache副本，防止cookie_dict并发读写
        threads_course = []
        for course in course_list:
            course_cache = copy.deepcopy(cache)
            t = threading.Thread(target=_course_study,
                                 args=(setting, user, course_cache, course), daemon=True)
            threads_course.append(t)
            t.start()
        for t in threads_course:
            t.join()

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              Purple, "所有待学习课程学习完毕")
    generic_user_block(
        setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], brush_func=None)


# ============ 课程拉取 ============

def _pull_course_action(cache: XueXiTUserCache) -> Optional[List[XueXiTCourse]]:
    """拉取课程 - 对应 Go 的 XueXiTPullCourseAction"""
    body, _ = xxt_api.course_list_api(cache, retry=8)
    data = safe_json_parse(body)
    if not data:
        return None

    channel_list = data.get("channelList", [])
    course_list: List[XueXiTCourse] = []
    seen_keys = set()

    for ch in channel_list:
        if not isinstance(ch, dict):
            continue
        content = ch.get("content", {})
        if not isinstance(content, dict):
            continue
        course_info = content.get("course", {})
        if not isinstance(course_info, dict):
            continue
        data_list = course_info.get("data")
        if not isinstance(data_list, list) or not data_list:
            continue

        d = data_list[0]
        if not isinstance(d, dict):
            continue

        course_square_url = d.get("courseSquareUrl", "")
        if not course_square_url or "courseId=" not in course_square_url:
            continue

        try:
            user_id = course_square_url.split("userId=")[1].split("&")[0]
            class_id = course_square_url.split(
                "classId=")[1].split("&userId")[0]
            course_id = course_square_url.split(
                "courseId=")[1].split("&personId")[0]
        except (IndexError, KeyError):
            continue

        if not cache.user_id:
            cache.user_id = user_id

        course = XueXiTCourse(
            cpi=ch.get("cpi", 0),
            key=class_id,
            course_id=course_id,
            course_name=d.get("name", ""),
            teacher=d.get("teacherfactor", ""),
            is_start=content.get("isstart", False),
            state=content.get("state", 0),
            chat_id=content.get("chatid", ""),
            content_id=content.get("id", 0),
            course_data_id=d.get("id", 0),
            course_image=d.get("imageurl", ""),
        )

        if course.key in seen_keys:
            continue
        seen_keys.add(course.key)
        course_list.append(course)

    if course_list:
        _fetch_course_status(cache, course_list)
        # 诊断日志：显示所有检测到的课程及其状态
        for c in course_list:
            status_str = ""
            if not c.is_start:
                status_str = "未开课"
            elif c.job_rate >= 100:
                status_str = f"已完成({c.job_rate}%)"
            elif c.state == 1:
                status_str = "已结束"
            else:
                status_str = f"进行中({c.job_rate}%, {c.job_finish_count}/{c.job_count})"
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      f"[课程] {c.course_name} | {status_str}")

    return course_list


def _fetch_course_status(cache: XueXiTUserCache, course_list: List[XueXiTCourse]):
    """拉取课程完成进度"""
    parts = []
    key_map = {}
    for course in course_list:
        parts.append(f"{course.key}_{course.cpi}")
        key_map[course.key] = course

    clazz_person_str = ",".join(parts)
    body, _ = xxt_api.course_complete_status_api(
        cache, clazz_person_str, retry=5)
    data = safe_json_parse(body)
    if not data:
        return

    job_array = data.get("jobArray")
    if not isinstance(job_array, list):
        return

    for item in job_array:
        if not isinstance(item, dict):
            continue
        clazz_id = str(int(item.get("clazzId", 0)))
        if clazz_id in key_map:
            course = key_map[clazz_id]
            course.job_finish_count = int(item.get("jobFinishCount", 0))
            course.job_rate = float(item.get("jobRate", 0))
            course.job_count = int(item.get("jobCount", 0))


# ============ 课程学习 ============

def _course_study(setting: Setting, user: User, cache: XueXiTUserCache,
                  course: XueXiTCourse):
    """课程学习 - 对应 Go 的 courseStudy"""
    cc = user.courses_custom
    if cc.exclude_courses and cmp_course(course.course_name, cc.exclude_courses):
        return
    if cc.include_courses and not cmp_course(course.course_name, cc.include_courses):
        return
    if not course.is_start:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  "[", course.course_name, "] ", Blue, "该课程还未开课，已自动跳过")
        return
    if course.job_rate >= 100 or course.state == 1:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  "[", course.course_name, "] ", Blue, "该课程已完成或已结束，已跳过")
        return
    _chapter_study(setting, user, cache, course)
    # 写课程的作业和考试
    _write_course_work_and_exam(setting, user, cache, course)
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              "[", course.course_name, "] ", Purple, "课程学习完毕")


# ============ 章节学习 ============

def _unwrap_data(obj):
    """Unwrap chaoxing API nested {data: [...]} or {data: {...}} wrappers.
    The chaoxing gas/ API often wraps arrays/objects inside a 'data' key.
    This helper recursively unwraps until we get the actual content.
    """
    if not isinstance(obj, dict):
        return obj
    if 'data' in obj and len(obj) <= 2:
        inner = obj['data']
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            return inner
    return obj


def _chapter_study(setting: Setting, user: User, cache: XueXiTUserCache,
                   course: XueXiTCourse):
    """章节学习 - 对应 Go 的 chapterStudy"""
    try:
        key_int = int(course.key)
    except (ValueError, TypeError):
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  "[", course.course_name, "] ", BoldRed, f"课程key解析失败: '{course.key}'")
        return

    body, _ = xxt_api.pull_chapter_api(cache, key_int, course.cpi, retry=8)
    data = safe_json_parse(body)
    if not data:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  "[", course.course_name, "] ", BoldRed, "拉取章节信息失败")
        return

    # chaoxing gas/clazz API wraps: {data: [{course: {data: [{knowledge: {data: [...]}}]}}]}
    knowledge_list = []
    data_items = data.get("data", [])
    if isinstance(data_items, list) and data_items:
        first_item = data_items[0]
        if isinstance(first_item, dict):
            course_obj = first_item.get("course", {})
            # Unwrap course.data layer: course -> {data: [{knowledge: ...}]}
            course_info = course_obj
            course_data_inner = course_obj.get("data")
            if isinstance(course_data_inner, list) and course_data_inner:
                course_info = course_data_inner[0]
            # Now get knowledge from the unwrapped course_info
            knowledge_obj = course_info.get(
                "knowledge", []) if isinstance(course_info, dict) else []
            # Unwrap knowledge.data layer: {data: [...]} -> [...]
            if isinstance(knowledge_obj, dict):
                knowledge_list = knowledge_obj.get("data", [])
            elif isinstance(knowledge_obj, list):
                knowledge_list = knowledge_obj

    if not knowledge_list:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  "[", course.course_name, "] ", BoldRed, "该课程章节为空，已自动跳过")
        return

    nodes = []
    knowledge_map = {}
    for item in knowledge_list:
        if isinstance(item, dict):
            nid = item.get("id", 0)
            nodes.append(nid)
            knowledge_map[nid] = {
                "name": item.get("name", ""),
                "label": item.get("label", "")
            }

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              "[", course.course_name, "] ",
              f"获取课程章节成功 (共 ", Yellow, str(len(nodes)), Default, " 个)")

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              "[", course.course_name, "] ", Purple, "正在学习该课程")

    try:
        course_id_int = int(course.course_id)
        user_id_int = int(cache.user_id) if cache.user_id else 0
    except (ValueError, TypeError):
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  "[", course.course_name, "] ", BoldRed,
                  f"ID解析失败: courseId='{course.course_id}', userId='{cache.user_id}'")
        return

    point_body, _ = xxt_api.fetch_chapter_point_status(
        cache, nodes, key_int, user_id_int, course.cpi, course_id_int, retry=5)
    point_data = safe_json_parse(point_body)

    finished_map = {}
    if point_data:
        for k, v in point_data.items():
            if isinstance(v, dict):
                # chaoxing API uses totalcount/finishcount/unfinishcount
                total = v.get("totalcount", v.get("pointTotal", 0))
                finished = v.get("finishcount", v.get("pointFinished", 0))
                unfinish = v.get("unfinishcount", 0)
                # 对齐 Go updatePointStatus: 当unfinishcount!=0且totalcount==0时
                # 使用unfinishcount作为total（顶级标签场景）
                if unfinish != 0 and total == 0:
                    total = unfinish
                finished_map[k] = (total, finished)

    # === Node iteration: model3 concurrent, others sequential (matching Go) ===
    cc = user.courses_custom
    if cc.video_model == 3 and cache.account in _model3_caches and _model3_caches[cache.account]:
        # Model 3: concurrent node execution using model3 cache pool
        import queue as _queue_mod
        m3_list = _model3_caches[cache.account]
        resource_q = _queue_mod.Queue()
        for i in range(len(m3_list)):
            resource_q.put(i)

        node_threads = []
        for index, node_id in enumerate(nodes):
            node_str = str(node_id)
            if node_str in finished_map:
                total, finished = finished_map[node_str]
                if total >= 0 and total == finished:
                    continue
                if total == 0 and finished == 0:
                    err = xxt_api.enter_chapter_forward_call_api(
                        cache, course.course_id, course.key,
                        str(node_id), str(course.cpi))
                    if err:
                        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                                  "[", Green, display_account(
                                      cache.account), Default, "] ",
                                  "[", course.course_name, "] ", BoldRed,
                                  f"零任务点遍历失败: {err}")
                    continue

            if (cc.cx_node or 3) == -1:
                # Unlimited mode: relogin for each node
                def _run_unlimited(idx=index, nid=node_id):
                    res_cache = copy.deepcopy(cache)
                    try:
                        xxt_api.relogin(res_cache)
                        _node_run(setting, user, res_cache,
                                  course, nodes, idx, nid, knowledge_map)
                    except Exception as e:
                        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                                  "[", Green, display_account(
                                      cache.account), Default, "] ",
                                  "[", course.course_name, "] ", BoldRed,
                                  f"节点{nid}运行异常: {e}")
                t = threading.Thread(target=_run_unlimited, daemon=True)
                node_threads.append(t)
                t.start()
                time.sleep(1)
            else:
                # Queue-based: get a cache slot from pool
                slot_idx = resource_q.get()

                def _run_slot(si=slot_idx, idx=index, nid=node_id):
                    try:
                        _node_run(setting, user,
                                  m3_list[si], course, nodes, idx, nid, knowledge_map)
                    except Exception as e:
                        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                                  "[", Green, display_account(
                                      cache.account), Default, "] ",
                                  "[", course.course_name, "] ", BoldRed,
                                  f"节点{nid}运行异常: {e}")
                    finally:
                        resource_q.put(si)
                t = threading.Thread(target=_run_slot, daemon=True)
                node_threads.append(t)
                t.start()

        for t in node_threads:
            t.join()
    else:
        # Sequential node execution (model 1/2)
        for index, node_id in enumerate(nodes):
            node_str = str(node_id)
            if node_str in finished_map:
                total, finished = finished_map[node_str]
                if total >= 0 and total == finished:
                    continue
                if total == 0 and finished == 0:
                    err = xxt_api.enter_chapter_forward_call_api(
                        cache, course.course_id, course.key,
                        str(node_id), str(course.cpi))
                    if err:
                        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                                  "[", Green, display_account(
                                      cache.account), Default, "] ",
                                  "[", course.course_name, "] ", BoldRed,
                                  f"零任务点遍历失败: {err}")
                    continue
            # If node is NOT in finished_map, still run it (Go does this)
            _node_run(setting, user, cache, course, nodes,
                      index, node_id, knowledge_map)


# ============ 节点运行 (核心重写 - 完全对齐Go) ============

def _node_run(setting: Setting, user: User, cache: XueXiTUserCache,
              course: XueXiTCourse, nodes: List[int],
              index: int, node_id: int,
              knowledge_map: Dict = None):
    """节点运行 - 完全对齐 Go 的 nodeRun
    Go流程:
    1. ChapterFetchCardsAction → API1获取卡片 → parseIframeData → 创建PointDto
    2. ParsePointDto → 分离为6种DTO列表
    3. 对每种DTO:
       a. PageMobileChapterCardAction → 获取移动端AttachmentSetting+enc
       b. AttachmentsDetection → 从卡片数据填充参数
       c. 执行对应任务
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    try:
        course_id_int = int(course.course_id)
        class_id_int = int(course.key)
        cpi_int = int(course.cpi)
    except (ValueError, TypeError):
        return

    # === Step 1: ChapterFetchCardsAction (API 1 获取卡片列表) ===
    cords_body, cords_resp = xxt_api.fetch_chapter_cords(
        cache, node_id, course_id_int, retry=5)
    cords_data = safe_json_parse(cords_body)
    # 对齐Go: 500错误或空响应时自动relogin重试
    if not cords_data:
        status = cords_resp.status_code if cords_resp else 0
        if status >= 500 or not cords_body:
            log_print(DEBUG, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "[", course.course_name, "] ", DarkGray,
                      f"章节{node_id}卡片拉取失败(status={status})，尝试重新登录...")
            xxt_api.relogin(cache)
            cords_body, _ = xxt_api.fetch_chapter_cords(
                cache, node_id, course_id_int, retry=5)
            cords_data = safe_json_parse(cords_body)
    if not cords_data:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "[", course.course_name, "] ", BoldRed, "无法正常拉取卡片信息")
        return

    cards_data = cords_data.get("data", [])
    if not cards_data or not isinstance(cards_data, list):
        log_print(DEBUG, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "[", course.course_name, "] ", DarkGray,
                  f"章节{node_id}的data为空或格式异常")
        return
    first_data = cards_data[0]
    if not isinstance(first_data, dict):
        return
    card_data = first_data.get("card", {})
    if not isinstance(card_data, dict):
        return
    cards = card_data.get("data", [])
    if not cards or not isinstance(cards, list):
        log_print(DEBUG, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "[", course.course_name, "] ", DarkGray,
                  f"章节{node_id}无卡片数据")
        return

    # 获取 knowledge_id
    knowledge_id = 0
    for card in cards:
        if isinstance(card, dict):
            kid = card.get("knowledgeid", 0)
            if kid:
                knowledge_id = kid
                break

    # === Step 2: parseIframeData + 创建 PointDto 列表 ===
    point_dtos: List[PointDto] = []
    for card_idx, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        description = card.get("description", "")
        if not description:
            continue

        # 解析 iframe
        iframe_list = xxt_api.parse_iframe_data(description)
        if not iframe_list:
            continue

        for point_idx, point in enumerate(iframe_list):
            module_type = point.get("other", {}).get("module", "")
            if not module_type:
                continue
            if not point.get("has_data", False):
                continue

            tp_data = point.get("data", {})
            if not tp_data or not isinstance(tp_data, dict):
                continue

            dto = PointDto()
            _fill_dto_from_iframe(dto, module_type, tp_data, card_idx,
                                  course_id_int, class_id_int,
                                  knowledge_id, cpi_int, card, cache)
            point_dtos.append(dto)

    if not point_dtos:
        return

    # 创建 KnowledgeItem 用于日志输出
    ki_data = (knowledge_map or {}).get(node_id, {})
    knowledge_item = KnowledgeItem(
        id=node_id,
        name=ki_data.get("name", f"章节{node_id}"),
        label=ki_data.get("label", "")
    )

    # === Step 3: ParsePointDto → 分离为6种DTO列表 ===
    video_dtos = [d.video for d in point_dtos if d.video.is_set]
    work_dtos = [d.work for d in point_dtos if d.work.is_set]
    doc_dtos = [d.document for d in point_dtos if d.document.is_set]
    hyperlink_dtos = [d.hyperlink for d in point_dtos if d.hyperlink.is_set]
    live_dtos = [d.live for d in point_dtos if d.live.is_set]
    bbs_dtos = [d.bbs for d in point_dtos if d.bbs.is_set]

    cc = user.courses_custom

    # === 视频/音频类型 ===
    if video_dtos and cc.video_model != 0:
        for vdto in video_dtos:
            card, enc, err = _page_mobile_chapter_card_action(
                setting, cache, class_id_int, course_id_int,
                vdto.knowledge_id, vdto.card_index, cpi_int)
            if err:
                if "章节未开放" in str(err):
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ",
                              "[", course.course_name, "] ", BoldRed,
                              "该章节未开放，已自动跳过")
                    break
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "[", course.course_name, "] ", Red, str(err))
                break

            if card is None:
                continue

            _attachments_detection_video(vdto, card)

            if not vdto.is_job:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "[", course.course_name, "] ", Blue,
                          "该视频/音频非任务点或已完成，已自动跳过")
                continue

            vdto.enc = enc
            if vdto.is_passed and not vdto.is_job:
                continue
            if not vdto.is_passed and vdto.attachment is None and not vdto.job_id and vdto.duration <= vdto.play_time:
                continue

            if vdto.type == "video":
                _execute_video(setting, user, cache,
                               course, knowledge_item, vdto)
            elif vdto.type == "insertaudio":
                _execute_audio(setting, user, cache,
                               course, knowledge_item, vdto)

            rand_sleep = random.randint(10, 60)
            time.sleep(rand_sleep)

    # === 文档类型 ===
    if doc_dtos and cc.video_model != 0:
        for ddto in doc_dtos:
            card, enc, err = _page_mobile_chapter_card_action(
                setting, cache, class_id_int, course_id_int,
                ddto.knowledge_id, ddto.card_index, cpi_int)
            if err:
                if "章节未开放" in str(err):
                    break
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ", Red, str(err))
                break
            if card is None:
                continue
            _attachments_detection_document(ddto, card)
            if not ddto.is_job:
                continue
            _execute_document(cache, course, ddto)
            time.sleep(5)

    # === 章测(作业)类型 ===
    if work_dtos and cc.auto_exam != 0 and (cc.cx_chapter_test_sw or 0) == 1:
        for wdto in work_dtos:
            card, enc, err = _page_mobile_chapter_card_action(
                setting, cache, class_id_int, course_id_int,
                wdto.knowledge_id, wdto.card_index, cpi_int)
            if err:
                if "章节未开放" in str(err):
                    continue
                if "没有历史人脸" in str(err):
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ", BoldRed,
                              "过人脸失败，该账号可能从未进行过人脸识别")
                    break
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ", Red, str(err))
                break
            if card is None:
                continue
            flag, _ = _attachments_detection_work(wdto, card)
            if not flag:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ", Green,
                          "该章测已完成，已自动跳过")
                continue
            # 执行章测自动答题
            _chapter_test_action(setting, user, cache,
                                 course, knowledge_item, wdto)

    # === 外链类型 ===
    if hyperlink_dtos and cc.video_model != 0:
        for hdto in hyperlink_dtos:
            card, enc, err = _page_mobile_chapter_card_action(
                setting, cache, class_id_int, course_id_int,
                hdto.knowledge_id, hdto.card_index, cpi_int)
            if err:
                if "章节未开放" in str(err):
                    continue
                break
            if card is None:
                continue
            _attachments_detection_hyperlink(hdto, card)
            _execute_hyperlink(cache, course, hdto)
            time.sleep(5)

    # === 直播类型 ===
    if live_dtos and cc.video_model != 0:
        for lvdto in live_dtos:
            card, enc, err = _page_mobile_chapter_card_action(
                setting, cache, class_id_int, course_id_int,
                lvdto.knowledge_id, lvdto.card_index, cpi_int)
            if err:
                if "章节未开放" in str(err):
                    continue
                break
            if card is None:
                continue
            _attachments_detection_live(lvdto, card)
            if not lvdto.is_job:
                continue
            _execute_live(setting, user, cache, course, knowledge_item, lvdto)
            time.sleep(5)

    # === 讨论类型 ===
    if bbs_dtos and cc.auto_exam != 0:
        for bbs_dto in bbs_dtos:
            card, enc, err = _page_mobile_chapter_card_action(
                setting, cache, class_id_int, course_id_int,
                bbs_dto.knowledge_id, bbs_dto.card_index, cpi_int)
            if err:
                if "章节未开放" in str(err):
                    continue
                break
            if card is None:
                continue
            _attachments_detection_bbs(bbs_dto, card)
            if not bbs_dto.is_job:
                continue
            _execute_bbs(setting, user, cache, course, knowledge_item, bbs_dto)
            time.sleep(5)


# ============ PageMobileChapterCardAction ============

def _page_mobile_chapter_card_action(
        setting: Setting, cache: XueXiTUserCache, class_id: int, course_id: int,
        knowledge_id: int, card_index: int, cpi: int
) -> Tuple[Optional[Dict], str, Optional[Exception]]:
    """移动端卡片获取 + AttachmentSetting提取 - 对应 Go PageMobileChapterCardAction
    返回: (attachment_dict, enc, error)
    """
    html_body, resp = xxt_api.page_mobile_chapter_card_api(
        cache, class_id, course_id, knowledge_id, card_index, cpi, retry=3)
    if not html_body:
        return None, "", Exception("卡片响应为空")

    attachment, enc = xxt_api.parse_attachment_setting(html_body)

    if enc == "CAPTCHA":
        # 验证码绕过 - 尝试自动通过验证码后重试
        _bypass_captcha(setting, cache)
        # 重试获取卡片
        html_body, resp = xxt_api.page_mobile_chapter_card_api(
            cache, class_id, course_id, knowledge_id, card_index, cpi, retry=3)
        if not html_body:
            return None, "", Exception("验证码绕过后卡片响应仍为空")
        attachment, enc = xxt_api.parse_attachment_setting(html_body)
        if enc == "CAPTCHA":
            # 对齐Go: 触发验证码时仅跳过，不显示警告
            return None, "", Exception("触发验证码")

    if enc == "FACE":
        # 人脸识别绕过
        platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
        acct = display_account(cache.account)
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ", Yellow,
                  "触发人脸识别，正在尝试自动绕过...")
        err = xxt_api.pass_face_pc_action(
            cache, str(course_id), str(class_id), str(cpi),
            str(knowledge_id), enc, "", "", "", "")
        if err:
            if "没有历史人脸" in str(err):
                return None, "", Exception("过人脸失败，该账号可能从未进行过人脸识别，请先进行一次人脸识别")
            if "活体检测失败" in str(err):
                return None, "", Exception("过人脸失败，该账号所录入的人脸可能不规范")
            return None, "", Exception(f"人脸绕过失败: {err}")
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ", Green,
                  "人脸识别绕过成功，重新获取卡片...")
        # 重试获取卡片
        html_body, resp = xxt_api.page_mobile_chapter_card_api(
            cache, class_id, course_id, knowledge_id, card_index, cpi, retry=3)
        if not html_body:
            return None, "", Exception("人脸绕过后卡片响应为空")
        attachment, enc = xxt_api.parse_attachment_setting(html_body)
        if enc == "FACE":
            return None, "", Exception("人脸识别绕过后仍触发人脸，请手动处理")

    if attachment is None:
        # 检查章节未开放
        if '章节未开放' in html_body:
            return None, "", Exception("章节未开放")
        return None, "", Exception("无法解析AttachmentSetting")

    return attachment, enc, None


def _bypass_captcha(setting: Setting, cache: XueXiTUserCache) -> bool:
    """验证码绕过 - 对应 Go XueXiTVerCodeApi
    尝试获取验证码图片并自动提交
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    try:
        img_data, err = xxt_api.verification_code_api(cache)
        if err or not img_data:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ", Red,
                      f"获取验证码失败: {err}")
            return False
        # 简单验证码识别 - 使用AI或OCR
        try:
            from logic.core.ai_client import AIClient
            if setting and hasattr(setting, 'ai_setting') and setting.ai_setting:
                ai = setting.ai_setting
                client = AIClient(ai.ai_url, ai.model, ai.api_key, ai.ai_type)
                import base64
                img_b64 = base64.b64encode(img_data).decode()
                answer = client.ask(
                    f"请识别这张验证码图片中的字符，只返回字符内容不要其他文字。图片base64: {img_b64}")
                if answer and len(answer.strip()) >= 2:
                    code = answer.strip()
                    success, err = xxt_api.pass_verification_code_api(
                        cache, code)
                    if success:
                        log_print(INFO, f"[{platform}]",
                                  "[", Green, acct, Default, "] ", Green,
                                  f"验证码AI识别成功: {code}")
                        return True
        except Exception:
            pass
        # 对齐Go: 验证码识别失败时静默跳过(Go根本不尝试自动解决)
        return False
    except Exception as e:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ", Red,
                  f"验证码绕过异常: {e}")
        return False


# ============ DTO 填充 (从iframe解析) ============

def _fill_dto_from_iframe(dto: PointDto, module_type: str,
                          tp_data: Dict, card_idx: int,
                          course_id: int, class_id: int,
                          knowledge_id: int, cpi: int,
                          card: Dict, cache: XueXiTUserCache):
    """根据iframe解析结果填充对应DTO - 对应 Go ChapterFetchCardsAction 中的 switch"""
    if module_type in ("video", "insertvideo"):
        object_id = tp_data.get("objectid", "")
        if not object_id:
            return
        vd = dto.video
        vd.card_index = card_idx
        vd.course_id = str(course_id)
        vd.class_id = str(class_id)
        vd.knowledge_id = knowledge_id
        vd.cpi = str(cpi)
        vd.object_id = object_id
        vd.type = "video"
        vd.is_set = True
        # 名称
        name = tp_data.get("name", "")
        if name:
            try:
                vd.title = unquote(name)
            except Exception:
                vd.title = name
        # jobid
        vd.job_id = _extract_jobid(tp_data)

    elif module_type == "work":
        work_id = str(tp_data.get("workid", ""))
        school_id = str(tp_data.get("schoolid", "0"))
        job_id = str(tp_data.get("_jobid", ""))
        if work_id and job_id:
            wd = dto.work
            wd.card_index = card_idx
            wd.course_id = str(course_id)
            wd.class_id = str(class_id)
            wd.knowledge_id = knowledge_id
            wd.cpi = str(cpi)
            wd.work_id = work_id
            wd.school_id = school_id if school_id else "0"
            wd.job_id = job_id
            wd.is_set = True

    elif module_type in ("document", "insertdoc"):
        object_id = tp_data.get("objectid", "")
        job_id = str(tp_data.get("_jobid", ""))
        if object_id and job_id:
            dd = dto.document
            dd.card_index = card_idx
            dd.course_id = str(course_id)
            dd.class_id = str(class_id)
            dd.knowledge_id = knowledge_id
            dd.cpi = str(cpi)
            dd.object_id = object_id
            dd.job_id = job_id
            dd.type = "document"
            dd.is_set = True

    elif module_type == "insertreadv2":
        job_id = str(tp_data.get("_jobid", ""))
        if job_id:
            dd = dto.document
            dd.card_index = card_idx
            dd.course_id = str(course_id)
            dd.class_id = str(class_id)
            dd.knowledge_id = knowledge_id
            dd.cpi = str(cpi)
            dd.title = tp_data.get("title", "")
            dd.job_id = job_id
            dd.type = "insertreadv2"
            dd.is_set = True
            dd.read = tp_data.get("resd", False)

    elif module_type == "insertbook":
        job_id = str(tp_data.get("_jobid", ""))
        if job_id:
            dd = dto.document
            dd.card_index = card_idx
            dd.course_id = str(course_id)
            dd.class_id = str(class_id)
            dd.knowledge_id = knowledge_id
            dd.cpi = str(cpi)
            dd.job_id = job_id
            dd.type = "insertbook"
            dd.is_set = True

    elif module_type == "hyperlink":
        job_id = str(tp_data.get("_jobid", ""))
        if job_id:
            hd = dto.hyperlink
            hd.card_index = card_idx
            hd.course_id = str(course_id)
            hd.class_id = str(class_id)
            hd.knowledge_id = knowledge_id
            hd.cpi = str(cpi)
            hd.object_id = str(tp_data.get("objectid", ""))
            hd.job_id = job_id
            hd.title = tp_data.get("title", "")
            hd.link_type = int(tp_data.get("linkType", 0))
            hd.is_set = True

    elif module_type == "insertlive":
        job_id = str(tp_data.get("_jobid", ""))
        if job_id:
            ld = dto.live
            ld.card_index = card_idx
            ld.course_id = str(course_id)
            ld.class_id = str(class_id)
            ld.knowledge_id = knowledge_id
            ld.cpi = str(cpi)
            ld.job_id = job_id
            ld.module = module_type
            ld.user_id = cache.cookie_dict.get("_uid", cache.uid)
            ld.title = tp_data.get("title", "")
            ld.live_status_str = tp_data.get("liveStatus", "")
            ld.stream_name = tp_data.get("streamName", "")
            ld.live = tp_data.get("live", False)
            ld.vdoid = tp_data.get("vdoid", "")
            live_id = tp_data.get("liveId", 0)
            if isinstance(live_id, (int, float)):
                ld.live_id = str(int(live_id))
            ld.is_set = True

    elif module_type == "insertbbs":
        job_id = str(tp_data.get("_jobid", ""))
        if job_id:
            bd = dto.bbs
            bd.card_index = card_idx
            bd.course_id = str(course_id)
            bd.class_id = str(class_id)
            bd.knowledge_id = knowledge_id
            bd.cpi = str(cpi)
            bd.job_id = job_id
            bd.module = module_type
            bd.user_id = cache.cookie_dict.get("_uid", cache.uid)
            bd.title = tp_data.get("title", "")
            bd.detail = tp_data.get("detail", "")
            bd.mid = tp_data.get("mid", "")
            bd.allow_view_reply = int(tp_data.get("allowViewReply", 0))
            bd.reply_times = tp_data.get("replytimes", "")
            bd.replay_word_num = tp_data.get("replywordnum", "")
            bd.end_time = tp_data.get("endtime", "")
            bd.is_job = tp_data.get("isJob", False)
            bd.is_set = True

    elif module_type == "insertaudio":
        object_id = tp_data.get("objectid", "")
        if not object_id:
            return
        vd = dto.video
        vd.card_index = card_idx
        vd.course_id = str(course_id)
        vd.class_id = str(class_id)
        vd.knowledge_id = knowledge_id
        vd.cpi = str(cpi)
        vd.object_id = object_id
        vd.type = "insertaudio"
        vd.is_set = True
        name = tp_data.get("name", "")
        if name:
            try:
                vd.title = unquote(name)
            except Exception:
                vd.title = name
        vd.job_id = _extract_jobid(tp_data)


def _extract_jobid(data: Dict) -> str:
    """从数据字典中提取jobid，处理string/float类型"""
    for key in ("jobid", "_jobid"):
        val = data.get(key)
        if val is not None:
            if isinstance(val, str) and val:
                return val
            if isinstance(val, (int, float)):
                return str(int(val))
    return ""


# ============ AttachmentsDetection 系列 ============

def _attachments_detection_video(vdto: PointVideoDto, attachment_map: Dict):
    """视频DTO附件检测 - 对应 Go PointVideoDto.AttachmentsDetection"""
    attachments = attachment_map.get("attachments", [])
    if not isinstance(attachments, list):
        return

    for a in attachments:
        if not isinstance(a, dict):
            continue
        prop = a.get("property", {})
        if not isinstance(prop, dict):
            continue

        objectid = prop.get("objectid")
        if objectid is None:
            continue

        jobid = ""
        for k in ("jobid", "_jobid"):
            v = prop.get(k)
            if isinstance(v, str):
                jobid = v
            elif isinstance(v, (int, float)):
                jobid = str(int(v))

        if objectid != vdto.object_id or vdto.job_id != jobid:
            continue

        # 匹配成功，填充参数
        other_info = a.get("otherInfo", "")
        if isinstance(other_info, str) and "&" in other_info:
            other_info = other_info.split("&")[0]
        vdto.other_info = other_info

        vdto.is_passed = a.get("isPassed", False)
        vdto.mid = a.get("mid", "")
        vdto.random_capture_time = a.get("randomCaptureTime", "0")
        vdto.att_duration_enc = a.get("attDurationEnc", "")
        vdto.video_face_capture_enc = a.get("videoFaceCaptureEnc", "")
        vdto.is_job = a.get("job", False)

        # RT
        rt_val = prop.get("rt")
        if isinstance(rt_val, (int, float)):
            vdto.rt = float(rt_val)
        elif isinstance(rt_val, str):
            try:
                vdto.rt = float(rt_val)
            except Exception:
                vdto.rt = 0.9
        else:
            vdto.rt = 0.9

        vdto.attachment = a

        # jobid from property
        jid = prop.get("jobid")
        if isinstance(jid, str):
            vdto.job_id = jid
        elif isinstance(jid, (int, float)):
            vdto.job_id = str(int(jid))
        break

    if vdto.attachment is None:
        return

    defaults = attachment_map.get("defaults", {})
    if isinstance(defaults, dict):
        fid_str = str(defaults.get("fid", "0"))
        try:
            vdto.fid = int(fid_str)
        except (ValueError, TypeError):
            vdto.fid = 0


def _attachments_detection_work(wdto: PointWorkDto, attachment_map: Dict) -> Tuple[bool, Optional[Exception]]:
    """作业DTO附件检测 - 对应 Go PointWorkDto.AttachmentsDetection"""
    attachments = attachment_map.get("attachments", [])
    if not isinstance(attachments, list):
        return False, None

    flag = False
    for a in attachments:
        if not isinstance(a, dict):
            continue
        prop = a.get("property", {})
        if not isinstance(prop, dict):
            continue

        work_id = prop.get("workid")
        if isinstance(work_id, (int, float)):
            work_id = str(int(work_id))
        if not work_id or work_id != wdto.work_id:
            continue

        wdto.enc = a.get("enc", "")
        flag = a.get("job", False) if a.get("job") is not None else False
        break

    defaults = attachment_map.get("defaults", {})
    if isinstance(defaults, dict):
        wdto.k_token = defaults.get("ktoken", "")
        wdto.puid = defaults.get("userid", "")
    return flag, None


def _attachments_detection_document(ddto: PointDocumentDto, attachment_map: Dict):
    """文档DTO附件检测 - 对应 Go PointDocumentDto.AttachmentsDetection"""
    attachments = attachment_map.get("attachments", [])
    if not isinstance(attachments, list):
        return

    for a in attachments:
        if not isinstance(a, dict):
            continue
        prop = a.get("property", {})
        if not isinstance(prop, dict):
            continue

        type_str = a.get("type", "")
        if not type_str and isinstance(prop, dict):
            type_str = prop.get("module", "")

        if type_str in ("", "document", "insertdoc"):
            objectid = prop.get("objectid")
            jobid = prop.get("jobid")
            if (ddto.object_id and objectid == ddto.object_id) or \
               (jobid is not None and ddto.job_id == str(jobid)):
                ddto.title = prop.get("name", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                ddto.is_job = a.get("job", False) if a.get(
                    "job") is not None else False
                break

        elif type_str == "insertbook":
            jobid = prop.get("jobid")
            if (jobid is not None and ddto.job_id == str(jobid)):
                ddto.title = prop.get("bookname", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                ddto.is_job = a.get("job", False) if a.get(
                    "job") is not None else False
                break

        elif type_str == "read":
            jobid = prop.get("jobid")
            if jobid is not None and ddto.job_id == str(jobid):
                ddto.title = prop.get("title", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                ddto.is_job = a.get("job", False) if a.get(
                    "job") is not None else False
                break

        else:
            # 通用fallback
            objectid = prop.get("objectid")
            jobid = prop.get("jobid")
            if (ddto.object_id and objectid == ddto.object_id) or \
               (jobid is not None and ddto.job_id == str(jobid)):
                ddto.title = prop.get("name", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                ddto.is_job = a.get("job", False) if a.get(
                    "job") is not None else False
                break


def _attachments_detection_hyperlink(hdto: PointHyperlinkDto, attachment_map: Dict):
    """外链DTO附件检测"""
    attachments = attachment_map.get("attachments", [])
    if not isinstance(attachments, list):
        return

    for a in attachments:
        if not isinstance(a, dict):
            continue
        jobid = a.get("jobid")
        if jobid is None:
            continue
        if str(jobid) != hdto.job_id:
            continue
        prop = a.get("property", {})
        if isinstance(prop, dict):
            hdto.title = prop.get("title", "")
            if prop.get("jobid"):
                hdto.job_id = str(prop["jobid"])
        hdto.jtoken = a.get("jtoken", "")
        break


def _attachments_detection_live(ldto: PointLiveDto, attachment_map: Dict):
    """直播DTO附件检测"""
    attachments = attachment_map.get("attachments", [])
    if not isinstance(attachments, list):
        return

    for a in attachments:
        if not isinstance(a, dict):
            continue
        ldto.auth_enc = a.get("authEnc", ldto.auth_enc)
        ldto.live_drag_enc = a.get("liveDragEnc", ldto.live_drag_enc)
        ldto.live_set_enc = a.get("liveSetEnc", ldto.live_set_enc)
        ldto.other_info = a.get("otherInfo", ldto.other_info)
        ldto.enc = a.get("enc", ldto.enc)
        ldto.live_sw_ds_enc = a.get("liveSwDsEnc", ldto.live_sw_ds_enc)
        ldto.is_job = a.get("job", False) if a.get(
            "job") is not None else False
        aid = a.get("aid")
        if isinstance(aid, (int, float)):
            ldto.aid = str(int(aid))
        jobid = a.get("jobid")
        if jobid is not None and str(jobid) == ldto.job_id:
            break


def _attachments_detection_bbs(bdto: PointBBsDto, attachment_map: Dict):
    """讨论DTO附件检测"""
    attachments = attachment_map.get("attachments", [])
    if not isinstance(attachments, list):
        return

    for a in attachments:
        if not isinstance(a, dict):
            continue
        bdto.auth_enc = a.get("authEnc", bdto.auth_enc)
        bdto.other_info = a.get("otherInfo", bdto.other_info)
        enc = attachment_map.get("enc", "")
        if enc:
            bdto.enc = enc
        bdto.is_job = a.get("job", False) if a.get(
            "job") is not None else False
        jobid = a.get("jobid")
        if jobid is not None and str(jobid) == bdto.job_id:
            break


# ============ 视频执行 (完全对齐Go) ============

def _video_submit_with_relogin(cache: XueXiTUserCache, video: PointVideoDto,
                               playing_time: int, isdrag: int,
                               mode: int) -> Tuple[str, Optional[Any]]:
    """视频学时提交 + 错误时ReLogin重试 - 对齐Go的VideoSubmitStudyTimeAction聚合层
    Go聚合层逻辑: 先提交 → 遇到500/202/400/403时ReLogin → 重试同mode
    """
    # 第一次提交
    if mode == 1:
        body, resp = xxt_api.video_submit_study_time_pe_api(
            cache, video, playing_time, isdrag=isdrag, retry=5)
    else:
        body, resp = xxt_api.video_submit_study_time_api(
            cache, video, playing_time, isdrag=isdrag, retry=5)

    status_code = resp.status_code if resp else 0

    # 如果成功或404(特殊处理)，直接返回
    if status_code == 200 or status_code == 404:
        return body, resp

    # 500/202/400/403: ReLogin后重试 (完全对齐Go聚合层)
    # Go: 触发403的时候会进行一次重登测试，如果之后还是403那说明是人脸了
    if status_code in (500, 202, 400, 403):
        xxt_api.relogin(cache)
        if mode == 1:
            body2, resp2 = xxt_api.video_submit_study_time_pe_api(
                cache, video, playing_time, isdrag=isdrag, retry=5)
        else:
            body2, resp2 = xxt_api.video_submit_study_time_api(
                cache, video, playing_time, isdrag=isdrag, retry=5)
        return body2, resp2

    # 其他错误: 直接返回
    return body, resp


def _execute_video(setting: Setting, user: User, cache: XueXiTUserCache,
                   course: XueXiTCourse, knowledge_item: KnowledgeItem,
                   video: PointVideoDto):
    """执行视频学习 - 完全对齐 Go ExecuteVideo
    包含: 过超提交、403人脸绕过、500跳过、404重试、OutTimeMsg、isdrag=3
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    k_label = f"{knowledge_item.label} {knowledge_item.name}".strip(
    ) if knowledge_item.label else knowledge_item.name

    # VideoDtoFetchAction
    if not _video_dto_fetch_action(cache, video):
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", k_label, "】",
                  "【", video.title, "】 >>> ",
                  Red, "视频任务点解析失败，已自动跳过")
        return

    # 初始播放时间处理
    playing_time = video.play_time
    if not video.is_passed and video.play_time == video.duration:
        playing_time = 0

    over_time = 0
    select_sec = 58          # 默认60s提交间隔
    extend_sec = 5           # 过超提交停留时间
    limit_time = max(500, video.duration // 2)  # 过超时间最大限制
    mode = 1                 # 0=Web模式, 1=手机模式
    stop_val = 0             # 403重试计数器 (对齐Go stopVal)

    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              "【", k_label, "】",
              "【", video.title, "】 >>> ",
              Yellow, "正在学习视频：", Default,
              f"duration={video.duration}s")

    while True:
        # isdrag: 首次播放(playingTime==playTime)时为3，否则为0
        if playing_time != video.duration:
            if playing_time == video.play_time:
                isdrag = 3
            else:
                isdrag = 0
        else:
            isdrag = 0

        # 根据mode选择API - 对齐Go聚合层: 先提交，错误时ReLogin重试
        body, resp = _video_submit_with_relogin(
            cache, video, playing_time, isdrag, mode)

        status_code = resp.status_code if resp else 0

        # === 错误处理 - 完全对齐 Go VideoSubmitStudyTimeAction + ExecuteVideo ===
        # 500: Go聚合层ReLogin后重试，仍失败则报错给调用层
        if status_code == 500:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      BoldRed, "视频提交触发500风控，ReLogin后重试仍失败，跳过该视频")
            break

       # 403: 对齐Go ExecuteVideo (XueXiTongPart.go)
        # Go逻辑: mode==1(手机端)时切换为mode==0(Web端); mode==0时尝试人脸绕过
        if status_code == 403:
            if mode == 1:
                mode = 0
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", video.title, "】 >>> ", Yellow,
                          "检测到手机端触发403正在切换为Web端...")
                continue
            # mode == 0: Web端仍403，说明是人脸校验，尝试绕过
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ", Yellow,
                      "触发403正在尝试绕过人脸识别...")
            face_err = xxt_api.pass_face_pc_action(
                cache, video.course_id, video.class_id, video.cpi,
                str(video.knowledge_id), video.enc,
                video.job_id, video.object_id, video.mid,
                video.random_capture_time)
            if face_err:
                err_str = str(face_err)
                if "没有历史人脸" in err_str or "上传人脸失败" in err_str:
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】",
                              "【", k_label, "】",
                              "【", video.title, "】 >>> ",
                              BoldRed, f"上传人脸失败，已自动跳过该视频: {face_err}")
                    break
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", video.title, "】 >>> ",
                          Red, f"绕过人脸失败: {face_err}")
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", video.title, "】 >>> ", Green,
                          "绕过人脸成功")
            time.sleep(5)  # Go: 不要删！一定要等待一小段时间
            continue

        # 202/400: Go聚合层ReLogin后重试，仍失败则跳过
        if status_code in (202, 400):
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      BoldRed, f"视频提交异常 status={status_code}，已跳过")
            break

        if status_code == 404:
            time.sleep(10)
            continue

        if status_code and status_code != 200:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      BoldRed, f"视频提交异常 status={status_code}")
            break

        resp_data = safe_json_parse(body) if body else None
        if not resp_data or "isPassed" not in resp_data:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      BoldRed, f"视频提交返回异常: {body[:200] if body else 'empty'}")
            break

        is_passed = resp_data.get("isPassed", False)

        # OutTimeMsg 阈值超限
        out_time_msg = resp_data.get("OutTimeMsg", "")
        if out_time_msg == "观看时长超过阈值":
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      Green, f"观看时长超过阈值，已直接提交 passed={is_passed}")
            break

        if is_passed and playing_time >= video.duration:
            stop_val = 0  # 视频完成后重置计数器
            if over_time == 0:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", video.title, "】 >>> ",
                          "提交状态：", Green, str(is_passed), Default,
                          f" 观看时间：{video.duration}/{video.duration}",
                          f" 观看进度：100.00%")
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", video.title, "】 >>> ",
                          "提交状态：", Green, str(is_passed), Default,
                          f" 观看时间：{video.duration}/{video.duration}",
                          f" 过超时间：{over_time}/{limit_time}",
                          Green, " 过超提交成功",
                          f" 观看进度：100.00%")
            break

        # 日志
        if over_time == 0:
            pct = (playing_time / video.duration *
                   100) if video.duration > 0 else 0
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      "提交状态：", Green, str(is_passed), Default,
                      f" 观看时间：{playing_time}/{video.duration}",
                      f" 观看进度：{pct:.2f}%")
        else:
            pct = (playing_time / video.duration *
                   100) if video.duration > 0 else 0
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      "提交状态：", Green, str(is_passed), Default,
                      f" 观看时间：{playing_time}/{video.duration}",
                      f" 过超时间：{over_time}/{limit_time}",
                      f" 观看进度：{pct:.2f}%")

        # 过超提交检测
        if over_time >= limit_time:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title, "】 >>> ",
                      Red, "过超提交失败，自动进行下一任务...")
            break

        # 时间推进
        remaining = video.duration - playing_time
        if remaining < select_sec and video.duration != playing_time:
            playing_time = video.duration
            time.sleep(max(remaining, 1))
        elif video.duration == playing_time:
            if not video.job_id and video.attachment is None:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", video.title, "】 >>> ",
                          Green, "该视频为非任务点，直接跳入下一视频")
                break
            else:
                over_time += extend_sec
            time.sleep(extend_sec)
        else:
            playing_time += select_sec
            time.sleep(select_sec)


def _video_dto_fetch_action(cache: XueXiTUserCache, video: PointVideoDto) -> bool:
    """视频元数据获取 - 对应 Go VideoDtoFetchAction"""
    meta_body, _ = xxt_api.video_dto_fetch(
        cache, video.object_id, str(video.fid), retry=5)
    if not meta_body:
        return False
    meta = safe_json_parse(meta_body)
    if not meta:
        return False

    dtoken = meta.get("dtoken", "")
    if dtoken:
        video.dtoken = dtoken
    else:
        return False

    duration = meta.get("duration")
    if isinstance(duration, (int, float)):
        video.duration = int(duration)

    status = meta.get("status", "")
    if status == "success":
        return True
    return False


# ============ 音频执行 (完全对齐Go) ============

def _audio_submit_with_relogin(cache: XueXiTUserCache, audio: PointVideoDto,
                               playing_time: int, isdrag: int,
                               mode: int) -> Tuple[str, Optional[Any]]:
    """音频学时提交 + 错误时ReLogin重试 - 对齐Go的AudioSubmitStudyTimeAction聚合层"""
    if mode == 1:
        body, resp = xxt_api.audio_submit_api(
            cache, audio, playing_time, isdrag=isdrag, retry=5)
    else:
        body, resp = xxt_api.video_submit_study_time_api(
            cache, audio, playing_time, isdrag=isdrag, retry=5)

    status_code = resp.status_code if resp else 0
    if status_code == 200 or status_code == 404:
        return body, resp

    # 500/202/400/403: ReLogin后重试
    if status_code in (500, 202, 400, 403):
        xxt_api.relogin(cache)
        if mode == 1:
            body2, resp2 = xxt_api.audio_submit_api(
                cache, audio, playing_time, isdrag=isdrag, retry=5)
        else:
            body2, resp2 = xxt_api.video_submit_study_time_api(
                cache, audio, playing_time, isdrag=isdrag, retry=5)
        return body2, resp2
    return body, resp


def _execute_audio(setting: Setting, user: User, cache: XueXiTUserCache,
                   course: XueXiTCourse, knowledge_item: KnowledgeItem,
                   audio: PointVideoDto):
    """执行音频学习 - 完全对齐 Go ExecuteAudio"""
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    k_label = f"{knowledge_item.label} {knowledge_item.name}".strip(
    ) if knowledge_item.label else knowledge_item.name

    if not _video_dto_fetch_action(cache, audio):
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", k_label, "】",
                  "【", audio.title, "】 >>> ",
                  Red, "音频任务点解析失败，已自动跳过")
        return

    playing_time = audio.play_time
    if not audio.is_passed and audio.play_time == audio.duration:
        playing_time = 0

    over_time = 0
    select_sec = 58
    extend_sec = 5
    limit_time = max(500, audio.duration // 2)
    mode = 1
    stop_val = 0  # 403重试计数器 (对齐Go stopVal)

    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              "【", k_label, "】",
              "【", audio.title, "】 >>> ",
              Yellow, "正在学习音频：", Default,
              f"duration={audio.duration}s")

    while True:
        if playing_time != audio.duration:
            isdrag = 3 if playing_time == audio.play_time else 0
        else:
            isdrag = 0

        # 音频使用 audio_submit_api (移动端) 或 video_submit (PC端)
        body, resp = _audio_submit_with_relogin(
            cache, audio, playing_time, isdrag, mode)

        status_code = resp.status_code if resp else 0

        if status_code == 500:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title, "】 >>> ",
                      BoldRed, "音频提交触发500风控，ReLogin后仍失败，已跳过")
            break

        if status_code == 403:
            # 对齐Go ExecuteAudio (XueXiTongPart.go): mode==1→切换Web端; mode==0→人脸绕过
            if mode == 1:
                mode = 0
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", audio.title, "】 >>> ", Yellow,
                          "检测到手机端触发403正在切换为Web端...")
                continue
            # mode == 0: Web端仍403，尝试人脸绕过
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title, "】 >>> ", Yellow,
                      "触发403正在尝试绕过人脸识别...")
            face_err = xxt_api.pass_face_pc_action(
                cache, audio.course_id, audio.class_id, audio.cpi,
                str(audio.knowledge_id), audio.enc,
                audio.job_id, audio.object_id, audio.mid,
                audio.random_capture_time)
            if face_err:
                err_str = str(face_err)
                if "没有历史人脸" in err_str or "上传人脸失败" in err_str:
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】",
                              "【", k_label, "】",
                              "【", audio.title, "】 >>> ",
                              BoldRed, f"上传人脸失败，已自动跳过该音频: {face_err}")
                    break
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", audio.title, "】 >>> ",
                          Red, f"绕过人脸失败: {face_err}")
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", audio.title, "】 >>> ", Green,
                          "绕过人脸成功")
            time.sleep(5)
            continue

        if status_code == 404:
            time.sleep(10)
            continue

        if status_code and status_code != 200:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title, "】 >>> ",
                      BoldRed, f"音频提交异常 status={status_code}")
            break

        resp_data = safe_json_parse(body) if body else None
        if not resp_data or "isPassed" not in resp_data:
            break

        is_passed = resp_data.get("isPassed", False)

        out_time_msg = resp_data.get("OutTimeMsg", "")
        if out_time_msg == "观看时长超过阈值":
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title, "】 >>> ",
                      Green, "音频提交时长超过阈值，已直接提交")
            break

        if is_passed and playing_time >= audio.duration:
            stop_val = 0  # 音频完成后重置计数器
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title, "】 >>> ",
                      "提交状态：", Green, str(is_passed), Default,
                      f" 观看时间：{audio.duration}/{audio.duration}",
                      f" 观看进度：100.00%")
            break

        if over_time >= limit_time:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title, "】 >>> ",
                      Red, "音频过超提交失败")
            break

        remaining = audio.duration - playing_time
        if remaining < select_sec and audio.duration != playing_time:
            playing_time = audio.duration
            time.sleep(max(remaining, 1))
        elif audio.duration == playing_time:
            if not audio.job_id and audio.attachment is None:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", audio.title, "】 >>> ",
                          Green, "该音频为非任务点，直接跳过")
                break
            else:
                over_time += extend_sec
            time.sleep(extend_sec)
        else:
            playing_time += select_sec
            time.sleep(select_sec)


# ============ 文档执行 ============

def _execute_document(cache: XueXiTUserCache, course: XueXiTCourse,
                      ddto: PointDocumentDto):
    """执行文档学习 - 对应 Go ExecuteDocument"""
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    if not ddto.object_id:
        return

    body, _ = xxt_api.document_submit_api(
        cache, ddto.object_id, str(ddto.knowledge_id), cache.uid, retry=5)
    resp_data = safe_json_parse(body) if body else None

    # Document submit may return {"status": true} or {"download": "...", "filename": "..."}
    if resp_data and (resp_data.get("status") is True or
                      "download" in resp_data or
                      "filename" in resp_data):
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", ddto.title, "】 >>> ",
                  "文档阅览状态：", Green, "True")
    else:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", ddto.title, "】 >>> ",
                  BoldRed, f"文档提交异常: {body[:200] if body else 'empty'}")


# ============ 外链执行 ============

def _execute_hyperlink(cache: XueXiTUserCache, course: XueXiTCourse,
                       hdto: PointHyperlinkDto):
    """执行外链任务 - 对应 Go ExecuteHyperlink"""
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    if not hdto.job_id:
        return
    body, _ = xxt_api.hyperlink_submit_api(
        cache, hdto.job_id, hdto.knowledge_id,
        hdto.course_id, hdto.class_id, hdto.jtoken,
        retry=5)
    resp_data = safe_json_parse(body) if body else None
    if resp_data and resp_data.get("status") is True:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", hdto.title, "】 >>> ",
                  "外链任务点状态：", Green, "True")
    else:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", hdto.title, "】 >>> ",
                  BoldRed, f"外链提交异常: {body[:200] if body else 'empty'}")


# ============ 直播执行 ============

def _execute_live(setting: Setting, user: User, cache: XueXiTUserCache,
                  course: XueXiTCourse, knowledge: KnowledgeItem,
                  ldto: PointLiveDto):
    """执行直播任务 - 对应 Go ExecuteLive
    流程: PullLiveInfo → 检查开播 → LiveCreateRelation → 循环提交进度直到>=90%
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    pass_value = 90.0

    # 拉取直播信息
    body, _ = xxt_api.pull_live_info_api(
        cache, ldto.live_id, course.course_id, course.key, retry=5)
    live_data = safe_json_parse(body) if body else None
    if live_data:
        ldto.live_status_code = live_data.get(
            "liveStatusCode", ldto.live_status_code)
        ldto.video_complete_percent = float(
            live_data.get("videoCompletePercent", 0))

    # 检查是否开播
    if ldto.live_status_code == 0:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", ldto.title, "】 >>> ", Yellow,
                  "该直播任务点还未开播，已自动跳过")
        return

    # 建立联系
    relation_body, relation_err = xxt_api.live_create_relation_api(
        cache, ldto.live_id, course.course_id, course.key,
        str(ldto.knowledge_id), retry=5)
    if relation_err:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", ldto.title, "】",
                  BoldRed, f"直播建立联系失败: {relation_err}")
    else:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", ldto.title, "】",
                  Green, "直播建立联系成功")

    # 循环提交进度
    max_rounds = 200  # 安全上限
    for _ in range(max_rounds):
        submit_body, submit_err = xxt_api.live_submit_api(
            cache, ldto.live_id, course.course_id, course.key,
            str(ldto.knowledge_id), ldto.vdoid, ldto.stream_name,
            ldto.aid, playing_time=30, retry=3)

        # 更新进度
        info_body, _ = xxt_api.pull_live_info_api(
            cache, ldto.live_id, course.course_id, course.key, retry=3)
        info_data = safe_json_parse(info_body) if info_body else None
        if info_data:
            ldto.video_complete_percent = float(
                info_data.get("videoCompletePercent", 0))

        if submit_err:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", knowledge.name, "】",
                      "【", ldto.title, "】",
                      BoldRed, f"直播提交异常: {submit_err}")

        if "@success" in (submit_body or ""):
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", knowledge.name, "】",
                      "【", ldto.title, "】 >>> ",
                      "直播任务点状态：", Green, submit_body,
                      " 观看进度：", Green, f"{ldto.video_complete_percent:.2f}%")

        if ldto.video_complete_percent >= pass_value:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", knowledge.name, "】",
                      "【", ldto.title, "】 >>> ",
                      Green, "直播任务点已完成")
            return

        time.sleep(30)


# ============ 讨论执行 ============

def _execute_bbs(setting: Setting, user: User, cache: XueXiTUserCache,
                 course: XueXiTCourse, knowledge: KnowledgeItem,
                 bdto: PointBBsDto):
    """执行讨论任务 - 对齐Go ExecuteBbsTest + PullPhoneBbsInfoAction
    流程: PullPhoneBbsInfoApi(HTML) → 提取topicId/classId →
          PullPhoneBbsDetailApi(JSON) → 获取uuid/title/content →
          AI答题 → AnswerPhoneBbsApi
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    # 1. 拉取讨论章节页面HTML - 对齐Go PullPhoneBbsInfoApi
    topic_body, _topic_resp = xxt_api.pull_phone_bbs_info_api(
        cache, bdto.mid, bdto.job_id, bdto.knowledge_id,
        course.course_id, bdto.class_id, retry=5)
    if not topic_body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", bdto.title, "】",
                  BoldRed, "拉取讨论页面失败，已自动跳过")
        return

    # 2. 解析HTML提取字段 - 对齐Go PullPhoneBbsInfoAction
    #    Go提取: groupId, bbsId, topicId, classId, courseId, classChatId, role
    bbs_group_id = ""
    bbs_bbs_id = ""
    bbs_topic_id = ""
    bbs_class_id = ""
    bbs_course_id = ""
    bbs_class_chat_id = ""
    bbs_role = ""
    try:
        from bs4 import BeautifulSoup as BS
        soup = BS(topic_body, "html.parser")
        gid_input = soup.find("input", id="groupId")
        if gid_input:
            bbs_group_id = gid_input.get("value", "")
        bid_input = soup.find("input", id="bbsId")
        if bid_input:
            bbs_bbs_id = bid_input.get("value", "")
        tid_input = soup.find("input", id="topicId")
        if tid_input:
            bbs_topic_id = tid_input.get("value", "")
        # 对齐Go: 使用regex提取classId/courseId/classChatId/role
        for m in re.finditer(r'classId:\s*"([^"]+)"|courseId:\s*"([^"]+)"|classChatId:\s*"([^"]+)"|role:\s*"([^"]+)"', topic_body):
            if m.group(1):
                bbs_class_id = m.group(1)
            if m.group(2):
                bbs_course_id = m.group(2)
            if m.group(3):
                bbs_class_chat_id = m.group(3)
            if m.group(4):
                bbs_role = m.group(4)
    except Exception:
        pass

    if not bbs_topic_id:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", bdto.title, "】",
                  BoldRed, "无法解析讨论topicId，已自动跳过")
        return

    final_class_id = bbs_class_id or bdto.class_id

    # 3. 拉取讨论详细信息 - 对齐Go PullPhoneBbsDetailApi
    detail_body, _detail_resp = xxt_api.pull_phone_bbs_detail_api(
        cache, bbs_topic_id, retry=3)
    topic_uuid = ""
    topic_title = bdto.title or "发表讨论回复"
    topic_content = ""
    if detail_body:
        detail_data = safe_json_parse(detail_body)
        if detail_data and "data" in detail_data:
            d = detail_data["data"]
            topic_uuid = d.get("uuid", "")
            topic_title = d.get("title", topic_title)
            topic_content = d.get("text_content", "")

    if not topic_uuid:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", bdto.title, "】",
                  BoldRed, "无法获取讨论uuid，已自动跳过")
        return

    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              "【", knowledge.name, "】",
              "【", bdto.title, "】",
              Yellow, "正在执行讨论任务点...")

    # 4. 根据答题模式获取回答内容
    content = ""
    if cc.auto_exam == 1:
        try:
            from logic.core.ai_client import ai_problem_message
            ai = setting.ai_setting
            prompt = topic_title
            if topic_content:
                prompt = topic_title + "\n" + topic_content
            answer = ai_problem_message(
                ai.ai_url, ai.model, ai.api_key, ai.ai_type, prompt)
            content = answer if answer else "同意"
        except Exception:
            content = "同意"
    elif cc.auto_exam == 3:
        try:
            body, _ = xxt_api.xxt_ai_api(
                cache, topic_title,
                course.course_id, course.key, str(course.cpi))
            data = safe_json_parse(body) if body else None
            content = data.get("answer", "同意") if data else "同意"
        except Exception:
            content = "同意"
    else:
        content = "同意"

    # 5. 发表讨论回复 - 对齐Go AnswerPhoneBbsApi
    reply_body, reply_err = xxt_api.answer_phone_bbs_api(
        cache, final_class_id, topic_uuid, content, retry=3)
    # 对齐Go: 解析JSON检查result字段
    reply_data = safe_json_parse(reply_body) if reply_body else None
    if reply_err or not reply_data:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", bdto.title, "】",
                  BoldRed, f"讨论任务点提交异常: {reply_err or '响应为空'}")
    else:
        result_val = reply_data.get("result", None)
        msg_val = reply_data.get("msg", "")
        if result_val == 1 or reply_data.get("status") is True:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", knowledge.name, "】",
                      "【", bdto.title, "】 >>> ",
                      "讨论任务点状态：", Green, f"{msg_val or '提交成功'}")
        else:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", knowledge.name, "】",
                      "【", bdto.title, "】",
                      BoldRed, f"讨论任务点提交异常: {reply_body[:200]}")


# ============ 相似度匹配 - 对齐Go qutils.SimilarityArraySelect ============

def _levenshtein(a: str, b: str) -> int:
    """Levenshtein编辑距离 - 对齐Go qutils.Levenshtein"""
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    # 优化：只用一维数组
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[lb]


def _similarity(a: str, b: str) -> float:
    """相似度 0.0~1.0 - 对齐Go qutils.Similarity"""
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / max_len


def _similarity_array_select(target: str, options: List[str]) -> List[str]:
    """对齐Go qutils.SimilarityArraySelect
    对千单选题: 返回单个最大匹配字母 ["A"]
    对千多选题: target可能包含多个答案(用逗号/顿号/换行分隔), 返回排序后的字母列表
    """
    if not target or not options:
        return ["A"]

    # 多选题: 尝试分割AI答案 (常见分隔符: ，、, \n ; 等)
    # 对齐Go: for _, item := range ch.Answers { answers += SimilarityArraySelect(item, candidateSelects) }
    parts = re.split(r'[,，、;\n|/]+', target)
    parts = [p.strip().strip("'\"\u2018\u2019\u201c\u201d\u300c\u300d\u300e\u300f")
             for p in parts if p.strip()]

    if not parts:
        parts = [target]

    letters_map = {}
    for part in parts:
        best_score = -1.0
        best_idx = 0
        for i, opt in enumerate(options):
            score = _similarity(part, opt)
            # 也尝试部分匹配: AI可能只返回选项的一部分
            if score < 0.5 and len(part) > 2:
                # 检查是否包含关系（作为候选）
                if part in opt or opt in part:
                    score = max(score, 0.6)
            if score > best_score:
                best_score = score
                best_idx = i
        letter = chr(65 + best_idx)
        letters_map[letter] = True

    # 如果完全无法匹配，尝试检查答案本身是否是字母
    if all(score < 0.2 for score in [_similarity(p, options[0] if options else "") for p in parts]):
        direct = []
        for ch in target.upper():
            if ch.isalpha() and ord(ch) - 65 < len(options):
                direct.append(ch)
        if direct:
            return sorted(set(direct))

    result = sorted(letters_map.keys())
    return result if result else ["A"]


# ============ 章测自动答题 ============

def _chapter_test_action(setting: Setting, user: User, cache: XueXiTUserCache,
                         course: XueXiTCourse, knowledge: KnowledgeItem,
                         wdto: PointWorkDto):
    """章测自动答题 - 对应 Go chapterTestAction
    流程: WorkFetchQuestion → 解析题目+元数据 → AI答题 → WorkNewSubmitAnswer
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    # 获取题目页面
    body, resp = xxt_api.work_fetch_question_api(cache, wdto, retry=5)
    if not body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  BoldRed, f"章测题目页面获取失败 (status={resp.status_code if resp else 'N/A'})")
        return

    if "已截止" in body or "不能作答" in body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Yellow, "该试卷已到截止时间，已自动跳过")
        return

    # 解析题目并提取元数据
    questions, meta = _parse_work_questions_v2(body)
    if not questions:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Yellow, "该章测无题目，已自动跳过")
        return

    mode_str = ""
    if cc.auto_exam == 1:
        mode_str = "AI自动"
    elif cc.auto_exam == 2:
        mode_str = "外挂题库"
    elif cc.auto_exam == 3:
        mode_str = "内置AI"

    title = meta.get("title", knowledge.name)
    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              f"<{mode_str}>",
              "【", course.course_name, "】",
              "【", f"{knowledge.label} {knowledge.name}".strip(), "】",
              "【", title, "】",
              Yellow, f"正在{mode_str}写章节作业(共{len(questions)}题)...")

    # 对每道题AI答题
    answerwqbid = ""
    ai_answered = 0  # AI实际给出答案的题数
    ai_raw_answers = []  # 调试用：记录AI原始返回值
    for q in questions:
        q_type = q.get("type", "")
        q_text = q.get("text", "")
        q_id = q.get("id", "")
        answer = ""

        # 提取选项纯文本(去掉 "A." 前缀) - 对齐Go TurnStandardQuestion
        raw_options = q.get("options", [])
        opt_texts_for_ai = []
        for opt in raw_options:
            dot_idx = opt.find(".")
            if dot_idx >= 0:
                opt_texts_for_ai.append(opt[dot_idx+1:].strip())
            else:
                opt_texts_for_ai.append(opt)

        if cc.auto_exam == 1:
            try:
                from logic.core.ai_client import ai_problem_message
                ai = setting.ai_setting
                # 对齐Go: 传递题型和选项，AI返回JSON数组格式答案
                answer = ai_problem_message(
                    ai.ai_url, ai.model, ai.api_key, ai.ai_type,
                    q_text, options=opt_texts_for_ai, q_type=q_type)
            except Exception:
                answer = ""
        elif cc.auto_exam == 3:
            try:
                ai_body, _ = xxt_api.xxt_ai_api(
                    cache, q_text, course.course_id, course.key, str(course.cpi))
                ai_data = safe_json_parse(ai_body) if ai_body else None
                answer = ai_data.get("answer", "") if ai_data else ""
            except Exception:
                answer = ""
        else:
            answer = "A"

        # 清理AI答案中的引号和多余空白 - 防止SimilarityArraySelect匹配失败
        # AI常返回 '认清中国国情' 或 "认清中国国情" 带引号格式
        if answer:
            answer = answer.strip()
            # 去除首尾成对的单引号或双引号
            if len(answer) >= 2 and answer[0] == answer[-1] and answer[0] in ("'", '"', '\u2018', '\u2019', '\u201c', '\u201d'):
                answer = answer[1:-1].strip()
            # 也处理中文引号「」『』
            if len(answer) >= 2 and answer[0] in ('「', '『') and answer[-1] in ('」', '』'):
                answer = answer[1:-1].strip()

        # 记录AI原始返回（调试用）
        ai_raw_answers.append(repr(answer[:50]) if answer else "<empty>")

        # 记录AI是否实际给出了答案(在AnswerFixedPattern之前)
        if answer.strip():
            ai_answered += 1

        # AnswerFixedPattern: 防止留空
        if not answer and q_type in ("single_choice", "multiple_choice", "choice", "judge"):
            answer = "A" if q_type in (
                "single_choice", "choice", "multiple_choice") else "true"

        # AnswerFixedPattern: 判断题答案修正 - 对齐Go AnswerFixedPattern
        if q_type == "judge":
            answer = answer.replace("对", "正确").replace(
                "√", "正确").replace("×", "错误")

        if q_id:
            answerwqbid += q_id + ","
            q["answer"] = answer

        time.sleep(random.randint(1, 2))

    # 调试日志：显示AI返回的原始答案
    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              f"<{mode_str}>",
              "【", course.course_name, "】",
              Yellow, f"[AI调试] ai_answered={ai_answered} auto_exam={cc.auto_exam} "
              f"题数={len(questions)} answers={ai_raw_answers}")

    # 检查AI是否可用 - 如果AI没有给出任何实际答案，跳过提交
    if ai_answered == 0 and cc.auto_exam in (1, 3) and questions:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  "【", f"{knowledge.label} {knowledge.name}".strip(), "】",
                  "【", title, "】",
                  Yellow, f"AI未返回任何答案(余额不足?)，跳过提交")
        return

    # 构建提交数据 - 完全对齐Go WorkNewSubmitAnswer的multipart fields
    is_submit = cc.exam_auto_submit in (1, 2)
    submit_state = "" if is_submit else "1"  # Go: ""为交卷, "1"为暂存

    # totalQuestionNum: 必须使用HTML中的原始值(通常是哈希字符串)
    # Go代码直接传递: question.TotalQuestionNum = informMap["totalQuestionNum"]
    # 服务器会验证此值与session中存储的值是否匹配
    # 绝对不能覆盖为数字! 否则服务器返回code-2
    raw_total_q = meta.get("totalQuestionNum", "")
    total_q_num = raw_total_q  # 保持原样，不转换为数字
    if not total_q_num:
        total_q_num = str(len(questions))  # 兆底：如果HTML中完全没有，才用题数

    submit_data = {
        "pyFlag": submit_state,
        "courseId": meta.get("courseId", wdto.course_id),
        "classId": meta.get("classId", wdto.class_id),
        "api": meta.get("api", ""),
        "workAnswerId": meta.get("workAnswerId", ""),
        "answerId": meta.get("answerId", ""),
        "totalQuestionNum": total_q_num,
        "fullScore": meta.get("fullScore", ""),
        "knowledgeid": meta.get("knowledgeid", str(wdto.knowledge_id)),
        "oldSchoolId": meta.get("oldSchoolId", ""),
        "oldWorkId": meta.get("oldWorkId", wdto.work_id),
        "jobid": meta.get("jobid", wdto.job_id),
        "workRelationId": meta.get("workRelationId", ""),
        "enc": "",
        "enc_work": meta.get("enc_work", ""),
        "userId": cache.cookie_dict.get("_uid", cache.uid),
        "cpi": meta.get("cpi", wdto.cpi),
        "workTimesEnc": "",
        "randomOptions": meta.get("randomOptions", "false"),
        "isAccessibleCustomFid": "0",
        # 注意: Go的WorkNewSubmitAnswer不发送cfid和uploadEnc字段!
        # 虽然ParseWorkInform读取了它们,但提交时从未写入multipart form
    }

    # 添加每道题的答案 - 完全对齐Go WorkNewSubmitAnswer的各题型写入
    # 关键: Go代码中answertype写在answer之后! (writer.WriteField("answer"+qid) 先于 answertype)
    for q in questions:
        q_id = q.get("id", "")
        if not q_id:
            continue
        aw_type = q.get("answertype", "0")
        q_type = q.get("type", "")
        answer = q.get("answer", "")
        # 注意: answertype 在各题型的 answer 之后写入 (对齐Go)

        if q_type == "single_choice":
            # 单选题: 不分割答案! AI可能返回含逗号的完整选项文本
            # 对齐Go: for _, item := range ch.Answers { answers += SimilarityArraySelect(item, opts) }
            # Go的ch.Answers中每个元素都是完整的，不在SimilarityArraySelect内部做分割
            options = q.get("options", [])
            if options:
                opt_texts = []
                for opt in options:
                    dot_idx = opt.find(".")
                    if dot_idx >= 0:
                        opt_texts.append(opt[dot_idx+1:].strip())
                    else:
                        opt_texts.append(opt)
                # 单选题: 整个answer作为一个整体匹配，返回单个字母
                best_score = -1.0
                best_idx = 0
                for i, opt_text in enumerate(opt_texts):
                    score = _similarity(answer, opt_text)
                    if score < 0.5 and len(answer) > 2:
                        if answer in opt_text or opt_text in answer:
                            score = max(score, 0.6)
                    if score > best_score:
                        best_score = score
                        best_idx = i
                submit_data[f"answer{q_id}"] = chr(65 + best_idx)
            else:
                submit_data[f"answer{q_id}"] = answer
            submit_data[f"answertype{q_id}"] = aw_type

        elif q_type == "multiple_choice":
            # 多选题: 可以按逗号分割，每个部分分别匹配
            options = q.get("options", [])
            if options:
                opt_texts = []
                for opt in options:
                    dot_idx = opt.find(".")
                    if dot_idx >= 0:
                        opt_texts.append(opt[dot_idx+1:].strip())
                    else:
                        opt_texts.append(opt)
                result_letters = _similarity_array_select(answer, opt_texts)
                submit_data[f"answer{q_id}"] = "".join(result_letters)
            else:
                submit_data[f"answer{q_id}"] = answer
            submit_data[f"answertype{q_id}"] = aw_type

        elif q_type == "judge":
            # 对齐Go: "正确"→"true", "错误"→"false"
            judge_answer = answer
            if judge_answer == "正确":
                judge_answer = "true"
            elif judge_answer == "错误":
                judge_answer = "false"
            elif judge_answer not in ("true", "false"):
                # 如果AI返回的不是标准格式，默认true
                judge_answer = "true"
            submit_data[f"answer{q_id}"] = judge_answer
            submit_data[f"answertype{q_id}"] = aw_type

        elif q_type == "fill":
            # 对齐Go: answer{qid}{index} → tiankongsize → answertype
            answer_fields = q.get("answer_fields", {})
            for k, v in answer_fields.items():
                if k.startswith(f"answer{q_id}"):
                    submit_data[k] = answer  # 所有空填同一个AI答案
                elif k.startswith(f"tiankongsize{q_id}"):
                    submit_data[k] = v
            submit_data[f"answertype{q_id}"] = aw_type

        else:
            # 简答/论述/名词解释/其它
            submit_data[f"answer{q_id}"] = answer
            submit_data[f"answertype{q_id}"] = aw_type

    # 确保enc_work和totalQuestionNum在submit_data中
    submit_data["enc_work"] = meta.get("enc_work", "")
    # 重要: 不要覆盖totalQuestionNum! 保持HTML中的原始哈希值
    # Go代码: writer.WriteField("totalQuestionNum", totalQuestionNum) 直接使用HTML原始值

    # Go版顺序: answer/answertype字段在answerwqbid之前
    # 对齐Go WorkNewSubmitAnswer: writer.WriteField("answerwqbid", answerwqbid) 在最后
    submit_data["answerwqbid"] = answerwqbid

    # 第二层保护：提交前再次验证AI答案不为空
    if ai_answered == 0 and cc.auto_exam in (1, 3):
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  "【", f"{knowledge.label} {knowledge.name}".strip(), "】",
                  "【", title, "】",
                  Yellow, f"[保护] AI未返回答案，阻止提交(ai_answered={ai_answered})")
        return

    # 详细调试: 输出所有答案字段
    answer_debug = []
    for q in questions:
        q_id = q.get('id', '')
        q_type = q.get('type', '')
        raw_ans = q.get('answer', '')
        submitted = submit_data.get(f'answer{q_id}', '<MISSING>')
        answer_debug.append(
            f"q{q_id}({q_type}):raw={repr(raw_ans[:30])}→sub={repr(submitted[:20])}")
    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              f"<{mode_str}>",
              "【", course.course_name, "】",
              Yellow, f"[提交调试] {' | '.join(answer_debug[:8])}")
    if len(answer_debug) > 8:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  Yellow, f"[提交调试2] {' | '.join(answer_debug[8:16])}")
    if len(answer_debug) > 16:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  Yellow, f"[提交调试3] {' | '.join(answer_debug[16:])}")

    result_body, result_resp = xxt_api.work_new_submit_answer_api(
        cache, wdto.course_id, wdto.class_id,
        str(wdto.knowledge_id), wdto.work_id,
        submit_data, retry=3)

    # 响应验证 - 对齐Go: gojsonq.New().JSONString(resultStr).Find("status")
    status_code = result_resp.status_code if result_resp else 0
    result_str = result_body or ""
    is_success = False
    try:
        resp_json = safe_json_parse(result_str)
        if resp_json and resp_json.get("status") is True:
            is_success = True
    except Exception:
        pass

    if is_success:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  "【", f"{knowledge.label} {knowledge.name}".strip(), "】",
                  "【", title, "】",
                  Green, f"章节作业{mode_str}答题完毕,服务器返回信息：{result_str[:300]}")
    else:
        # 诊断日志：显示完整submit_data
        submit_fields = []
        for sk, sv in submit_data.items():
            if sk.startswith('answer') and not sk.startswith('answerwqbid'):
                submit_fields.append(f"{sk}={repr(str(sv)[:40])}")
            elif sk in ('pyFlag', 'courseId', 'classId', 'totalQuestionNum',
                        'enc_work', 'workAnswerId', 'answerId', 'userId',
                        'knowledgeid', 'oldWorkId', 'jobid', 'cpi'):
                submit_fields.append(f"{sk}={repr(str(sv)[:30])}")
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  "【", f"{knowledge.label} {knowledge.name}".strip(), "】",
                  "【", title, "】",
                  BoldRed, f"章节作业{mode_str}答题失败(status={status_code}),服务器返回信息：{result_str[:300]}")
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  Yellow, f"[完整提交字段] {' | '.join(submit_fields[:15])}")
        if len(submit_fields) > 15:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      f"<{mode_str}>",
                      "【", course.course_name, "】",
                      Yellow, f"[完整提交字段2] {' | '.join(submit_fields[15:])}")


def _parse_work_questions(html_body: str) -> List[Dict]:
    """从作业页面HTML解析题目列表"""
    questions = []
    # 匹配题目块 - 常见格式
    # 查找所有题目input或textarea
    pattern = re.compile(
        r'<input[^>]*name="answer(\w+)"[^>]*value="([^"]*)"[^>]*>',
        re.IGNORECASE)
    for m in pattern.finditer(html_body):
        questions.append({
            "id": m.group(1),
            "text": m.group(2),
            "type": "choice",
        })
    # 如果没有input，尝试找textarea
    if not questions:
        pattern2 = re.compile(
            r'<textarea[^>]*name="answer(\w+)"[^>]*>(.*?)</textarea>',
            re.IGNORECASE | re.DOTALL)
        for m in pattern2.finditer(html_body):
            questions.append({
                "id": m.group(1),
                "text": m.group(2).strip(),
                "type": "text",
            })
    return questions


def _parse_work_questions_v2(html_body: str) -> Tuple[List[Dict], Dict]:
    """从作业页面HTML解析题目列表+元数据 - 对齐Go ParseWorkQuestionAction
    使用 BeautifulSoup + div.Py-mian1 块解析每道题（与Go的ParseQuestionSets完全对齐）
    Returns: (questions_list, metadata_dict)
    """
    questions = []
    meta = {}
    if not html_body:
        return questions, meta

    # === 提取元数据 - 对齐Go ParseWorkInform ===
    meta_fields = ["userId", "courseId", "classId", "api", "workAnswerId",
                   "answerId", "totalQuestionNum", "fullScore", "knowledgeid",
                   "oldSchoolId", "oldWorkId", "jobid", "workRelationId",
                   "enc", "enc_work", "cpi", "workTimesEnc", "randomOptions",
                   "cfid", "uploadEnc", "workId"]
    for field in meta_fields:
        val = _html_input_get(html_body, field)
        if val:
            meta[field] = val
    # 提取title
    title_match = re.search(
        r'class=["\'][^"\']*chapter-title[^"\']*["\'][^>]*workname=["\']([^"\']*)["\']',
        html_body, re.IGNORECASE)
    if title_match:
        meta["title"] = title_match.group(1)
    if "title" not in meta:
        t_match = re.search(
            r'<title[^>]*>(.*?)</title>', html_body, re.IGNORECASE | re.DOTALL)
        if t_match:
            meta["title"] = re.sub(r'<[^>]+>', '', t_match.group(1)).strip()

    # === Go题目类型映射 ===
    type_cn_to_key = {
        "单选题": "single_choice", "多选题": "multiple_choice",
        "判断题": "judge", "填空题": "fill",
        "简答题": "short", "名词解释": "term_explanation",
        "论述题": "essay", "连线题": "matching", "辨析题": "judge",
        "投票题": "single_choice",
    }
    type_to_answertype = {
        "single_choice": "0", "multiple_choice": "1", "fill": "2",
        "judge": "3", "short": "4", "term_explanation": "5",
        "essay": "6", "matching": "11",
    }

    # === 使用BeautifulSoup解析 - 完全对齐Go goquery ===
    try:
        soup = BeautifulSoup(html_body, "html.parser")
    except Exception:
        return questions, meta

    # 对齐Go: questionNodes := doc.Find("div.Py-mian1")
    question_nodes = soup.find_all("div", class_="Py-mian1")

    for idx, node in enumerate(question_nodes):
        # 对齐Go: dataAttr, exists := questionNode.Attr("data")
        qid = node.get("data", "") or f"question_{idx+1}"

        # 提取题目类型 (Go: .Py-m1-title .quesType)
        type_text = ""
        title_div = node.find(class_="Py-m1-title")
        if title_div:
            ques_type_span = title_div.find(class_="quesType")
            if ques_type_span:
                raw_type = ques_type_span.get_text(strip=True)
                type_in_brackets = re.search(r'\[([^\]]+)\]', raw_type)
                type_text = type_in_brackets.group(
                    1) if type_in_brackets else raw_type
        q_type = type_cn_to_key.get(type_text, "short")
        aw_type = type_to_answertype.get(q_type, "0")

        # 提取题目文本 (Go: .Py-m1-title .workTextWrap)
        text = ""
        if title_div:
            text_wrap = title_div.find(class_="workTextWrap")
            if text_wrap:
                text = text_wrap.get_text(strip=True)
        if not text:
            text = f"题目{qid}"

        # 提取选项和构建答案字段
        options = []
        answer_fields = {}

        if q_type in ("single_choice", "multiple_choice"):
            # 对齐Go: .answerList.singleChoice li / .answerList.multiChoice li
            css_class = "singleChoice" if q_type == "single_choice" else "multiChoice"
            answer_list = node.find(
                class_=lambda c: c and "answerList" in c and css_class in c)
            if answer_list:
                for li in answer_list.find_all("li"):
                    em = li.find("em", class_="choose-opt")
                    if em:
                        letter = em.get(
                            "id-param", "") or em.get_text(strip=True)
                        cc_content = li.find("cc")
                        opt_text = cc_content.get_text(
                            strip=True) if cc_content else ""
                        if letter:
                            options.append(f"{letter}. {opt_text}")
            answer_fields[f"answer{qid}"] = ""

        elif q_type == "judge":
            # 对齐Go: .answerList.panduan li, 提取val-param属性
            answer_list = node.find(
                class_=lambda c: c and "answerList" in c and "panduan" in c)
            if answer_list:
                for li in answer_list.find_all("li"):
                    val_param = li.get("val-param", "")
                    if val_param == "true":
                        options.append("对")
                    elif val_param == "false":
                        options.append("错")
            answer_fields[f"answer{qid}"] = ""

        elif q_type == "fill":
            # 对齐Go: ul.blankList2 提取空数
            blank_lists = node.find_all("ul", class_="blankList2")
            blank_count = 0
            for bl in blank_lists:
                p_tags = bl.find_all("p")
                blank_count += len(p_tags)
            if blank_count == 0:
                blank_count = 1
            for bi in range(1, blank_count + 1):
                answer_fields[f"answer{qid}{bi}"] = ""
            answer_fields[f"tiankongsize{qid}"] = str(blank_count)

        else:
            # 简答/论述/名词解释/其它
            answer_fields[f"answer{qid}"] = ""

        questions.append({
            "id": qid,
            "text": text,
            "type": q_type,
            "answertype": aw_type,
            "options": options,
            "answer_fields": answer_fields,
        })

    return questions, meta


def _parse_exam_list_html(html_body: str) -> List[Dict]:
    """Parse exam list from chaoxing HTML - matches Go PullExamListAction
    Go uses goquery: doc.Find("ul.nav li") with li.Attr("data")
    """
    exam_list = []
    if not html_body:
        return exam_list

    # Match <li ... data="URL"> ... </li> within ul.nav
    # First try to find ul.nav block
    nav_match = re.search(r'<ul[^>]*class=["\'][^"\']*nav[^"\']*["\'][^>]*>(.*?)</ul>',
                          html_body, re.IGNORECASE | re.DOTALL)
    search_html = nav_match.group(1) if nav_match else html_body

    li_pattern = re.compile(
        r'<li[^>]*\bdata=["\']([^"\']+)["\'][^>]*>(.*?)</li>',
        re.IGNORECASE | re.DOTALL)

    for li_match in li_pattern.finditer(search_html):
        raw_url = li_match.group(1)
        li_inner = li_match.group(2)

        # Parse URL params
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(raw_url if raw_url.startswith(
            "http") else "http://x?" + raw_url.lstrip("?"))
        params = {}
        for k, v in parse_qs(parsed.query).items():
            params[k] = v[0] if v else ""

        # Extract name from <p> tag within <div>
        name_match = re.search(
            r'<p[^>]*>(.*?)</p>', li_inner, re.IGNORECASE | re.DOTALL)
        name = re.sub(r'<[^>]+>', '', name_match.group(1)
                      ).strip() if name_match else ""

        # Extract status from first <span>
        span_matches = list(re.finditer(
            r'<span[^>]*>(.*?)</span>', li_inner, re.IGNORECASE | re.DOTALL))
        status = re.sub(r'<[^>]+>', '', span_matches[0].group(1)
                        ).strip() if span_matches else ""
        remain = re.sub(r'<[^>]+>', '', span_matches[1].group(1)
                        ).strip() if len(span_matches) > 1 else ""

        exam_list.append({
            "name": name or f"考试{params.get('taskrefId', '')}",
            "status": status,
            "remainTime": remain,
            "rawUrl": raw_url,
            "taskrefId": params.get("taskrefId", ""),
            "courseId": params.get("courseId", ""),
            "userId": params.get("userId", ""),
            "clazzId": params.get("clazzId", ""),
            "type": params.get("type", ""),
            "enc_task": params.get("enc_task", ""),
            "msgId": params.get("msgId", "0"),
        })

    if not exam_list:
        json_data = safe_json_parse(html_body)
        if json_data:
            if isinstance(json_data, list):
                return json_data
            if isinstance(json_data, dict):
                return json_data.get("data", [])
    return exam_list


def _parse_work_list_html(html_body: str) -> List[Dict]:
    """Parse work list from chaoxing HTML - matches Go PullWorkListAction
    Go uses goquery: doc.Find("ul.nav li") with li.Attr("data")
    """
    work_list = []
    if not html_body:
        return work_list

    # Match <li ... data="URL"> ... </li> within ul.nav
    nav_match = re.search(r'<ul[^>]*class=["\'][^"\']*nav[^"\']*["\'][^>]*>(.*?)</ul>',
                          html_body, re.IGNORECASE | re.DOTALL)
    search_html = nav_match.group(1) if nav_match else html_body

    li_pattern = re.compile(
        r'<li[^>]*\bdata=["\']([^"\']+)["\'][^>]*>(.*?)</li>',
        re.IGNORECASE | re.DOTALL)

    for li_match in li_pattern.finditer(search_html):
        raw_url = li_match.group(1)
        li_inner = li_match.group(2)

        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(raw_url if raw_url.startswith(
            "http") else "http://x?" + raw_url.lstrip("?"))
        params = {}
        for k, v in parse_qs(parsed.query).items():
            params[k] = v[0] if v else ""

        name_match = re.search(
            r'<p[^>]*>(.*?)</p>', li_inner, re.IGNORECASE | re.DOTALL)
        name = re.sub(r'<[^>]+>', '', name_match.group(1)
                      ).strip() if name_match else ""

        span_matches = list(re.finditer(
            r'<span[^>]*>(.*?)</span>', li_inner, re.IGNORECASE | re.DOTALL))
        status = re.sub(r'<[^>]+>', '', span_matches[0].group(1)
                        ).strip() if span_matches else ""
        remain = re.sub(r'<[^>]+>', '', span_matches[1].group(1)
                        ).strip() if len(span_matches) > 1 else ""

        work_list.append({
            "name": name or f"作业{params.get('taskrefId', '')}",
            "status": status,
            "remainTime": remain,
            "rawUrl": raw_url,
            "taskrefId": params.get("taskrefId", ""),
            "courseId": params.get("courseId", ""),
            "userId": params.get("userId", ""),
            "clazzId": params.get("clazzId", ""),
            "type": params.get("type", ""),
            "enc_task": params.get("enc_task", ""),
            "msgId": params.get("msgId", "0"),
        })

    if not work_list:
        json_data = safe_json_parse(html_body)
        if json_data:
            if isinstance(json_data, list):
                return json_data
            if isinstance(json_data, dict):
                return json_data.get("data", [])
    return work_list


# ============ 课程级作业执行 ============

def _write_course_work_and_exam(setting: Setting, user: User,
                                cache: XueXiTUserCache, course: XueXiTCourse):
    """课程级作业和考试 - 对应 Go writeCourseWorkAndExam"""
    cc = user.courses_custom
    if cc.auto_exam == 0:
        return

    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    # AI可用性检查
    if cc.auto_exam == 1:
        from logic.core.ai_client import ai_check
        ai = setting.ai_setting
        err = ai_check(ai.ai_url, ai.model, ai.api_key, ai.ai_type)
        if err:
            log_print(INFO, f"[{platform}]",
                      BoldRed, f"<{ai.ai_type}> AI不可用: {err}")
            return

    # 作业
    if (cc.cx_work_sw or 0) == 1:
        _work_action(setting, user, cache, course)

    # 考试
    if (cc.cx_exam_sw or 0) == 1:
        _exam_action(setting, user, cache, course)


def _html_input_get(html: str, elem_id: str) -> str:
    """从HTML中提取指定id的input的value - 对应 Go paperDoc.Find("#id").Attr("value")
    Also falls back to name= attribute for compatibility"""
    m = re.search(r'id=["\']' + re.escape(elem_id) +
                  r'["\'][^>]*value=["\']([^"\']*)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'value=["\']([^"\']*)["\'][^>]*id=["\']' +
                      re.escape(elem_id) + r'["\']', html, re.IGNORECASE)
    # Fallback: try name= attribute (some hidden fields use name instead of id)
    if not m:
        m = re.search(r'name=["\']' + re.escape(elem_id) +
                      r'["\'][^>]*value=["\']([^"\']*)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'value=["\']([^"\']*)["\'][^>]*name=["\']' +
                      re.escape(elem_id) + r'["\']', html, re.IGNORECASE)
    return m.group(1) if m else ""


def _html_input_name_get(html: str, name: str) -> str:
    """从HTML中提取指定name的input的value"""
    m = re.search(r'name=["\']' + re.escape(name) +
                  r'["\'][^>]*value=["\']([^"\']*)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'value=["\']([^"\']*)["\'][^>]*name=["\']' +
                      re.escape(name) + r'["\']', html, re.IGNORECASE)
    return m.group(1) if m else ""


def _html_work_question_turn_entity(html: str) -> Dict:
    """解析作业题目HTML提取元数据 - 对应 Go HtmlWorkQuestionTurnEntity"""
    q = {}
    qid = _html_input_get(html, "questionId")
    q["questionId"] = qid
    q["questionTypeCode"] = _html_input_name_get(html, f"type{qid}")
    # Extract questionTypeStr from span.focusSpan
    focus_match = re.search(
        r'class=["\']focusSpan["\'][^>]*aria-label=["\']([^"\']*)["\']', html)
    if focus_match:
        qtype_str = re.sub(r'^\s*\d+\.\s*', '', focus_match.group(1))
        q["questionTypeStr"] = qtype_str
    # Extract question content from div.workWrap or div.ans-cc
    title_match = re.search(
        r'class=["\'][^"\']*workWrap[^"\']*["\'][^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
    if title_match:
        q["questionContent"] = re.sub(
            r'<[^>]+>', '', title_match.group(1)).strip()
    # Extract options from div.centerSpan
    options = {}
    for opt_m in re.finditer(r'<div[^>]*class=["\']centerSpan["\'][^>]*id=["\']([A-Z])["\'][^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL):
        letter = opt_m.group(1)
        text = re.sub(r'<[^>]+>', '', opt_m.group(2)).strip()
        if text:
            options[letter] = text
    q["options"] = [options.get(l, "")
                    for l in "ABCDEFGHIJKLMN" if options.get(l, "")]

    # Extract all metadata hidden fields
    for field_id in ["courseId", "testUserRelationId", "classId", "type", "isphone",
                     "imei", "subCount", "remainTime", "tempSave", "timeOver",
                     "encRemainTime", "encLastUpdateTime", "cpi", "enc", "source",
                     "userId", "enterPageTime", "answeredView", "paperGroupId",
                     "workId", "currentTime", "currentCpi", "currentUploadEnc",
                     "matchEnc", "cfid", "addTimes", "limitWorkSubmitTimes",
                     "encWork", "index"]:
        q[field_id] = _html_input_get(html, field_id)
    q["score"] = _html_input_name_get(html, f"score{qid}")
    return q


def _html_exam_question_turn_entity(html: str) -> Dict:
    """解析考试题目HTML提取元数据 - 对应 Go HtmlQuestionTurnEntity"""
    q = {}
    qid = _html_input_get(html, "questionId")
    q["questionId"] = qid
    q["questionTypeCode"] = _html_input_name_get(html, f"type{qid}")
    q["questionTypeStr"] = _html_input_name_get(html, f"typeName{qid}")
    # Extract question content from div.tit
    tit_match = re.search(
        r'class=["\']tit["\'][^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
    if tit_match:
        q["questionContent"] = re.sub(
            r'<[^>]+>', '', tit_match.group(1)).strip()
    # Extract options from .singleChoice
    options = {}
    for opt_m in re.finditer(r'<div[^>]*class=["\'][^"\']*singleChoice[^"\']*["\'][^>]*name=["\']([A-Z])["\'][^>]*>.*?class=["\'][^"\']*answerInfo[^"\']*cc[^"\']*["\'][^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL):
        letter = opt_m.group(1)
        text = opt_m.group(2).strip()
        options[letter] = letter + re.sub(r'<[^>]+>', '', text).strip()
    q["options"] = [options.get(l, "")
                    for l in "ABCDEFGHIJKLMN" if options.get(l, "")]

    for field_id in ["courseId", "testPaperId", "testUserRelationId", "classId",
                     "type", "isphone", "imei", "subCount", "remainTime",
                     "tempSave", "timeOver", "encRemainTime", "encLastUpdateTime",
                     "cpi", "enc", "source", "userId", "enterPageTime",
                     "answeredView", "exitdtime", "paperGroupId"]:
        q[field_id] = _html_input_get(html, field_id)
    q["score"] = _html_input_name_get(html, f"score{qid}")
    return q


def _work_action(setting: Setting, user: User, cache: XueXiTUserCache,
                 course: XueXiTCourse):
    """作业处理 - 对应 Go workAction + EnterWorkAction
    流程: PullWorkList → EnterWork(解析hidden fields) → PullWorkPaper → 逐题(PullWorkQuestion → AI → SubmitWorkAnswer)
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    list_body, _ = xxt_api.pull_work_list_api(
        cache, course.course_id, course.key, str(course.cpi), retry=3)
    if not list_body:
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "[", course.course_name, "] ", Red, "拉取作业列表失败，已自动跳过")
        return

    work_list = _parse_work_list_html(list_body)
    if not work_list:
        return

    for work in work_list:
        if not isinstance(work, dict):
            continue
        status = work.get("status", "")
        if status not in ("待做", "未交", "待重做"):
            continue

        task_ref_id = work.get("taskrefId", "")
        work_name = work.get("name", "")
        enc_task = work.get("enc_task", "")
        msg_id = work.get("msgId", "0")

        # 进入作业 - 解析enter page HTML
        enter_body, enter_resp = xxt_api.enter_work_api(
            cache, task_ref_id, enc_task, course.course_id, course.key,
            str(course.cpi), retry=3)
        if not enter_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Red, f"进入作业失败 (status={enter_resp.status_code if enter_resp else 'N/A'}, body={(enter_body or '')[:100]})")
            continue

        # 提取题目数量
        qt_match = re.search(r'共包含\s*(\d+)\s*道题目', enter_body)
        question_total = int(qt_match.group(1)) if qt_match else 0
        if not question_total and "待重做" in enter_body:
            qt_match2 = re.search(r'共\s*(\d+)\s*题', enter_body)
            question_total = int(qt_match2.group(1)) if qt_match2 else 0

        # 提取hidden fields
        exam_relation_id = _html_input_get(enter_body, "testPaperId")
        answer_id = _html_input_get(enter_body, "testUserRelationId")
        cpi_val = _html_input_get(enter_body, "cpi") or str(course.cpi)

        # extractParams from HTML
        cpi_match = re.search(r'cpi=(\d+)', enter_body)
        aid_match = re.search(r'workAnswerId=(\d+)', enter_body)
        enc_match = re.search(r'enc=([a-fA-F0-9]+)', enter_body)
        if cpi_match:
            cpi_val = cpi_match.group(1)
        if aid_match:
            answer_id = aid_match.group(1)
        enc_val = enc_match.group(1) if enc_match else ""

        # 检查是否已过时
        if "已过时效，不能操作!" in enter_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Red, "该作业已过时，已自动跳过")
            continue

        # 拉取 work paper (same URL as pull_work_question but first fetch)
        paper_body, _ = xxt_api.pull_work_question_api(
            cache, course.course_id, course.key,
            task_ref_id, 0, cpi_val,
            work_answer_id=answer_id, enc=enc_val,
            msg_id=msg_id, retry=3)
        if not paper_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Red, f"拉取作业试卷失败 (body为空)")
            continue

        if "已过时效，不能操作!" in paper_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Red, "该作业已过时，已自动跳过")
            continue

        # Parse paper to get metadata
        paper_entity = _html_work_question_turn_entity(paper_body)
        enc_val = paper_entity.get("enc", enc_val) or enc_val
        enc_remain_time = paper_entity.get("encRemainTime", "")
        enc_last_update_time = paper_entity.get("encLastUpdateTime", "")
        if not question_total:
            question_total = 1  # at least 1

        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】【", work_name, "】",
                  Yellow, f"正在写作业中(共{question_total}题)...")

        # 逐题回答
        for qi in range(question_total):
            # 拉取题目
            q_body, _ = xxt_api.pull_work_question_api(
                cache, course.course_id, course.key,
                task_ref_id, qi, cpi_val,
                work_answer_id=answer_id, enc=enc_val,
                msg_id=msg_id, retry=3)
            if not q_body:
                continue

            q_entity = _html_work_question_turn_entity(q_body)
            q_text = q_entity.get("questionContent", q_body[:500])
            q_type_code = q_entity.get("questionTypeCode", "0")

            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Yellow, f"写作业状态中，正在回答第{qi+1}题")

            # AI答题
            answer = ""
            if cc.auto_exam == 1:
                try:
                    from logic.core.ai_client import ai_problem_message
                    ai = setting.ai_setting
                    # 对齐Go: 传递题型和选项
                    _wt_code_map = {'0': 'single_choice', '1': 'multiple_choice',
                                    '2': 'fill', '3': 'judge', '4': 'short',
                                    '5': 'term_explanation', '6': 'essay',
                                    '11': 'matching', '8': 'short'}
                    _wt = _wt_code_map.get(q_type_code, '')
                    _w_opts = q_entity.get('options', [])
                    answer = ai_problem_message(
                        ai.ai_url, ai.model, ai.api_key, ai.ai_type,
                        q_text, options=_w_opts, q_type=_wt)
                except Exception:
                    answer = ""
            elif cc.auto_exam == 3:
                try:
                    ai_body, _ = xxt_api.xxt_ai_api(
                        cache, q_text, course.course_id, course.key, cpi_val)
                    ai_data = safe_json_parse(ai_body) if ai_body else None
                    answer = ai_data.get("answer", "") if ai_data else ""
                except Exception:
                    answer = ""
            if not answer:
                answer = "A" if q_type_code in ("0", "1") else (
                    "true" if q_type_code == "3" else "答案")

            # 判断答案格式 - 对齐Go的SimilarityArraySelect逻辑
            options = q_entity.get("options", [])
            if q_type_code in ("0", "1") and options:
                # 匹配答案到选项字母
                answer_letter = "A"
                for i, opt in enumerate(options):
                    if answer and opt and (answer in opt or opt in answer):
                        answer_letter = chr(65 + i)
                        break
                answer = answer_letter

            # 构建提交数据 - 对齐Go SubmitWorkAnswerApi (用list of tuples支持重复字段)
            # 关键: Go PullWorkQuestionAction 中 AnswerId/WordId 从 enter page 设置作为后备值
            is_last = (qi + 1 == question_total)
            is_submit = cc.exam_auto_submit in (1, 2) and is_last

            course_id_val = q_entity.get("courseId", "") or course.course_id
            work_rel_id = q_entity.get("workId", "") or task_ref_id
            class_id_val = q_entity.get("classId", "") or course.key
            qid = q_entity.get("questionId", "")
            # Go: qsEntity.AnswerId = exam.AnswerId (从enter page 设置的后备值)
            work_answer_id = q_entity.get(
                "testUserRelationId", "") or answer_id

            submit_data = [
                ("workExamUploadUrl", ""),
                ("workExamUploadCrcUrl", ""),
                ("workRelationAnswerId", work_answer_id),
                ("knowledgeid", "0"),
                ("enc", q_entity.get("enc", enc_val) or enc_val),
                ("source", q_entity.get("source", "0")),
                ("encWork", q_entity.get("encWork", "")),
                # Go源码中values.Add重复添加两次courseId/workRelationId/classId
                ("courseId", course_id_val),
                ("workRelationId", work_rel_id),
                ("classId", class_id_val),
                ("courseId", course_id_val),
                ("workRelationId", work_rel_id),
                ("classId", class_id_val),
                ("workTimesEnc", ""),
                ("questionId", qid),
                ("index", str(qi)),  # 使用循环变量，而非HTML中的固定值
            ]
            # 设置题型相关字段
            submit_data.append((f"type{qid}", q_type_code))
            submit_data.append((f"score{qid}", q_entity.get("score", "")))
            if q_type_code == "0":  # 单选
                submit_data.append((f"answer{qid}", answer))
            elif q_type_code == "1":  # 多选
                submit_data.append((f"answers{qid}", answer))
            elif q_type_code == "3":  # 判断 - 对齐Go: "true"/"false"
                # Go: arraySelect→A→"true", else→"false"
                judge_answer = answer
                if judge_answer not in ("true", "false"):
                    # 尝试转换为标准格式
                    judge_answer = judge_answer.replace(
                        "对", "正确").replace("√", "正确").replace("×", "错误")
                    if judge_answer == "正确" or "正确" in judge_answer or "对" in judge_answer:
                        judge_answer = "true"
                    elif judge_answer == "错误" or "错误" in judge_answer or "错" in judge_answer:
                        judge_answer = "false"
                    else:
                        judge_answer = "true"  # 默认
                submit_data.append((f"answer{qid}", judge_answer))
            elif q_type_code == "2":  # 填空
                submit_data.append((f"answer{qid}1", answer))
                submit_data.append((f"blankNum{qid}", "1,"))
            else:  # 简答/论述
                submit_data.append((f"answer{qid}", answer))

            submit_body, submit_resp = xxt_api.submit_work_answer_api(
                cache, submit_data, is_submit=is_submit, retry=3)
            submit_status = submit_resp.status_code if submit_resp else 0
            submit_str = submit_body or ""
            # 响应验证
            submit_ok = False
            try:
                sj = safe_json_parse(submit_str)
                if sj and sj.get("status") is True:
                    submit_ok = True
            except Exception:
                pass
            if submit_ok:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Green, f"第{qi+1}题回答成功，服务器返回:{submit_str[:200]}")
            else:
                # 诊断日志：显示编码后的请求数据和完整响应
                from urllib.parse import urlencode as _dbg_encode
                encoded_dbg = _dbg_encode(submit_data) if isinstance(
                    submit_data, list) else str(submit_data)
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Red, f"第{qi+1}题提交失败(status={submit_status})，服务器返回:{submit_str[:300]}")
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Yellow, f"[诊断] questionId={qid} type={q_type_code} is_submit={is_submit} "
                          f"data_len={len(encoded_dbg)} data_snippet={encoded_dbg[:400]}")
                # 额外的enc诊断
                q_enc = q_entity.get("enc", "")
                q_encwork = q_entity.get("encWork", "")
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Yellow, f"[enc诊断] q_entity.enc='{q_enc}' enc_val='{enc_val}' "
                          f"q_entity.encWork='{q_encwork}' used_enc='{q_entity.get('enc', enc_val) or enc_val}'")

        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】【", work_name, "】",
                  Green, "作业已完成")


# ============ 课程级考试执行 ============

def _exam_action(setting: Setting, user: User, cache: XueXiTUserCache,
                 course: XueXiTCourse):
    """考试处理 - 对应 Go examAction + EnterExamAction
    流程: PullExamList → EnterExam(解析hidden+examJumpUrl) → PullExamPaper → 逐题(PullExamQuestion → AI → SubmitExamAnswer)
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    list_body, _ = xxt_api.pull_exam_list_api(
        cache, course.course_id, course.key, str(course.cpi), retry=3)
    if not list_body:
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "[", course.course_name, "] ", Red, "拉取考试列表失败，已自动跳过")
        return

    exam_list = _parse_exam_list_html(list_body)
    if not exam_list:
        return

    for exam in exam_list:
        if not isinstance(exam, dict):
            continue
        status = exam.get("status", "")
        if status not in ("待做", "待重考", "待重做"):
            continue

        task_ref_id = exam.get("taskrefId", "")
        exam_name = exam.get("name", "")
        enc_task = exam.get("enc_task", "")
        msg_id = exam.get("msgId", "0")

        # 进入考试 - 对应 Go EnterExamAction
        enter_body, enter_resp = xxt_api.enter_exam_api(
            cache, task_ref_id, enc_task, course.course_id, course.key,
            str(course.cpi), retry=3)
        if not enter_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Red, "进入考试失败")
            continue

        # 处理"待重做" - 对应 Go PullExamEnterInformHtmlApi 中的逻辑
        # 如果enter_body含"待重做"，需要拉取重做版本的试卷(url+&redo=1)
        is_redo_exam = "待重做" in enter_body

        # 处理examJumpUrl - Go PullExamEnterInformHtmlApi中的逻辑
        jump_match = re.search(
            r'id=["\']examJumpUrl["\']\s+value=["\']([^"\']+)["\']', enter_body)
        if jump_match:
            jump_url = jump_match.group(1)
            # 拉取嵌套页面
            if not jump_url.startswith("http"):
                jump_url = "https://mooc1-api.chaoxing.com" + jump_url
            # 待重做时追加&redo=1 - 对应 Go PullReDoExamPaperHtmlApi
            if is_redo_exam:
                jump_url = jump_url + "&redo=1"
            try:
                _client = xxt_api._build_client(
                    cache, custom_ua=xxt_api.XXTEXAMUA)
                jump_body, _ = _client.get(jump_url, retry=3)
                _client.close()
                if jump_body:
                    enter_body = jump_body
            except Exception:
                pass

        # 检查重考
        is_re_exam = "bnt_retake\">重考</a>" in enter_body
        if is_re_exam:
            re_exam_match = re.search(
                r'class=["\']bnt_retake["\'][^>]*data=["\']([^"\']+)["\']', enter_body)
            if re_exam_match:
                re_exam_url = re_exam_match.group(1)
                if not re_exam_url.startswith("http"):
                    re_exam_url = "https://mooc1-api.chaoxing.com" + re_exam_url
                try:
                    _client = xxt_api._build_client(
                        cache, custom_ua=xxt_api.XXTEXAMUA)
                    re_body, _ = _client.get(re_exam_url, retry=3)
                    _client.close()
                    if re_body:
                        enter_body = re_body
                except Exception:
                    pass

        # 提取题目数量
        qt_match = re.search(r'共包含\s*(\d+)\s*道题目', enter_body)
        question_total = int(qt_match.group(1)) if qt_match else 0

        # 提取hidden fields
        exam_relation_id = _html_input_get(enter_body, "testPaperId")
        answer_id = _html_input_get(enter_body, "testUserRelationId")
        cpi_val = _html_input_get(enter_body, "cpi") or str(course.cpi)

        # 如果是重考，先调用重考接口
        if is_re_exam and exam_relation_id and answer_id:
            try:
                _client = xxt_api._build_client(
                    cache, custom_ua=xxt_api.XXTEXAMUA)
                _client.get(
                    f"https://mooc1-api.chaoxing.com/exam-ans/exam/phone/restartOp"
                    f"?examId={exam_relation_id}&examAnswerId={answer_id}"
                    f"&courseId={course.course_id}&classId={course.key}&source=0&code=",
                    retry=3)
                _client.close()
            except Exception:
                pass

        # 拉取考试试卷 - 对应 Go PullExamPaperHtmlApi / PullReDoExamPaperHtmlApi
        api_imei = xxt_api._IMEI
        paper_body, paper_resp = xxt_api.pull_exam_paper_api(
            cache, course.course_id, course.key,
            exam_relation_id, cpi_val,
            exam_answer_id=answer_id,
            imei=api_imei, redo=is_redo_exam, retry=3)
        if not paper_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Red, f"拉取考试试卷失败 (status={paper_resp.status_code if paper_resp else 'N/A'})")
            continue

        # 检查访问异常 - 对应 Go EnterExamAction 中的XXTEXAMUA切换逻辑
        # Go: strings.Contains(pullPaperHtml, "访问异常") → XXTEXAMUA = GetUA("iphone") → 递归重试
        if "访问异常" in paper_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, "考试访问异常，切换iPhone UA重试...")
            xxt_api.XXTEXAMUA = xxt_api.get_ua("iphone")
            # 重试拉取试卷
            paper_body, paper_resp = xxt_api.pull_exam_paper_api(
                cache, course.course_id, course.key,
                exam_relation_id, cpi_val,
                exam_answer_id=answer_id,
                imei=api_imei, redo=is_redo_exam, retry=3)
            if not paper_body or "访问异常" in paper_body:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, "考试访问异常，iPhone UA重试仍失败，跳过")
                xxt_api.XXTEXAMUA = xxt_api.get_ua("mobile")  # 恢复
                continue

        # Parse paper to get metadata
        paper_entity = _html_exam_question_turn_entity(paper_body)
        enc_val = paper_entity.get("enc", "")
        enc_remain_time = paper_entity.get("encRemainTime", "")
        enc_last_update_time = paper_entity.get("encLastUpdateTime", "")
        remain_time = paper_entity.get("remainTime", "")
        test_paper_id = paper_entity.get("testPaperId", exam_relation_id)
        test_user_relation_id = paper_entity.get(
            "testUserRelationId", answer_id)
        if not question_total:
            question_total = 1

        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】【", exam_name, "】",
                  Yellow, f"正在考试中(共{question_total}题)...")

        # 逐题回答
        for qi in range(question_total):
            # 拉取题目 - 使用 reVersionTestStartNew URL
            q_body, _ = xxt_api.pull_exam_question_api(
                cache, course.course_id, course.key,
                test_paper_id, test_user_relation_id,
                cpi_val, enc_remain_time,
                enc_val, str(int(time.time() * 1000)),
                index=qi, retry=3)
            if not q_body:
                continue

            q_entity = _html_exam_question_turn_entity(q_body)
            q_text = q_entity.get("questionContent", q_body[:500])
            q_type_code = q_entity.get("questionTypeCode", "0")
            q_type_str = q_entity.get("questionTypeStr", "")
            qid = q_entity.get("questionId", "")

            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, f"考试状态中，正在回答第{qi+1}题，总共{question_total}题")

            # AI答题
            answer = ""
            if cc.auto_exam == 1:
                try:
                    from logic.core.ai_client import ai_problem_message
                    ai = setting.ai_setting
                    # 对齐Go: 传递题型和选项
                    _wt_code_map = {'0': 'single_choice', '1': 'multiple_choice',
                                    '2': 'fill', '3': 'judge', '4': 'short',
                                    '5': 'term_explanation', '6': 'essay',
                                    '11': 'matching', '8': 'short'}
                    _wt = _wt_code_map.get(q_type_code, '')
                    _w_opts = q_entity.get('options', [])
                    answer = ai_problem_message(
                        ai.ai_url, ai.model, ai.api_key, ai.ai_type,
                        q_text, options=_w_opts, q_type=_wt)
                except Exception:
                    answer = ""
            elif cc.auto_exam == 3:
                try:
                    ai_body, _ = xxt_api.xxt_ai_api(
                        cache, q_text, course.course_id, course.key, cpi_val)
                    ai_data = safe_json_parse(ai_body) if ai_body else None
                    answer = ai_data.get("answer", "") if ai_data else ""
                except Exception:
                    answer = ""
            if not answer:
                answer = "A" if q_type_code in ("0", "1") else (
                    "true" if q_type_code == "3" else "答案")

            # 匹配答案到选项
            options = q_entity.get("options", [])
            if q_type_code in ("0", "1") and options:
                answer_letter = "A"
                for i, opt in enumerate(options):
                    if answer and opt and (answer in opt or opt in answer):
                        answer_letter = chr(65 + i)
                        break
                answer = answer_letter
            elif q_type_code == "3":  # 判断题 - 对齐Go: SimilarityArraySelect→A→"true", else→"false"
                judge_answer = answer
                if judge_answer not in ("true", "false"):
                    judge_answer = judge_answer.replace(
                        "对", "正确").replace("√", "正确").replace("×", "错误")
                    if judge_answer == "正确" or "正确" in judge_answer or "对" in judge_answer:
                        judge_answer = "true"
                    elif judge_answer == "错误" or "错误" in judge_answer or "错" in judge_answer:
                        judge_answer = "false"
                    else:
                        judge_answer = "true"  # 默认
                answer = judge_answer

            # 构建提交数据 - 对齐Go SubmitExamAnswerApi
            is_last = (qi + 1 == question_total)
            is_submit = cc.exam_auto_submit in (1, 2) and is_last

            submit_data = {
                "courseId": q_entity.get("courseId", "") or course.course_id,
                "testPaperId": q_entity.get("testPaperId", "") or test_paper_id,
                "testUserRelationId": q_entity.get("testUserRelationId", "") or test_user_relation_id,
                "classId": q_entity.get("classId", "") or course.key,
                "cpi": q_entity.get("cpi", "") or cpi_val,
                "userId": q_entity.get("userId", "") or cache.cookie_dict.get("_uid", cache.uid),
                "enc": q_entity.get("enc", "") or enc_val,
                "encRemainTime": q_entity.get("encRemainTime", "") or enc_remain_time,
                "encLastUpdateTime": q_entity.get("encLastUpdateTime", "") or enc_last_update_time,
                "remainTime": q_entity.get("remainTime", "") or remain_time,
                "enterPageTime": q_entity.get("enterPageTime", ""),
                "questionId": qid,
                "questionTypeCode": q_type_code,
                "questionTypeStr": q_type_str,
                "score": q_entity.get("score", ""),
                "tid": task_ref_id,
                "answerId": test_user_relation_id,
                "remainTimeParam": enc_remain_time,
                "imei": q_entity.get("imei", "") or api_imei,
                "answer": answer,
            }

            submit_body, submit_resp = xxt_api.submit_exam_answer_api(
                cache, submit_data, is_submit=is_submit, retry=3)
            # 提交试卷后恢复XXTEXAMUA - 对应 Go SubmitExamAnswerAction
            if is_submit:
                xxt_api.XXTEXAMUA = xxt_api.get_ua("mobile")
            submit_status = submit_resp.status_code if submit_resp else 0
            submit_str = submit_body or ""
            # 处理限制提交时间的考试
            time_match = re.search(
                r'考试(\d+)分钟内不允许提交考试', submit_str)
            if time_match:
                min_time = int(time_match.group(1))
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Green, f"检测到考试限制开考{min_time}分钟内不允许提交，已自动延时...")
                time.sleep(min_time * 60)
                submit_body, submit_resp = xxt_api.submit_exam_answer_api(
                    cache, submit_data, is_submit=is_submit, retry=3)
                submit_status = submit_resp.status_code if submit_resp else 0
                submit_str = submit_body or ""

            if "考试时间已用完" in submit_str:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, "考试时间已用完，已自动跳过")
                break

            # 响应验证
            exam_submit_ok = False
            try:
                ej = safe_json_parse(submit_str)
                if ej and ej.get("status") is True:
                    exam_submit_ok = True
            except Exception:
                pass
            if exam_submit_ok:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Green, f"第{qi+1}题回答成功，服务器返回:{submit_str[:200]}")
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, f"第{qi+1}题提交失败(status={submit_status})，服务器返回:{submit_str[:300]}")
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Yellow, f"[诊断] questionId={qid} type={q_type_code} is_submit={is_submit}")

        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】【", exam_name, "】",
                  Green, "考试已完成")
