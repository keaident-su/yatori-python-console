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
            else:
                c = copy.deepcopy(cache)
                xxt_api.relogin(c)
                _model3_caches[cache.account].append(c)
                time.sleep(1)

    # Concurrent course execution for model 2/3 (Go uses goroutines)
    if user.courses_custom.video_model == 1:
        for course in course_list:
            _course_study(setting, user, cache, course)
    else:
        threads_course = []
        for course in course_list:
            t = threading.Thread(target=_course_study,
                                 args=(setting, user, cache, course), daemon=True)
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
    for item in knowledge_list:
        if isinstance(item, dict):
            nodes.append(item.get("id", 0))

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              "[", course.course_name, "] ",
              f"获取课程章节成功 (共 ", Yellow, str(len(nodes)), Default, " 个)")

    try:
        course_id_int = int(course.course_id)
        user_id_int = int(cache.user_id) if cache.user_id else 0
    except (ValueError, TypeError):
        return

    point_body, _ = xxt_api.fetch_chapter_point_status(
        cache, nodes, key_int, user_id_int, course.cpi, course_id_int, retry=5)
    point_data = safe_json_parse(point_body)

    finished_map = {}
    if point_data:
        for k, v in point_data.items():
            if isinstance(v, dict):
                # chaoxing API uses totalcount/finishcount (not pointTotal/pointFinished)
                total = v.get("totalcount", v.get("pointTotal", 0))
                finished = v.get("finishcount", v.get("pointFinished", 0))
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
                    xxt_api.relogin(res_cache)
                    _node_run(setting, user, res_cache,
                              course, nodes, idx, nid)
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
                                  m3_list[si], course, nodes, idx, nid)
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
            _node_run(setting, user, cache, course, nodes, index, node_id)


# ============ 节点运行 (核心重写 - 完全对齐Go) ============

