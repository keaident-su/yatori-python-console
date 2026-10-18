# -*- coding: utf-8 -*-
"""
智慧树平台逻辑 - 移植自外部项目 zhihuishu_sdk(fuckzhs) 并适配本工程架构

流程: 密码登录 → 拉取课程(Polymas AI课 + Hike共享课, 自动去重) → 课程过滤
      → 按课程类型刷课(视频逐段上报进度, 非视频任务点标记完成) → 完成通知
支持: includeCourses/excludeCourses 课程过滤; zhsSpeed 刷课速度倍率(默认1.5)
说明: 智慧树课程考试(实验性 AI 答题)暂未接入, 如需后续补充
"""
import os
import asyncio as _asyncio
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
        # 2026-10-19: 身份信息(智慧树: CASLOGC cookie解姓名/userId, jt-cas JWT兜底)
        try:
            from logic.zhihuishu.api import fetch_user_profile as _zhs_prof
            from logic.platform_common import save_user_identity
            _pf = _zhs_prof(session)
            if _pf.get("name"):
                save_user_identity(user, school=_pf.get("school", ""),
                                   name=_pf.get("name", ""),
                                   stu_no=_pf.get("stuNo", ""),
                                   log=log.success)
        except Exception:
            pass
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
                elif ctype == "mapCourse":
                    # AI智课(mapCourse, ai-smart-course-student-pro平台): 2026-10-14新增
                    # classId 取顶层或 studentClasses[0]
                    _cls = str(c.get("classId") or "")
                    if not _cls:
                        _classes = c.get("studentClasses") or []
                        _cls = str(_classes[0].get("classId")
                                   or "") if _classes else ""
                    courses.append(ZhsCourse(
                        id=cid, name=c.get("courseName", "unknown"),
                        course_type=CourseType.AI_SMART,
                        class_id=_cls or None))
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
    """按课程类型分发刷课(2026-10-14: 类型自动识别 + 专属开关过滤)"""
    custom = getattr(user, "courses_custom", None)

    def _sw_on(name: str, default: int = 1) -> bool:
        try:
            return int(getattr(custom, name, default) or 0) == 1
        except Exception:
            return default == 1

    ctype = course.course_type
    _sw_map = {
        CourseType.SHARE: ("zhs_share_sw", 1, "共享课"),
        CourseType.POLYMAS_AI: ("zhs_ai_course_sw", 1, "AI课"),
        CourseType.HIKE: ("zhs_hike_sw", 1, "Hike共享课"),
        CourseType.AI_SMART: ("zhs_ai_smart_sw", 0, "AI智课"),
    }
    sw_name, sw_default, label = _sw_map.get(ctype, ("", 1, ""))
    if sw_name and not _sw_on(sw_name, sw_default):
        log.info(f"课程【{course.name}】{label}: 专属开关已关闭, 跳过")
        return StudyProgress()

    if ctype == CourseType.POLYMAS_AI:
        _p = _brush_polymas_course(cache, user, course, speed, log)
    elif ctype == CourseType.SHARE:
        _p = _brush_share_course(cache, user, course, speed, log)
    elif ctype == CourseType.AI_SMART:
        _p = _brush_ai_smart_course(cache, user, course, speed, log)
    else:
        _p = _brush_hike_course(cache, user, course, speed, log)
    # 2026-10-15: 课程学习完成后的作业/考试处理(开关默认关)
    try:
        _zhs_work_exam_action(cache, user, course, log)
    except Exception:
        pass
    return _p


# ============ AI智课(mapCourse, ai-smart-course-student-pro) 刷课 ============
# 2026-10-14: 平台测绘完成(needSecret加密门 + idMaps密钥ID体系(6:AI课/11:studyservice)
# + learning/saveCacheIntervalTimeV2 等同名上报接口 + 免密白名单saveUserStudyProcess);
# 首版: 结构探测+进度查看; 上报链路密钥链补齐后全协议化

