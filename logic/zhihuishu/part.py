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
    HikeAPIClient, ManagedSession, PolymasAPIClient, ShareCourseAPIClient,
    login_password, validate_session,
)
from logic.zhihuishu.models import (
    CourseType, StudyProgress, ZhsAuthError, ZhsCaptchaError, ZhsCourse,
    ZhsExtraAuthRequired, ZhsSmsRequired,
    ZhsError, ZhsUserCache,
)
from logic.zhihuishu.auth_state import load_session, save_session, session_key
from utils.log import log_print, with_log_account, INFO, Red, Yellow

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
    """批量登录(纯 HTTP，会话优先，单账号失败仅跳过)。"""
    user_caches: List[ZhsUserCache] = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        log = get_simple_logger(
            f"[{_DISPLAY}][{display_account(user.account)}]")
        if not (user.account or "").strip():
            log.error("账号为空, 已跳过")
            continue

        session = None
        session_id = session_key(user.account)
        try:
            stored = load_session(session_id)
            if stored:
                candidate = ManagedSession(cookies=stored[0])
                if validate_session(candidate):
                    session = candidate
                    log.success("已复用加密保存的智慧树会话")
        except Exception as e:
            log.warning(f"缓存会话不可用，将重新执行协议登录: {e}")

        if session is None:
            try:
                if not (user.password or "").strip():
                    log.error("没有有效会话且密码为空, 已跳过")
                    continue
                session = ManagedSession()
                login_password(session, user.account.strip(), user.password)
                save_session(session_id, session.cookies)
                log.success("协议登录成功")
            except ZhsCaptchaError as e:
                # 滑块已由 login_password 内置纯协议求解器自动处理;
                # 到这里说明求解未通过(小概率), 重试一次后跳过
                log.warning(f"易盾滑块未通过, 重试一次: {e}")
                try:
                    session = ManagedSession()
                    login_password(session, user.account.strip(),
                                   user.password)
                    save_session(session_id, session.cookies)
                    log.success("协议登录成功(重试)")
                except Exception as e2:
                    log.error(f"重试仍失败, 已跳过: {e2}")
                    continue
            except ZhsSmsRequired as e:
                log.error(f"登录状态 SMS_REQUIRED: {e}")
                continue
            except ZhsExtraAuthRequired as e:
                log.error(f"登录状态 EXTRA_AUTH_REQUIRED: {e}")
                continue
            except ZhsAuthError as e:
                log.error(f"登录状态 INVALID_CREDENTIALS: {e}")
                continue
            except Exception as e:
                log.error(f"登录异常: {e}")
                continue

        cache = ZhsUserCache(
            account=user.account, password=user.password,
            session=session, cas_user_id=session.get_cas_user_id(),
        )
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
        t = threading.Thread(
            target=with_log_account(
                matched.account, matched.remark_name)(_user_block),
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
    # 夜间休息检查(2026-10-10 修复): 入口级——休息时段内等待到点继续
    try:
        from logic.platform_common import rest_wait_if_needed as _pub_rest_wait
        _pub_rest_wait(user.account, user.courses_custom,
                       ACCOUNT_TYPE_STR[PLATFORM_TYPE])
    except Exception:
        pass
    for course in courses:
        # 夜间休息检查(2026-10-10 修复: 课程级——刷课中途到点即停,恢复后继续)
        try:
            from logic.platform_common import rest_wait_if_needed as _pub_rest_wait
            _pub_rest_wait(user.account, user.courses_custom,
                           ACCOUNT_TYPE_STR[PLATFORM_TYPE])
        except Exception:
            pass
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
                elif ctype == "shareCourse":
                    # 新版共享课(studyvideoh5): 2026-10-13 升级协议级秒刷
                    # 三元组全部来自本响应: ccCourseId=courseId / recruitId / rid=origenParam.secret
                    _op = c.get("origenParam") or {}
                    courses.append(ZhsCourse(
                        id=cid, name=c.get("courseName", "unknown"),
                        course_type=CourseType.SHARE,
                        recruit_id=str(c.get("recruitId")
                                       or _op.get("recruitId") or ""),
                        rid=str(_op.get("secret") or "")))
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
    if course.course_type == CourseType.SHARE:
        return _brush_share_course(cache, user, course, speed, log)
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
                rate = api.report_progress(
                    rid, course.id, curr, nxt, nxt - curr)
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
                url = _json.loads(match.group(1))[
                    "result"]["lines"][0]["lineUrl"]
                api._session.get(url, timeout=5)
        except Exception:
            pass

    threading.Thread(target=_do, daemon=True).start()


# ============ Web 端课程查询(供前端控制台"课程"按钮) ============

def _count_zhs_tree(nodes) -> tuple:
    """递归统计智慧树目录树节点完成度(兼容多种完成标记)"""
    fin = total = 0
    for n in (nodes or []):
        if not isinstance(n, dict):
            continue
        children = (n.get("children") or n.get("childList")
                    or n.get("resourceList") or [])
        if isinstance(children, list) and children:
            f2, t2 = _count_zhs_tree(children)
            fin += f2
            total += t2
            continue
        total += 1
        try:
            v = float(n.get("studyProgress", 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if (v >= 100 or n.get("completeRate") in (100, "100")
                or n.get("finished") in (1, True)
                or n.get("studyStatus") in (2, "2")):
            fin += 1
    return fin, total


def web_course_list(cache: ZhsUserCache, user: User) -> List[dict]:
    """Web端课程列表+总进度 - 智慧树(遍历课程目录树统计节点完成度)"""
    import logging as _lg
    log = _lg.getLogger("zhs-web")
    courses = _fetch_all_courses(cache, log)
    result = []
    for c in courses:
        fin, total, has = 0, 0, False
        try:
            if c.course_type == CourseType.POLYMAS_AI and c.class_id:
                poly = PolymasAPIClient(cache.session)
                poly.ensure_token(expected_user_id=cache.cas_user_id)
                tree, _lib = poly.get_course_structure(c.id, c.class_id)
                fin, total = _count_zhs_tree(tree)
                has = total > 0
        except Exception:
            pass
        rate = round(fin / total * 100, 1) if total else 0.0
        result.append({
            "courseId": str(c.id),
            "courseName": c.name,
            "teacher": "",
            "jobFinishCount": fin,
            "jobCount": total,
            "jobRate": rate,
            "hasProgress": has,
            "statusText": ("已完成" if (total and fin >= total)
                           else ("进行中" if has else "")),
        })
    return result


# ============ 新版共享课(studyvideoh5) 刷课 ============

def _brush_share_course(cache: ZhsUserCache, user: User, course: ZhsCourse,
                        speed: float, log) -> StudyProgress:
    """新版共享课(studyvideoh5)刷课
    2026-10-13 升级: "协议级秒刷优先"(实测24/24全绿, 借助热心人士资料);
    三元组: ccCourseId=course.id, recruitId=course.recruit_id, rid=学堂解析;
    任一步失败自动回退旧逐秒上报流程(下方保留)。
    """
    api = ShareCourseAPIClient(cache.session)
    api.ensure_session()
    # ---- 协议级秒刷优先 ----
    try:
        _cc = int(str(course.id or "0").strip() or 0)
        _rec_s = str(course.recruit_id or "").strip()
        _rec = int(_rec_s) if _rec_s else 0
        if _cc and _rec:
            from logic.zhihuishu.share_proto import brush_share_protocol, resolve_rid
            # 2026-10-13: rid优先取课程响应自带(origenParam.secret), 兜底学堂解析
            _rid = str(getattr(course, "rid", "")
                       or "").strip() or resolve_rid(api, _cc)
            if _rid:
                log.info(f"课程【{course.name}】协议级秒刷: rid={_rid[:12]}...")
                _st = brush_share_protocol(
                    cache, _rid, _cc, _rec, log=log.info)
                _prog = StudyProgress()
                _prog.total_videos = int(_st.get("total", 0) or 0)
                _prog.completed_videos = int(_st.get("full", 0) or 0)
                _prog.elapsed_seconds = float(_st.get("elapsed", 0) or 0)
                log.success(
                    f"课程【{course.name}】协议秒刷完成: "
                    f"{_prog.completed_videos}/{_prog.total_videos}")
                return _prog
            log.warning(f"课程【{course.name}】rid解析为空, 回退旧流程")
        else:
            log.info(f"课程【{course.name}】缺 recruitId/ccCourseId, 回退旧流程")
    except Exception as _e:
        log.warning(f"课程【{course.name}】协议秒刷异常, 回退: {str(_e)[:120]}")
    # ---- 旧逐秒上报流程(回退保留) ----
    rid = str(course.id or "")
    if not rid:
        log.warning(f"课程【{course.name}】缺少 recruitAndCourseId, 跳过")
        return StudyProgress()
    qc = api.query_course(rid)
    if not _share_ok(qc):
        msg = (qc or {}).get("message", "")
        log.warning(
            f"课程【{course.name}】共享课接口校验失败({msg})，可能会话未建立或平台限制，已跳过(可重登后重试)")
        return StudyProgress()
    vl = api.video_list(rid)
    if not _share_ok(vl):
        log.warning(
            f"课程【{course.name}】videolist 获取失败({(vl or {}).get('message', '')})，已跳过")
        return StudyProgress()
    videos = _extract_share_videos(vl.get("data") or {})
    if not videos:
        log.info(f"课程【{course.name}】无可学习视频或已全部完成")
        return StudyProgress()
    log.info(f"正在学习课程(新版共享课): {course.name} (视频 {len(videos)} 个)")
    begin = time.time()
    progress = StudyProgress()
    for v in videos:
        try:
            _share_video(api, course, rid, v, speed, progress, log)
        except ZhsError as e:
            log.error(f"课程【{course.name}】刷课失败: {e}")
            break
    progress.elapsed_seconds = time.time() - begin
    log.success(
        f"课程【{course.name}】学习完毕(视频 {progress.completed_videos}/{progress.total_videos}, 耗时 {progress.elapsed_seconds:.0f}s)")
    return progress


def _share_ok(resp) -> bool:
    """共享课网关响应是否有效(code==0 或 200)"""
    if not isinstance(resp, dict):
        return False
    return resp.get("code") in (0, 200, "0", "200")


def _extract_share_videos(data) -> list:
    """解析 videolist 响应中的视频数组(容错嵌套)"""
    videos = []

    def _walk(node):
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return
        vid = node.get("videoId") or node.get("id") or node.get("fileId")
        if vid is not None and (node.get("videoName") or node.get("name") or node.get("duration") is not None):
            videos.append(node)
            return
        for child in node.values():
            _walk(child)
    _walk(data)
    seen = set()
    out = []
    for v in videos:
        key = str(v.get("videoId") or v.get("id") or v.get("fileId"))
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _share_video(api, course, rid: str, video: dict, speed: float,
                 progress: StudyProgress, log) -> None:
    """单个共享课视频: 模拟播放 + 周期上报进度(91%完成)"""
    vid = str(video.get("videoId") or video.get("id") or video.get("fileId"))
    name = str(video.get("videoName") or video.get("name") or vid)
    duration = int(video.get("duration") or video.get("videoDuration") or 0)
    studied = int(video.get("studiedTime") or video.get("studyTime") or 0)
    if duration and studied >= duration * _END_THRESHOLD:
        return
    progress.bump_total()
    log.info(f"视频任务点: {name} ({duration // 60}分{duration % 60:02d}秒)")
    end_time = max(duration * _END_THRESHOLD, 1.0)
    played = studied
    watchdog = int(time.time() * 1000)
    max_iters = int(end_time / _REPORT_STEP) + 120
    try:
        api.save_cache_time(_share_payload(
            rid, vid, 0, studied, duration, watchdog))
    except Exception:
        pass
    while played <= end_time and max_iters > 0:
        max_iters -= 1
        time.sleep(1 / max(speed, 0.1))
        played = min(played + _REPORT_STEP, end_time)
        payload = _share_payload(rid, vid, int(
            played - studied), int(played), duration, watchdog)
        res = api.save_cache_time(payload)
        if not _share_ok(res):
            res = api.save_database_time(payload)
            if not _share_ok(res):
                log.error(
                    f"共享课进度上报失败: {name} ({(res or {}).get('message', '')})")
                return
        data = res.get("data") or {}
        if isinstance(data, dict):
            total = data.get("studyTotalTime") or data.get("studiedTime")
            if isinstance(total, (int, float)) and total > played:
                played = int(total)
    if max_iters > 0:
        progress.bump_completed()
        log.success(f"视频完成: {name}")
    else:
        log.warning(f"视频未播完(超时): {name}")


def _share_payload(rid: str, vid: str, interval: int, total: int,
                   duration: int, watchdog: int) -> dict:
    """构造进度上报参数(对齐页面字段命名)"""
    return {
        "recruitAndCourseId": str(rid),
        "videoId": str(vid),
        "intervalTime": int(interval),
        "cacheIntervalTime": int(total),
        "studyTotalTime": int(total),
        "watcVideoTime": int(total),
        "videoDuration": int(duration),
        "startWatchTime": watchdog,
        "clientType": "Windows",
    }