def _node_run(setting: Setting, user: User, cache: XueXiTUserCache,
              course: XueXiTCourse, nodes: List[int],
              index: int, node_id: int):
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
        return
    first_data = cards_data[0]
    if not isinstance(first_data, dict):
        return
    card_data = first_data.get("card", {})
    if not isinstance(card_data, dict):
        return
    cards = card_data.get("data", [])
    if not cards or not isinstance(cards, list):
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
    knowledge_item = KnowledgeItem(id=node_id, name=f"章节{node_id}")

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
                _execute_video(setting, user, cache, course, vdto)
            elif vdto.type == "insertaudio":
                _execute_audio(setting, user, cache, course, vdto)

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
            return None, "", Exception("验证码绕过失败，请手动处理")

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
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ", Yellow,
                  "验证码自动识别失败，请手动处理")
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
            hd.job_id = job_id
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
                   course: XueXiTCourse, video: PointVideoDto):
    """执行视频学习 - 完全对齐 Go ExecuteVideo
    包含: 过超提交、403人脸绕过、500跳过、404重试、OutTimeMsg、isdrag=3
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    # VideoDtoFetchAction
    if not _video_dto_fetch_action(cache, video):
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  Red, f"视频任务点解析失败 objectId={video.object_id}，已自动跳过")
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

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{platform}]",
                "[", Green, acct, Default, "] ",
                Yellow, "正在学习视频：", Default,
                f"{video.title or video.object_id} duration={video.duration}s")

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
                      BoldRed, "视频提交触发500风控，ReLogin后重试仍失败，跳过该视频")
            break

        # 403: Go聚合层ReLogin后重试同mode，仍403才传到调用层
        if status_code == 403:
            if mode == 1:
                # 手机端403 → 切换为Web端 (Go ExecuteVideo逻辑)
                mode = 0
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          Yellow, "手机端403，切换为Web端...")
                continue
            # Web端仍403 → 人脸识别绕过 (Go ExecuteVideo逻辑)
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ", Yellow,
                      "触发403人脸识别，正在尝试自动绕过...")
            face_err = xxt_api.pass_face_pc_action(
                cache, video.course_id, video.class_id, video.cpi,
                str(video.knowledge_id), video.enc,
                video.job_id, video.object_id, video.mid,
                video.random_capture_time)
            if face_err:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          BoldRed, f"403人脸绕过失败: {face_err}，跳过该视频")
                return
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ", Green,
                      "403人脸绕过成功，继续播放...")
            time.sleep(5)  # Go: 不要删！一定要等待一小段时间
            continue

        # 202/400: Go聚合层ReLogin后重试，仍失败则跳过
        if status_code in (202, 400):
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      BoldRed, f"视频提交异常 status={status_code}，已跳过")
            break

        if status_code == 404:
            time.sleep(10)
            continue

        if status_code and status_code != 200:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      BoldRed, f"视频提交异常 status={status_code}")
            break

        resp_data = safe_json_parse(body) if body else None
        if not resp_data or "isPassed" not in resp_data:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      BoldRed, f"视频提交返回异常: {body[:200] if body else 'empty'}")
            break

        is_passed = resp_data.get("isPassed", False)

        # OutTimeMsg 阈值超限
        out_time_msg = resp_data.get("OutTimeMsg", "")
        if out_time_msg == "观看时长超过阈值":
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      Green, f"观看时长超过阈值，已直接提交 passed={is_passed}")
            break

        if is_passed and playing_time >= video.duration:
            if over_time == 0:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", video.title, "】 >>> ",
                          "提交状态：", Green, str(is_passed), Default,
                          f" 观看时间：{video.duration}/{video.duration}",
                          f" 观看进度：100.00%")
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", video.title, "】 >>> ",
                          "提交状态：", Green, str(is_passed), Default,
                          f" 过超时间：{over_time}/{limit_time}",
                          Green, " 过超提交成功")
            break

        # 日志
        if over_time == 0:
            pct = (playing_time / video.duration *
                   100) if video.duration > 0 else 0
            model_print(setting.basic_setting.log_model == 0,
                        INFO, f"[{platform}]",
                        "[", Green, acct, Default, "] ",
                        "【", video.title, "】 >>> ",
                        "提交状态：", Green, str(is_passed), Default,
                        f" 观看时间：{playing_time}/{video.duration}",
                        f" 观看进度：{pct:.2f}%")
        else:
            pct = (playing_time / video.duration *
                   100) if video.duration > 0 else 0
            model_print(setting.basic_setting.log_model == 0,
                        INFO, f"[{platform}]",
                        "[", Green, acct, Default, "] ",
                        "【", video.title, "】 >>> ",
                        "提交状态：", Green, str(is_passed), Default,
                        f" 观看时间：{playing_time}/{video.duration}",
                        f" 过超时间：{over_time}/{limit_time}",
                        f" 观看进度：{pct:.2f}%")

        # 过超提交检测
        if over_time >= limit_time:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
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
                   course: XueXiTCourse, audio: PointVideoDto):
    """执行音频学习 - 完全对齐 Go ExecuteAudio"""
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    if not _video_dto_fetch_action(cache, audio):
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  Red, f"音频任务点解析失败 objectId={audio.object_id}")
        return

    playing_time = audio.play_time
    if not audio.is_passed and audio.play_time == audio.duration:
        playing_time = 0

    over_time = 0
    select_sec = 58
    extend_sec = 5
    limit_time = max(500, audio.duration // 2)
    mode = 1

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{platform}]",
                "[", Green, acct, Default, "] ",
                Yellow, "正在学习音频：", Default,
                f"{audio.title or audio.object_id} duration={audio.duration}s")

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
                      BoldRed, "音频提交触发500风控，ReLogin后仍失败，已跳过")
            break

        if status_code == 403:
            if mode == 1:
                mode = 0
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          Yellow, "手机端403，切换为Web端...")
                continue
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      BoldRed, "触发403人脸识别(暂未实现)，跳过该音频")
            return

        if status_code == 404:
            time.sleep(10)
            continue

        if status_code and status_code != 200:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
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
                      Green, "音频提交时长超过阈值，已直接提交")
            break

        if is_passed and playing_time >= audio.duration:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      Green, f"音频完成 passed={is_passed}")
            break

        if over_time >= limit_time:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
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
    if not hdto.object_id:
        return
    body, _ = xxt_api.hyperlink_submit_api(
        cache, hdto.object_id, str(hdto.knowledge_id), cache.uid, retry=5)
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
    """执行讨论任务 - 对应 Go ExecuteBBS
    流程: PullPhoneBbsInfo → AI答题/外挂题库/内置AI → 发表讨论回复
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    # 拉取讨论主题
    topic_body, topic_err = xxt_api.pull_phone_bbs_info_api(
        cache, bdto.job_id, course.course_id, course.key, retry=5)
    if not topic_body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", bdto.title, "】",
                  BoldRed, "无法正常拉取讨论任务点主题，已自动跳过")
        return

    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              "【", knowledge.name, "】",
              "【", bdto.title, "】",
              Yellow, "正在执行讨论任务点...")

    # 根据答题模式获取回答内容
    content = ""
    if cc.auto_exam == 1:
        # AI答题
        try:
            from logic.core.ai_client import ai_problem_message
            ai = setting.ai_setting
            answer = ai_problem_message(
                ai.ai_url, ai.model, ai.api_key, ai.ai_type,
                bdto.title or bdto.detail or "发表讨论回复")
            content = answer if answer else "同意"
        except Exception as e:
            content = "同意"
    elif cc.auto_exam == 3:
        # 学习通内置AI
        try:
            body, _ = xxt_api.xxt_ai_api(
                cache, bdto.title or "发表讨论回复",
                course.course_id, course.key, str(course.cpi))
            data = safe_json_parse(body) if body else None
            content = data.get("answer", "同意") if data else "同意"
        except Exception:
            content = "同意"
    else:
        content = "同意"

    # 发表讨论回复
    reply_body, reply_err = xxt_api.bbs_reply_api(
        cache, bdto.job_id, course.course_id, course.key, content, retry=5)
    if reply_err:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", bdto.title, "】",
                  BoldRed, f"讨论任务点提交异常: {reply_err}")
    else:
        reply_data = safe_json_parse(reply_body) if reply_body else None
        msg = reply_data.get(
            "msg", reply_body[:100]) if reply_data else "unknown"
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", knowledge.name, "】",
                  "【", bdto.title, "】 >>> ",
                  "讨论任务点状态：", Green, str(msg))