async def _ai_smart_visit_and_brush(jar: dict, course, todo: list, log) -> None:
    """AI智课完整链(nodriver访问注册 + 终极brush)

    2026-10-15 实测: 访问注册(learnPage JS执行) + 全视频report序列 + 全资源completed = prog 100%
    """
    import importlib as _il
    _nd = _il.import_module("nodriver")
    from logic.zhihuishu.ai_smart_proto import AiSmartAPI
    api = AiSmartAPI(jar)
    UDD = os.path.join(os.environ.get("TEMP", "/tmp"), "yatori-zhs-aismart")
    browser = await _nd.start(user_data_dir=UDD,
                              browser_args=["--window-size=1300,900", "--disable-quic"])
    try:
        import json as _js
        tab = await browser.get("https://www.zhihuishu.com/")
        await _asyncio.sleep(2)
        try:
            from nodriver import cdp as _cdp
            _params = []
            for _n, _v in jar.items():
                if _n and _v:
                    _params.append(_cdp.network.CookieParam(
                        name=str(_n), value=str(_v),
                        domain=".zhihuishu.com", path="/"))
            await tab.send(_cdp.network.set_cookies(cookies=_params))
        except Exception:
            pass
        for _i, (_kid, _prog, _name) in enumerate(todo):
            _url = ("https://ai-smart-course-student-pro.zhihuishu.com"
                    "/learnPage/%s/%s/%s?mapUid=1935993298808344576"
                    % (course.id, _kid, course.class_id))
            try:
                await tab.get(_url)
                await _asyncio.sleep(10)
            except Exception:
                try:
                    await _asyncio.sleep(3)
                    await tab.get(_url)
                    await _asyncio.sleep(10)
                except Exception:
                    pass
            try:
                api.brush_video_knowledge(course.id, course.class_id, _kid)
            except Exception:
                pass
            if (_i + 1) % 10 == 0:
                try:
                    log.info(f"   AI智课全链进度: {_i+1}/{len(todo)}")
                except Exception:
                    pass
    finally:
        try:
            browser.stop()
        except Exception:
            pass


