# -*- coding: utf-8 -*-
"""
智慧树平台逻辑 - 移植自外部项目 zhihuishu_sdk(fuckzhs) 并适配本工程架构

流程: 密码登录 → 拉取课程(Polymas AI课 + Hike共享课, 自动去重) → 课程过滤
      → 按课程类型刷课(视频逐段上报进度, 非视频任务点标记完成) → 完成通知
支持: includeCourses/excludeCourses 课程过滤; zhsSpeed 刷课速度倍率(默认1.5)
说明: 智慧树课程考试(实验性 AI 答题)暂未接入, 如需后续补充
"""
import threading
import time
from random import random, uniform
from typing import Any, List

from config.config import (
    User, Setting, JSONDataForConfig, cmp_course, display_account,
)
from global_state.global_var import ACCOUNT_TYPE_STR
from logic.platform_common import (
    generic_filter_account, generic_user_block, get_simple_logger,
    send_user_event_notice, run_stats_bump,
)
from logic.zhihuishu.api import (
    HikeAPIClient, ManagedSession, PolymasAPIClient, login_password,
)
from logic.zhihuishu.models import (
    CourseType, StudyProgress, ZhsAuthError, ZhsCaptchaError, ZhsCourse,
    ZhsError, ZhsUserCache,
)
from utils.log import log_print, INFO, Red, Yellow

PLATFORM_TYPE = "ZHIHUISHU"
_DISPLAY = ACCOUNT_TYPE_STR[PLATFORM_TYPE]

# 视频完成阈值: 播放到总时长的 91% 即视为完成(平台允许少量未看完)
_END_THRESHOLD = 0.91
# 每次进度上报的视频时长步长(秒, 与 Polymas/Hike 前端行为一致)
_REPORT_STEP = 30


# ============ 平台入口(与其它平台统一的三个函数) ============

def filter_account(config_data: JSONDataForConfig) -> List[User]:
    """从配置中过滤出智慧树账号"""
    return generic_filter_account(config_data, PLATFORM_TYPE)


def user_login_operation(users: List[User]) -> List[ZhsUserCache]:
    """批量登录(单账号失败仅跳过, 不影响其他账号与其他平台)"""
    user_caches: List[ZhsUserCache] = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        log = get_simple_logger(f"[{_DISPLAY}][{display_account(user.account)}]")
        if not (user.account or "").strip():
            log.error("账号为空, 已跳过")
            continue
        if not (user.password or "").strip():
            log.error("密码为空(智慧树暂仅支持密码登录), 已跳过")
            continue
        try:
            session = ManagedSession()
            login_password(session, user.account.strip(), user.password)
        except (ZhsAuthError, ZhsCaptchaError) as e:
            log.error(f"登录失败: {e}")
            continue
        except Exception as e:
            log.error(f"登录异常: {e}")
            continue
        cache = ZhsUserCache(
            account=user.account, password=user.password,
            session=session, cas_user_id=session.get_cas_user_id(),
        )
        log.success("登录成功")
        user_caches.append(cache)
    return user_caches