# ============ 章测自动答题 ============

def _chapter_test_action(setting: Setting, user: User, cache: XueXiTUserCache,
                         course: XueXiTCourse, knowledge: KnowledgeItem,
                         wdto: PointWorkDto):
    """章测自动答题 - 对应 Go chapterTestAction
    流程: WorkFetchQuestion → 解析题目 → AI答题 → WorkNewSubmitAnswer
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    # 获取题目页面
    body, _ = xxt_api.work_fetch_question_api(cache, wdto, retry=5)
    if not body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  BoldRed, "章测题目页面获取失败")
        return

    if "已截止" in body or "不能作答" in body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Yellow, "该试卷已到截止时间，已自动跳过")
        return

    # 解析题目并AI答题
    questions = _parse_work_questions(body)
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

    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              f"<{mode_str}>",
              "【", course.course_name, "】",
              "【", knowledge.name, "】",
              Yellow, f"正在{mode_str}写章节作业(共{len(questions)}题)...")

    # 对每道题AI答题
    answer_data = {}
    for q in questions:
        q_type = q.get("type", "")
        q_text = q.get("text", "")
        q_id = q.get("id", "")
        answer = ""

        if cc.auto_exam == 1:
            # AI答题
            try:
                from logic.core.ai_client import ai_problem_message
                ai = setting.ai_setting
                answer = ai_problem_message(
                    ai.ai_url, ai.model, ai.api_key, ai.ai_type,
                    q_text)
            except Exception:
                answer = ""
        elif cc.auto_exam == 3:
            # 内置AI
            try:
                ai_body, _ = xxt_api.xxt_ai_api(
                    cache, q_text, course.course_id, course.key, str(course.cpi))
                ai_data = safe_json_parse(ai_body) if ai_body else None
                answer = ai_data.get("answer", "") if ai_data else ""
            except Exception:
                answer = ""
        else:
            answer = "A"  # 默认答案

        # AnswerFixedPattern: 防止留空
        if not answer and q_type in ("choice", "judge"):
            answer = "A" if q_type == "choice" else "True"

        if q_id:
            answer_data[q_id] = answer
        time.sleep(random.randint(1, 2))

    # 提交答案
    answer_data.update({
        "courseId": wdto.course_id,
        "classId": wdto.class_id,
        "knowledgeId": str(wdto.knowledge_id),
        "workId": wdto.work_id,
        "jobId": wdto.job_id,
        "cpi": wdto.cpi,
        "enc": wdto.enc,
        "ktoken": wdto.k_token,
    })

    is_submit = cc.exam_auto_submit in (1, 2)
    result_body, _ = xxt_api.work_new_submit_answer_api(
        cache, wdto.course_id, wdto.class_id,
        str(wdto.knowledge_id), wdto.work_id,
        answer_data, retry=3)

    log_print(INFO, f"[{platform}]",
              "[", Green, acct, Default, "] ",
              f"<{mode_str}>",
              "【", course.course_name, "】",
              "【", knowledge.name, "】",
              Green, f"章节作业{mode_str}答题完毕，服务器返回：{result_body[:200] if result_body else 'empty'}")


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


def _parse_exam_list_html(html_body: str) -> List[Dict]:
    """Parse exam list from chaoxing getExamList HTML response."""
    exam_list = []
    if not html_body:
        return exam_list

    exam_pattern = re.compile(
        r'<a[^>]*href="[^"]*[?&]examId=(\d+)[^"]*"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL)
    status_pattern = re.compile(r'(待做|待重考|已完成)', re.IGNORECASE)
    enc_pattern = re.compile(r'[?&]enc=([^&"\']+)', re.IGNORECASE)

    for m in exam_pattern.finditer(html_body):
        exam_id = m.group(1)
        inner_html = m.group(2)
        name = re.sub(r'<[^>]+>', '', inner_html).strip()
        context_start = max(0, m.start() - 500)
        context_end = min(len(html_body), m.end() + 500)
        context = html_body[context_start:context_end]
        status_match = status_pattern.search(context)
        status = status_match.group(1) if status_match else ""
        enc_match = enc_pattern.search(context)
        enc = enc_match.group(1) if enc_match else ""
        exam_list.append({
            "examId": exam_id,
            "name": name[:100] if name else f"考试{exam_id}",
            "enc": enc,
            "status": status,
            "questionTotal": 0,
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
    """Parse work list from chaoxing getWorkList HTML response.
    Extracts work items with workId, name, enc, status, questionTotal.
    """
    work_list = []
    if not html_body:
        return work_list

    # Try to find work item blocks - typical pattern:
    # <div class="...WorkList..."> ... <a href="...workId=xxx..."> ... </a> ... </div>
    # Look for links containing workId parameter
    work_pattern = re.compile(
        r'<a[^>]*href="[^"]*[?&]workId=(\d+)[^"]*"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL)
    # Look for status text
    status_pattern = re.compile(r'(待做|未交|待重做|已交|已批)', re.IGNORECASE)
    # Look for enc parameter
    enc_pattern = re.compile(r'[?&]enc=([^&"\']+)', re.IGNORECASE)

    for m in work_pattern.finditer(html_body):
        work_id = m.group(1)
        inner_html = m.group(2)
        # Extract name from inner text
        name = re.sub(r'<[^>]+>', '', inner_html).strip()
        # Try to find status near this link
        context_start = max(0, m.start() - 500)
        context_end = min(len(html_body), m.end() + 500)
        context = html_body[context_start:context_end]
        status_match = status_pattern.search(context)
        status = status_match.group(1) if status_match else ""
        # Extract enc from nearby href
        enc_match = enc_pattern.search(context)
        enc = enc_match.group(1) if enc_match else ""

        work_list.append({
            "workId": work_id,
            "name": name[:100] if name else f"作业{work_id}",
            "enc": enc,
            "status": status,
            "questionTotal": 0,  # Will be determined during processing
        })

    # Also try JSON response format (some endpoints return JSON)
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


def _work_action(setting: Setting, user: User, cache: XueXiTUserCache,
                 course: XueXiTCourse):
    """作业处理 - 对应 Go workAction
    流程: PullWorkList → EnterWork → PullWorkQuestion → AI答题 → SubmitWorkAnswer
    Note: The chaoxing getWorkList endpoint returns HTML, not JSON.
    We parse the HTML to extract work items.
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    # 拉取作业列表 (returns HTML page)
    list_body, list_resp = xxt_api.pull_work_list_api(
        cache, course.course_id, course.key, str(course.cpi), retry=3)
    if not list_body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "[", course.course_name, "] ", Red, "拉取作业列表失败，已自动跳过")
        return

    # Parse work list from HTML response
    work_list = _parse_work_list_html(list_body)
    if not work_list:
        # No pending work items - silently return
        return
    for work in work_list:
        if not isinstance(work, dict):
            continue
        status = work.get("status", "")
        if status not in ("待做", "未交", "待重做"):
            continue

        work_id = work.get("workId", "")
        work_name = work.get("name", "")
        work_enc = work.get("enc", "")
        total_q = work.get("questionTotal", 0)

        # 进入作业
        enter_body, enter_err = xxt_api.enter_work_api(
            cache, work_id, work_enc, course.course_id, course.key,
            str(course.cpi), retry=3)
        if enter_err:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", work_name, "】",
                      Red, f"进入作业失败: {enter_err}")
            continue

        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", work_name, "】",
                  Yellow, "正在写作业中...")

        # 逐题回答
        for qi in range(total_q):
            # 拉取题目
            q_body, _ = xxt_api.pull_work_question_api(
                cache, course.course_id, course.key,
                work_id, qi, str(course.cpi),
                retry=3)
            if not q_body:
                continue

            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", work_name, "】",
                      Yellow, f"写作业状态中，正在回答第{qi+1}题")

            # AI答题
            answer = ""
            if cc.auto_exam == 1:
                try:
                    from logic.core.ai_client import ai_problem_message
                    ai = setting.ai_setting
                    answer = ai_problem_message(
                        ai.ai_url, ai.model, ai.api_key, ai.ai_type,
                        q_body[:500])
                except Exception:
                    answer = ""
            elif cc.auto_exam == 3:
                try:
                    ai_body, _ = xxt_api.xxt_ai_api(
                        cache, q_body[:500], course.course_id,
                        course.key, str(course.cpi))
                    ai_data = safe_json_parse(ai_body) if ai_body else None
                    answer = ai_data.get("answer", "") if ai_data else ""
                except Exception:
                    answer = ""

            # 提交答案
            is_last = (qi + 1 == total_q)
            is_submit = cc.exam_auto_submit in (1, 2) and is_last
            submit_data = {"answer": answer, "questionIndex": str(qi)}
            submit_body, submit_err = xxt_api.submit_work_answer_api(
                cache, submit_data, is_submit=is_submit, retry=3)
            if submit_err:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", work_name, "】",
                          Red, f"作业提交失败: {submit_err}")
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", work_name, "】",
                          Green, f"第{qi+1}题回答成功，服务器返回:{(submit_body or '')[:200]}")

        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", work_name, "】",
                  Green, "作业已完成")