def _brush_ai_smart_course(cache: ZhsUserCache, user: User, course: ZhsCourse,
                           speed: float, log) -> StudyProgress:
    """AI智课刷课(2026-10-15 终极版)

    完整公式(实测prog 0→100%):
      访问注册(learnPage,nodriver可选) + 全部视频report序列 + study心跳 + 全资源completed
    prog = 已完成资源数/总资源数; 多视频需遍历; 超长多视频需多轮重刷.
    无nodriver时降级为"纯API上报"(已访问过知识点仍生效).
    """
    progress = StudyProgress()
    jar = {}
    try:
        for ck in cache.session.cookies:
            if ck.name and ck.value:
                jar[ck.name] = ck.value
    except Exception:
        pass
    log.info(f"正在学习课程（AI智课）: {course.name}")
    try:
        from logic.zhihuishu.ai_smart_proto import AiSmartAPI
        api = AiSmartAPI(jar)
        r = api.list_knowledge_theme(course.id, course.class_id)
        themes = ((r.get("data") or {}).get("courseThemeList") or [])
        kids = []
        for th in themes:
            for sub in (th.get("subThemeList") or []):
                for kp in (sub.get("knowledgeList") or []):
                    kids.append((kp.get("knowledgeId"),
                                 kp.get("studyProgress") or 0,
                                 kp.get("knowledgeName", "")))
        if not kids:
            log.warning(f"课程【{course.name}】知识点为空(未选课/无权限), 跳过")
            return progress
        todo = [(k, p, n) for k, p, n in kids if p < 100]
        log.info(f"   知识点={len(kids)} | 待刷={len(todo)}")
        if not todo:
            log.info(f"课程【{course.name}】AI智课已全部 100%, 无需刷课")
            return progress
        # 2026-10-15: 读取智慧树新配置(安全默认)
        _cc = getattr(user, "courses_custom", None)
        _visit_sw = int(getattr(_cc, "zhs_ai_smart_visit_sw", 1)
                        or 0) if _cc else 1
        _rounds = max(
            1, int(getattr(_cc, "zhs_ai_smart_rounds", 1) or 1)) if _cc else 1
        done_mode = ""
        for _rd in range(1, _rounds + 1):
            if _visit_sw == 1:
                try:
                    _asyncio.run(_ai_smart_visit_and_brush(
                        jar, course, todo, log))
                    done_mode = f"完整链(访问注册+序列+completed) x{_rd}"
                except Exception as e1:
                    log.warning(f"   全链模式不可用({str(e1)[:70]}), 降级纯API上报")
                    for kid, _p, _n in todo:
                        try:
                            api.brush_video_knowledge(
                                course.id, course.class_id, kid)
                        except Exception:
                            pass
                    done_mode = f"纯API上报(零访问知识点可能不生效, 建议重刷) x{_rd}"
            else:
                # 按配置跳过访问注册(仅API上报)
                for kid, _p, _n in todo:
                    try:
                        api.brush_video_knowledge(
                            course.id, course.class_id, kid)
                    except Exception:
                        pass
                done_mode = f"纯API上报(已按配置跳过访问注册) x{_rd}"
            if _rd < _rounds:
                log.info(f"   AI智课补刀: 第{_rd + 1}/{_rounds}轮重刷中...")
        log.info(
            f"课程【{course.name}】AI智课上报完成: {len(todo)}个知识点 | 模式={done_mode}")
    except Exception as e:
        log.warning(f"课程【{course.name}】AI智课刷课异常: {str(e)[:120]}")
    return progress


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
            elif c.course_type == CourseType.AI_SMART:
                # AI智课(2026-10-14): 结构页可达性探测+节数统计(尽力)
                import httpx as _hx2
                import urllib3 as _u3b
                _u3b.disable_warnings()
                _jar = {}
                for _ck in cache.session.cookies:
                    if _ck.name and _ck.value:
                        _jar[_ck.name] = _ck.value
                _cli2 = _hx2.Client(cookies=_jar, timeout=15,
                                    verify=False, follow_redirects=True)
                _r2 = _cli2.get(
                    f"https://ai-smart-course-student-pro.zhihuishu.com/singleCourse/"
                    f"knowledgeStudy/{c.id}/{c.class_id or ''}")
                has = _r2.status_code == 200
            elif c.course_type == CourseType.SHARE:
                # 共享课真实进度(2026-10-14完善): lessons + prelearning逐节比对
                from logic.zhihuishu.share_proto import (
                    list_lessons, resolve_rid, _prelearning)
                _sapi = ShareCourseAPIClient(cache.session)
                _sapi.ensure_session()
                _cc = int(str(c.id or "0").strip() or 0)
                _rs = str(c.recruit_id or "").strip()
                _rec = int(_rs) if _rs else 0
                _rid = str(getattr(c, "rid", "") or "").strip() \
                    or resolve_rid(_sapi, _cc)
                if _rid and _cc:
                    _lessons = list_lessons(_sapi, _rid)
                    total = len([x for x in _lessons if x.get("sec", 0) > 0])
                    _fin = 0
                    for _l in _lessons:
                        if _l.get("sec", 0) <= 0:
                            continue
                        try:
                            _, _learn = _prelearning(_sapi, _cc, _rec, _l)
                            if _learn >= _l["sec"]:
                                _fin += 1
                        except Exception:
                            pass
                    fin = _fin
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
            "courseType": c.course_type.value,
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

# ============ 智慧树作业/考试链 (2026-10-15 骨架版, 开关默认关) ============