def run_brush_operation(setting: Setting, users: List[User], user_caches: List[Any]):
    """执行刷课(每账号一个线程并发; 登录失败的账号已被过滤)"""
    threads = []
    for cache in user_caches:
        matched = None
        for u in users:
            if u.account == cache.account:
                matched = u
                break
        if matched is None:
            continue
        t = threading.Thread(target=_user_block,
                             args=(setting, matched, cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


# ============ 单账号刷课流程 ============

def _user_block(setting: Setting, user: User, cache: ZhsUserCache):
    """单账号流程: 拉课程 → 过滤 → 逐课程刷 → 完成通知"""
    log = get_simple_logger(f"[{_DISPLAY}][{display_account(user.account)}]")
    speed = float(getattr(user.courses_custom, "zhs_speed", 1.5) or 1.5)

    courses = _fetch_all_courses(cache, log)
    if not courses:
        log.warning("没有找到可学习的课程")
    cc = user.courses_custom
    for course in courses:
        if cc.exclude_courses and cmp_course(course.name, cc.exclude_courses):
            continue
        if cc.include_courses and not cmp_course(course.name, cc.include_courses):
            continue
        try:
            progress = _brush_course(cache, user, course, speed, log)
        except Exception as e:
            log.error(f"课程【{course.name}】刷课异常: {e}")
            continue
        # 课程完成 → 事件通知 + 本次运行统计
        run_stats_bump(_DISPLAY, user.account, "course")
        send_user_event_notice(
            setting, user, _DISPLAY,
            f"课程【{course.name}】已完成"
            f"（任务点 {progress.completed_videos}/{progress.total_videos}）")

    log.success("所有待学习课程学习完毕")
    generic_user_block(setting, user, _DISPLAY, brush_func=None)


def _fetch_all_courses(cache: ZhsUserCache, log) -> List[ZhsCourse]:
    """拉取全部课程: Polymas(AI课+共享课) + Hike(共享课去重补漏)"""
    courses: List[ZhsCourse] = []
    seen_ids: set = set()

    # 1. Polymas(新版聚合 API): 遍历三种状态确保覆盖
    try:
        poly = PolymasAPIClient(cache.session)
        poly.ensure_token(expected_user_id=cache.cas_user_id)
        for status in (1, 2, 3):
            for c in poly.get_courses(status=status):
                cid = str(c.get("courseId", ""))
                if not cid or cid in seen_ids:
                    continue
                ctype = c.get("courseType", "")
                classes = c.get("studentClasses") or []
                class_id = classes[0].get("classId") if classes else None
                if ctype == "hikeAiCourse" and class_id:
                    courses.append(ZhsCourse(
                        id=cid, name=c.get("courseName", "unknown"),
                        course_type=CourseType.POLYMAS_AI, class_id=str(class_id)))
                    seen_ids.add(cid)
                elif ctype == "spocCourse":
                    courses.append(ZhsCourse(
                        id=cid, name=c.get("courseName", "unknown"),
                        course_type=CourseType.HIKE))
                    seen_ids.add(cid)
    except ZhsError as e:
        log.warning(f"Polymas 课程获取失败: {e}")
    except Exception as e:
        log.warning(f"Polymas 课程获取异常: {e}")

    # 2. Hike(旧版共享课)作为补充
    try:
        hike = HikeAPIClient(cache.session, uuid=cache.session.uuid)
        for c in hike.get_course_list():
            cid = str(c.get("courseId", ""))
            if cid and cid not in seen_ids:
                courses.append(ZhsCourse(
                    id=cid, name=c.get("courseName", "unknown"),
                    course_type=CourseType.HIKE))
                seen_ids.add(cid)
    except Exception as e:
        log.warning(f"Hike 课程获取异常: {e}")

    return courses


def _brush_course(cache: ZhsUserCache, user: User, course: ZhsCourse,
                  speed: float, log) -> StudyProgress:
    """按课程类型分发刷课"""
    if course.course_type == CourseType.POLYMAS_AI:
        return _brush_polymas_course(cache, user, course, speed, log)
    return _brush_hike_course(cache, user, course, speed, log)


# ============ Polymas AI 课刷课 ============

def _brush_polymas_course(cache: ZhsUserCache, user: User, course: ZhsCourse,
                          speed: float, log) -> StudyProgress:
    """Polymas AI 课: 目录树遍历 → 逐视频上报进度"""
    api = PolymasAPIClient(cache.session)
    api.ensure_token(expected_user_id=cache.cas_user_id)
    nodes, _lib_id = api.get_course_structure(course.id, course.class_id or "")
    if not nodes:
        log.warning(f"课程【{course.name}】目录为空, 跳过")
        return StudyProgress()
    log.info(f"正在学习课程（AI课）: {course.name}")
    begin = time.time()
    progress = StudyProgress()
    try:
        _traverse_polymas(api, course, nodes, speed, progress, log)
    except ZhsError as e:
        log.error(f"课程【{course.name}】刷课失败: {e}")
    progress.elapsed_seconds = time.time() - begin
    log.success(
        f"课程【{course.name}】学习完毕"
        f"（任务点 {progress.completed_videos}/{progress.total_videos}，"
        f"耗时 {progress.elapsed_seconds:.0f}s）")
    return progress


def _traverse_polymas(api, course, nodes: list, speed: float,
                      progress: StudyProgress, log, depth: int = 0) -> None:
    """递归遍历 Polymas 课程结构(type=1 文件夹, type=2 文件)"""
    for node in nodes:
        detail = node.get("detail", {}) or {}
        title = detail.get("title", "")
        if node.get("type") == 1:
            children = node.get("children", []) or []
            if children:
                try:
                    _traverse_polymas(api, course, children, speed,
                                      progress, log, depth + 1)
                except Exception as e:
                    log.error(f"遍历文件夹 {title} 失败: {e}")
        elif node.get("type") == 2:
            try:
                biz_suffix = detail.get("bizSuffix", "")
                is_video = (detail.get("classify") == "file"
                            and biz_suffix in ("mp4", "avi", "mov", "flv"))
                if is_video:
                    _polymas_video(api, course, node, speed, progress, log)
                elif node.get("isFinished"):
                    progress.bump_total()
                    progress.bump_completed()
            except Exception as e:
                log.error(f"处理文件节点 {title} 失败: {e}")


def _polymas_video(api, course, node: dict, speed: float,
                   progress: StudyProgress, log) -> None:
    """单个 Polymas 视频: 循环上报进度直至达到完成阈值(90%)"""
    import json as _json
    progress.bump_total()
    detail = node.get("detail", {}) or {}
    title = detail.get("title", "")
    rid = node.get("nodeId", "")
    try:
        ext = _json.loads(detail.get("ext", "{}"))
    except (ValueError, TypeError):
        ext = {}
    duration = ext.get("duration", 0) or 0
    pct = node.get("completePercentage", 0) or 0
    done = node.get("isFinished", False) or pct >= 90

    if done or duration == 0:
        progress.bump_completed()
        return

    log.info(f"视频任务点: {title}（时长 {duration // 60}:{duration % 60:02d}）")
    api.event_track(rid, course.id, course.class_id)
    curr = int(duration * pct / 100)
    # 超时保护: 理论上 duration/30 次播完, 额外 +60 次容错
    max_iters = (duration // _REPORT_STEP) + 60
    while curr < duration and max_iters > 0:
        max_iters -= 1
        nxt = min(curr + _REPORT_STEP, duration)
        time.sleep(uniform(1, 3) / max(speed, 0.1))
        rate = None
        for attempt in range(3):
            try:
                rate = api.report_progress(rid, course.id, curr, nxt, nxt - curr)
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                else:
                    log.error(f"进度上报重试3次均失败: {e}")
        if rate is not None and rate >= 90:
            progress.bump_completed()
            log.success(f"视频完成: {title}")
            return
        curr = nxt
    # 循环自然结束(播放到末尾, 未触发 90% 判定)或容错耗尽
    if max_iters > 0:
        progress.bump_completed()
        log.success(f"视频完成: {title}")
    else:
        log.warning(f"视频未播完(超过最大重试次数): {title}")


# ============ Hike 共享课刷课 ============

def _brush_hike_course(cache: ZhsUserCache, user: User, course: ZhsCourse,
                       speed: float, log) -> StudyProgress:
    """Hike 共享课: 资源菜单树遍历 → 视频进度上报/非视频标记完成"""
    api = HikeAPIClient(cache.session, uuid=cache.session.uuid)
    # 对齐 SDK: 请求头模拟从 hikeservice 页面发起
    api._session.session.headers.update({
        "Origin": "https://hike.zhihuishu.com",
        "Referer": "https://hike.zhihuishu.com/",
    })
    root = api.query_resource_menu_tree(course.id)
    if not isinstance(root, list):
        root = [root]
    log.info(f"正在学习课程（共享课）: {course.name}")
    begin = time.time()
    progress = StudyProgress()
    for chapter in root:
        try:
            _traverse_hike(api, course, chapter, speed, progress, log)
        except ZhsError as e:
            log.error(f"课程【{course.name}】刷课失败: {e}")
            break
    progress.elapsed_seconds = time.time() - begin
    log.success(
        f"课程【{course.name}】学习完毕"
        f"（任务点 {progress.completed_videos}/{progress.total_videos}，"
        f"耗时 {progress.elapsed_seconds:.0f}s）")
    return progress


def _traverse_hike(api, course, node: Any, speed: float,
                   progress: StudyProgress, log, depth: int = 0) -> None:
    """递归遍历 Hike 资源树(目录含 childList 递归; 叶子按 dataType 处理)"""
    child_list = node.get("childList") if isinstance(node, dict) else None
    if child_list:
        for child in child_list:
            _traverse_hike(api, course, child, speed, progress, log, depth + 1)
        return
    if not isinstance(node, dict):
        return
    file_id = node.get("id")
    study_time = node.get("studyTime") or 0
    total_time = node.get("totalTime") or 0
    name = node.get("name", "")
    # 已学满完成阈值的资源跳过
    if total_time and study_time >= total_time * _END_THRESHOLD:
        return
    progress.bump_total()
    try:
        data_type = node.get("dataType")
        if data_type == 3:
            # 视频资源: 模拟播放
            if _hike_video(api, course, file_id, name,
                           study_time, total_time, speed, log):
                progress.bump_completed()
        elif data_type is None:
            # 不支持的类型(如测验/问卷): 仅提示不处理
            log.info(f"不支持的任务点类型(如测验/问卷), 跳过: {name}")
        else:
            # 文档/图片等非视频资源: 直接标记已观看
            api.stu_view_file(course.id, file_id)
            time.sleep(random() * 2 + 1)
            progress.bump_completed()
    except ZhsError:
        raise
    except Exception as e:
        log.error(f"处理任务点 {name} 失败: {e}")


def _hike_video(api, course, file_id, name, prev_time, total_time,
                speed: float, log) -> bool:
    """单个 Hike 视频: 标记观看 → 后台拉流(防检测) → 循环上报进度"""
    try:
        api.stu_view_file(course.id, file_id)
        _watch_video_init(api, file_id)
    except Exception as e:
        log.error(f"视频初始化失败 {name}: {e}")
        return False

    int_total = int(total_time)
    log.info(f"视频任务点: {name}（{int_total // 60}分{int_total % 60:02d}秒）")
    end_time = max(total_time * _END_THRESHOLD, 1.0)
    played = prev_time
    start_date = int(time.time() * 1000)
    # 超时保护: 理论上约 end_time/30 次播完, 额外 +120 次容错
    max_iters = int(end_time / _REPORT_STEP) + 120
    error = False

    while played is not None and played <= end_time and max_iters > 0:
        max_iters -= 1
        time.sleep(1 / max(speed, 0.1))
        played = min(played + _REPORT_STEP, end_time)
        try:
            reported = api.save_study_record(
                course.id, file_id, int(played), prev_time, start_date)
        except Exception as e:
            log.error(f"上报学习进度失败: {e}")
            error = True
            break
        if reported is None:
            log.error("save_study_record 返回空")
            error = True
            break
        # 用服务端返回值覆盖本地进度(防服务端与本地不一致)
        prev_time, played = reported, reported

    # 与 SDK 语义一致: 上报链路无异常即视为完成(进度数据以服务端返回为准)
    completed = not error
    if completed:
        time.sleep(random() + 1)  # 完成后短暂随机休眠, 模拟人工停顿
        log.success(f"视频完成: {name}")
    return completed


def _watch_video_init(api, video_id: str) -> None:
    """后台线程初始化视频拉流, 模拟真实播放器行为(不阻塞主流程)

    智慧树服务端会记录视频初始化请求; 不发该请求直接上报进度易被判脚本刷课。
    """
    def _do():
        try:
            import json as _json
            import re as _re
            r = api._session.get(
                "https://newbase.zhihuishu.com/video/initVideo",
                params={"jsonpCallBack": "result", "videoID": video_id,
                        "_": int(time.time() * 1000)},
                timeout=5,
            )
            match = _re.match(r"^result\((.*)\)$", r.text)
            if match:
                url = _json.loads(match.group(1))["result"]["lines"][0]["lineUrl"]
                api._session.get(url, timeout=5)
        except Exception:
            pass

    threading.Thread(target=_do, daemon=True).start()