# ============ 课程级考试执行 ============

def _exam_action(setting: Setting, user: User, cache: XueXiTUserCache,
                 course: XueXiTCourse):
    """考试处理 - 对应 Go examAction
    流程: PullExamList → EnterExam → PullExamQuestion → AI答题 → SubmitExamAnswer
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom

    # 拉取考试列表 (returns HTML page)
    list_body, _ = xxt_api.pull_exam_list_api(
        cache, course.course_id, course.key, str(course.cpi), retry=3)
    if not list_body:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "[", course.course_name, "] ", Red, "拉取考试列表失败，已自动跳过")
        return

    # Parse exam list from HTML or JSON
    exam_list = _parse_exam_list_html(list_body)
    if not exam_list:
        return
    for exam in exam_list:
        if not isinstance(exam, dict):
            continue
        status = exam.get("status", "")
        if status not in ("待做", "待重考"):
            continue

        exam_id = exam.get("examId", "")
        exam_name = exam.get("name", "")
        exam_enc = exam.get("enc", "")
        total_q = exam.get("questionTotal", 0)

        # 进入考试
        enter_body, enter_err = xxt_api.enter_exam_api(
            cache, exam_id, exam_enc, course.course_id, course.key,
            str(course.cpi), retry=3)
        if enter_err:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", exam_name, "】",
                      Red, f"进入考试失败: {enter_err}")
            continue

        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", exam_name, "】",
                  Yellow, "正在考试中...")

        # 逐题回答
        for qi in range(total_q):
            # 拉取题目
            q_body, _ = xxt_api.pull_exam_question_api(
                cache, course.course_id, course.key,
                exam_id, qi, str(course.cpi),
                retry=3)
            if not q_body:
                continue

            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", exam_name, "】",
                      Yellow, f"考试状态中，正在回答第{qi+1}题，总共{total_q}题")

            # AI答题
            answer = ""
            if cc.auto_exam == 1:
                try:
                    from logic.core.ai_client import ai_problem_message
                    ai = setting.ai_setting
                    answer = ai_problem_message(
                        ai.ai_url, ai.model, ai.api_key, ai.ai_type,
                        q_body[:500])
                except Exception:
                    answer = ""
            elif cc.auto_exam == 3:
                try:
                    ai_body, _ = xxt_api.xxt_ai_api(
                        cache, q_body[:500], course.course_id,
                        course.key, str(course.cpi))
                    ai_data = safe_json_parse(ai_body) if ai_body else None
                    answer = ai_data.get("answer", "") if ai_data else ""
                except Exception:
                    answer = ""

            # 提交答案
            is_last = (qi + 1 == total_q)
            is_submit = cc.exam_auto_submit in (1, 2) and is_last
            submit_data = {"answer": answer, "questionIndex": str(qi)}
            submit_body, submit_err = xxt_api.submit_exam_answer_api(
                cache, submit_data, is_submit=is_submit, retry=3)
            if submit_err:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", exam_name, "】",
                          Red, f"试卷提交失败: {submit_err}")
            else:
                # 处理限制提交时间的考试
                import re as _re
                time_match = _re.search(
                    r'考试(\d+)分钟内不允许提交考试', submit_body or "")
                if time_match:
                    min_time = int(time_match.group(1))
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】",
                              "【", exam_name, "】",
                              Green, f"检测到考试限制开考{min_time}分钟内不允许提交，已自动延时...")
                    time.sleep(min_time * 60)
                    submit_body, submit_err = xxt_api.submit_exam_answer_api(
                        cache, submit_data, is_submit=is_submit, retry=3)

                # 检查考试时间用完
                if "考试时间已用完" in (submit_body or ""):
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】",
                              "【", exam_name, "】",
                              Red, "考试时间已用完，已自动跳过")
                    break

                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", exam_name, "】",
                          Green, f"第{qi+1}题回答成功，服务器返回:{(submit_body or '')[:200]}")

        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", exam_name, "】",
                  Green, "考试已完成")