def _zhs_work_exam_action(cache: ZhsUserCache, user: User, course: ZhsCourse, log):
    """智慧树作业/考试处理(骨架版)

    消费配置: zhs_work_sw/zhs_exam_sw(默认0关) / zhs_collect_only_sw(只采集)
             / zhs_submit_rate(正确率提交阈值) / zhs_exam_pace(拟人节奏)
    链路: exam_proto(look_homework/get_student_homework/do_exam) 拉题
          -> bridge多源答题 -> (提交做题接口参数定型后启用) -> 缓存
    注: 提交接口参数白名单未定型(实验性), 当前仅完成"拉题+答题+缓存"就绪;
        zhs_collect_only_sw=1时仅采集归档不提交。
    """
    cc = getattr(user, "courses_custom", None)
    if cc is None:
        return
    _work_on = int(getattr(cc, "zhs_work_sw", 0) or 0) == 1
    _exam_on = int(getattr(cc, "zhs_exam_sw", 0) or 0) == 1
    if not (_work_on or _exam_on):
        return
    try:
        from logic.zhihuishu.exam_proto import ZhsExamAPI
        from logic.core.answer_bridge import bridge_answer_one, bridge_cache_results
    except Exception:
        return
    jar = {}
    try:
        for ck in cache.session.cookies:
            if ck.name and ck.value:
                jar[ck.name] = ck.value
    except Exception:
        pass
    ex = ZhsExamAPI(jar)
    recruit_id = str(getattr(course, "recruit_id", "") or course.id)
    course_id = str(course.id)
    _pace = int(getattr(cc, "zhs_exam_pace", 1) or 0)
    _rate = int(getattr(cc, "zhs_submit_rate", 100) or 100)
    _collect_only = int(getattr(cc, "zhs_collect_only_sw", 0) or 0)
    log.info(
        f"课程【{course.name}】作业/考试链(工作业={'开' if _work_on else '关'} 考试={'开' if _exam_on else '关'} 只采集={_collect_only})")

    def _process_homework_list():
        try:
            r = ex.get_student_homework(recruit_id, course_id, type=2)
        except Exception as e:
            log.warning(f"   作业列表拉取异常: {str(e)[:60]}")
            return
        lst = (r.get("rt") or {}).get("list") or (
            r.get("data") or {}).get("list") or []
        for hw in (lst if isinstance(lst, list) else []):
            if not isinstance(hw, dict):
                continue
            _st = hw.get("status")
            if _st in (2, "2"):
                continue  # 已完成跳过
            hw_id = hw.get("id") or hw.get("homeworkId")
            try:
                hw_id = int(hw_id)
            except Exception:
                continue
            try:
                detail = ex.look_homework(hw_id)
            except Exception as e:
                log.warning(f"   作业[{hw_id}]拉卷异常: {str(e)[:60]}")
                continue
            qs = ((detail.get("rt") or {}).get("questionList")
                  or (detail.get("data") or {}).get("questionList") or [])
            _results = []
            _low = 0
            for q in (qs if isinstance(qs, list) else []):
                if not isinstance(q, dict):
                    continue
                q_text = str(q.get("content", "") or q.get(
                    "questionContent", "") or "")
                opts = q.get("optionList") or q.get("options") or []
                opt_texts = [str((o or {}).get("content", ""))
                             for o in opts if isinstance(o, dict)]
                _ans, _src = bridge_answer_one(
                    q_text, options=opt_texts, q_type="")
                if _src and ("AI" in str(_src)):
                    _low += 1
                _results.append(
                    {"q_text": q_text, "answer": _ans, "src": _src, "q_type": ""})
                if _pace >= 1:
                    time.sleep(uniform(1.0, 2.5))
            if not _results:
                continue
            _n = bridge_cache_results(_results)
            _low_ratio = int(_low * 100 / max(1, len(_results)))
            if _collect_only:
                log.info(f"   作业[{hw_id}] 只采集模式: 已归档{len(_results)}题(不提交)")
            elif _low_ratio > _rate:
                log.info(
                    f"   作业[{hw_id}] 低置信度占比{_low_ratio}%>{_rate}%, 仅保存不提交")
            else:
                # 2026-10-15: 启用提交(saveStudentAnswer逐题 + answer/submit交卷)
                # 选项ID: 从题干qinfo取; 答案文本/字母 -> 选项ID
                _ok_sub = 0
                for _r, _q in zip(_results, qs):
                    try:
                        _qinfo = _q if isinstance(_q, dict) else {}
                        _ids = _pick_option_ids(_r.get("answer"), _qinfo)
                        if _ids:
                            _resp = ex.save_student_answer_hw(
                                recruit_id, hw_id, _qinfo.get(
                                    "questionId") or _qinfo.get("id"),
                                _ids, course_id)
                            if _resp.get("status") == 200 or _resp.get("code") in (0, 200):
                                _ok_sub += 1
                            elif "参数异常" in str(_resp.get("message", "")):
                                log.warning(
                                    f"   作业[{hw_id}]存题字段被拒: {str(_resp)[:100]}")
                    except Exception as _e:
                        pass
                _fin = ex.submit_homework(recruit_id, hw_id, course_id)
                log.info(
                    f"   作业[{hw_id}] 答题完成({len(_results)}题, 存{_ok_sub}题, 缓存{_n}条, 交卷响应={str(_fin.get('message') or _fin.get('status'))[:30]})")

    def _pick_option_ids(answer_text, qinfo):
        """答案文本/字母 -> 选项ID列表(对question_info的optionVos)"""
        options = qinfo.get("optionVos") or []
        ids = []
        _an = str(answer_text or "").strip()
        if not _an or not options:
            return ids
        # (a) 选项内容匹配
        for o in options:
            _oc = str(o.get("content", "") or "").strip()
            if _oc and (_oc == _an or _an in _oc or _oc in _an):
                ids.append(o.get("id"))
        if ids:
            return ids
        # (b) 字母(A/B-D/ABC) -> 位置映射
        _letters = {ch for ch in _an.upper().replace("-", "").replace(",", "").replace(" ", "")
                    if ch.isalpha()}
        if _letters:
            for i, o in enumerate(options):
                if chr(65 + i) in _letters:
                    ids.append(o.get("id"))
        return ids

    def _process_exam_list():
        try:
            r = ex.get_student_final_exam(recruit_id, course_id)
        except Exception as e:
            log.warning(f"   考试列表拉取异常: {str(e)[:60]}")
            return
        lst = ((r.get("rt") or {}).get("list") or (r.get("data") or {}).get("list")
               or (r.get("data") or {}).get("examList") or [])
        for exam in (lst if isinstance(lst, list) else []):
            if not isinstance(exam, dict):
                continue
            _et = exam.get("examTestId") or exam.get("id")
            _ep = exam.get("examPaperId") or exam.get(
                "paperId") or exam.get("id")
            _kid = exam.get("knowledgeId") or 0
            if not _et or not _ep:
                continue
            try:
                ex.open_exam_paper(_et, _ep, course_id)
                sheet = ex.get_exam_sheet(_et, _ep)
            except Exception as e:
                log.warning(f"   考试[{_et}]开考异常: {str(e)[:60]}")
                continue
            if not sheet:
                continue
            _results = []
            _low = 0
            for qid, ver in sheet:
                try:
                    qinfo = ex.get_exam_question_info(_et, _ep, qid, ver)
                except Exception:
                    continue
                q_text = str(qinfo.get("content", "") or "")
                options = qinfo.get("optionVos") or []
                opt_texts = [str(o.get("content", "")) for o in options]
                _ans, _src = bridge_answer_one(
                    q_text, options=opt_texts, q_type="")
                if _src and ("AI" in str(_src)):
                    _low += 1
                ids = _pick_option_ids(_ans, qinfo)
                if ids and not _collect_only:
                    try:
                        ex.save_exam_answer(course_id, _et, _ep, qid, ids)
                    except Exception:
                        pass
                _results.append(
                    {"q_text": q_text, "answer": _ans, "src": _src, "q_type": ""})
                if _pace >= 1:
                    time.sleep(uniform(1.5, 3.0))
            if not _results:
                continue
            _low_ratio = int(_low * 100 / max(1, len(_results)))
            if _collect_only:
                log.info(f"   考试[{_et}] 只采集模式: 已归档{len(_results)}题(未存卷未交)")
            elif _low_ratio > _rate:
                log.info(f"   考试[{_et}] 低置信度{_low_ratio}%>{_rate}%, 仅存答案不交卷")
            else:
                try:
                    ex.submit_exam_paper(_et, course_id, _ep, _kid)
                    log.info(f"   考试[{_et}] 已交卷({len(_results)}题)")
                except Exception as e:
                    log.warning(f"   考试[{_et}]交卷异常: {str(e)[:60]}")
            _n = bridge_cache_results(_results)
            if _n:
                log.info(f"   考试[{_et}] 缓存{_n}条")

    if _work_on:
        _process_homework_list()
    if _exam_on:
        _process_exam_list()

# ============ Web端课程详情统计(作业/考试清单, 2026-10-17) ============


def web_course_detail_stat(cache, user, course_id: str) -> dict:
    """课程详情统计: 作业/考试清单(供进度页展示)
    数据源: exam_proto.get_student_homework(type=2) + get_student_final_exam
    """
    try:
        from logic.zhihuishu.exam_proto import ZhsExamAPI
    except Exception:
        return {"supported": False}
    courses = _fetch_all_courses(cache, None)
    course = None
    for c in courses:
        if str(c.id) == str(course_id):
            course = c
            break
    if course is None:
        return {"supported": True, "workFinish": None, "workCount": None,
                "examFinish": None, "examCount": None,
                "workList": [], "examList": [],
                "workOngoing": 0, "examOngoing": 0}
    jar = {}
    try:
        for ck in cache.session.cookies:
            if ck.name and ck.value:
                jar[ck.name] = ck.value
    except Exception:
        pass
    ex = ZhsExamAPI(jar)
    recruit_id = str(getattr(course, "recruit_id", "") or course.id)
    cid = str(course.id)
    work_items, exam_items = [], []
    work_fin = work_all = None
    exam_fin = exam_all = None
    # 作业
    try:
        r = ex.get_student_homework(recruit_id, cid, type=2)
        lst = (r.get("rt") or {}).get("list") or (
            r.get("data") or {}).get("list") or []
        if isinstance(lst, list):
            work_all = len(lst)
            work_fin = 0
            for hw in lst:
                if not isinstance(hw, dict):
                    continue
                _st = hw.get("status")
                _done = _st in (2, "2")
                if _done:
                    work_fin += 1
                work_items.append({
                    "name": str(hw.get("name") or hw.get("homeworkName") or hw.get("title") or "作业")[:80],
                    "status": "已完成" if _done else "未完成",
                    "deadline": str(hw.get("endTime") or hw.get("deadline") or ""),
                    "ongoing": (not _done), "score": hw.get("score") or hw.get("finalScore")})
    except Exception:
        pass
    # 期末考试
    try:
        r2 = ex.get_student_final_exam(recruit_id, cid)
        lst2 = (r2.get("rt") or {}).get("list") or (r2.get("data") or {}).get(
            "list") or (r2.get("rt") or {}).get("examList") or []
        if isinstance(lst2, list):
            exam_all = len(lst2)
            exam_fin = 0
            for em in lst2:
                if not isinstance(em, dict):
                    continue
                _st = em.get("status")
                _done = _st in (2, "2", "已参加")
                if _done:
                    exam_fin += 1
                exam_items.append({
                    "name": str(em.get("name") or em.get("examName") or em.get("title") or "考试")[:80],
                    "status": "已完成" if _done else "未参加",
                    "deadline": str(em.get("endTime") or em.get("startTime") or ""),
                    "ongoing": (not _done), "score": em.get("score") or em.get("finalScore")})
    except Exception:
        pass
    return {"supported": True,
            "workFinish": work_fin, "workCount": work_all,
            "examFinish": exam_fin, "examCount": exam_all,
            "workList": work_items, "examList": exam_items,
            "workOngoing": sum(1 for w in work_items if w["ongoing"]),
            "examOngoing": sum(1 for e in exam_items if e["ongoing"])}
