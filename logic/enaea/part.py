# -*- coding: utf-8 -*-
"""
学习公社平台逻辑 - 对齐 Go 项目 logic/enaea/EnaeaPart.go + yatori-go-core
完整实现: 登录(passport MD5) → 项目 → 课程(侧边栏) → 视频/icourse → 学时提交
修复记录: 原底部存在重复占位代码(user_login_operation 被重新定义为"登录功能待实现"),
         将上方真正实现覆盖导致登录失效; 且接口域名/路径与Go原版不符, 已全部重写。
"""
import re
import threading
import time
from typing import List, Any, Optional
from urllib.parse import unquote

from config.config import (
    User, Setting, JSONDataForConfig, cmp_course, display_account
)
from logic.enaea.models import (
    EnaeaUserCache, EnaeaProject, EnaeaCourse, EnaeaVideo
)
from logic.enaea import api as enaea_api
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.models import safe_json_parse, json_get
from utils.log import (
    log_print, model_print, INFO, DEBUG,
    Green, Yellow, Red, Blue, Purple, Default, BoldRed, BoldGreen
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "ENAEA"


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


# ============ 登录 ============

def _enaea_login_action(cache: EnaeaUserCache) -> Optional[Exception]:
    """登录聚合 - 对齐Go EnaeaLoginAction"""
    body, _ = enaea_api.login_api(cache, retry=8)
    if not body:
        return Exception("登录响应为空")
    if "用户名或密码错误" in body:
        return Exception("用户名或密码错误")
    if '"success":false' in body:
        return Exception("登录失败(账号或密码错误)")
    if '"success":true' not in body:
        return Exception(f"登录响应异常: {body.strip()[:150]}")
    if not cache.asuss:
        return Exception("登录成功但未获取到ASUSS会话凭证")
    return None


def _login_timeout_afresh(cache: EnaeaUserCache, err) -> bool:
    """失效重登 - 对齐Go LoginTimeoutAfreshAction(仅 nologin 触发)

    :return: 是否已成功重新登录
    """
    err_str = str(err) if err else ""
    if "nologin" not in err_str:
        return False
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              BoldRed, "检测到登录失效，正在进行重新登录...")
    e = _enaea_login_action(cache)
    if e:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  BoldRed, f"失效重登失败: {e}")
        return False
    return True


def user_login_operation(users: List[User]) -> List[EnaeaUserCache]:
    """用户登录模块 - 对齐Go UserLoginOperation(单个账号失败仅跳过, 不影响其他账号)"""
    user_caches = []
    for user in users:
        cache = EnaeaUserCache(
            account=user.account, password=user.password,
            ip_proxy_sw=bool(user.is_proxy),
        )
        err = _enaea_login_action(cache)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(user.account), Default, "] ",
                      Red, str(err))
            continue
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  Green, "登录成功")
        user_caches.append(cache)
    return user_caches


# ============ 刷课 ============

def run_brush_operation(setting: Setting, users: List[User], user_caches: List[Any]):
    threads = []
    for i, cache in enumerate(user_caches):
        # 将 cache 匹配回对应 user(登录失败的账号已被过滤)
        matched = None
        for u in users:
            if u.account == cache.account:
                matched = u
                break
        if matched is None:
            continue
        t = threading.Thread(target=_user_block, args=(
            setting, matched, cache), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def _user_block(setting: Setting, user: User, cache: EnaeaUserCache):
    """项目→课程→视频三层刷课 - 对齐Go userBlock"""
    # 拉取项目列表
    proj_body, _ = enaea_api.project_list_api(cache, retry=8)
    proj_data = safe_json_parse(proj_body)
    projects = []
    for item in json_get(proj_data or {}, "result", "list", default=[]) or []:
        if not isinstance(item, dict):
            continue
        try:
            circle_id = str(int(item.get("circleId", 0) or 0))
        except (ValueError, TypeError):
            circle_id = str(item.get("circleId", ""))
        projects.append(EnaeaProject(
            circle_id=circle_id,
            circle_name=str(item.get("circleName", "") or ""),
            cluster_name=str(item.get("clusterName", "") or ""),
            start_end_time=str(item.get("startEndTime", "") or ""),
        ))

    cc = user.courses_custom
    # 项目过滤规则(支持 "项目名-->课程名" 格式)
    exclude_projects, include_projects = [], []
    exclude_courses_sub, include_courses_sub = [], []
    for c in cc.exclude_courses:
        parts = c.split("-->")
        exclude_projects.append(parts[0])
        if len(parts) >= 2:
            exclude_courses_sub.append(parts[1])
    for c in cc.include_courses:
        parts = c.split("-->")
        include_projects.append(parts[0])
        if len(parts) >= 2:
            include_courses_sub.append(parts[1])

    for project in projects:
        if exclude_projects and cmp_course(project.cluster_name, exclude_projects):
            continue
        if include_projects and not cmp_course(project.cluster_name, include_projects):
            continue

        # 拉取项目下课程(侧边栏菜单→逐 syllabus 拉课程)
        courses = _pull_courses(cache, project.circle_id)

        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  Purple, "正在学习项目 ", f"【{project.cluster_name}】")

        for course in courses:
            if exclude_courses_sub and cmp_course(course.title_tag, exclude_courses_sub):
                continue
            if include_courses_sub and not cmp_course(course.title_tag, include_courses_sub):
                continue
            _node_list_study(setting, user, cache, course)

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              Purple, "所有待学习课程学习完毕")
    generic_user_block(
        setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], brush_func=None)


def _pull_courses(cache: EnaeaUserCache, circle_id: str) -> List[EnaeaCourse]:
    """从项目页侧边栏提取课程菜单并逐条拉取课程 - 对齐Go CourseListAction"""
    html, _ = enaea_api.pull_course_html_api(cache, circle_id, retry=8)
    if not html:
        return []
    html = html.replace("&amp;", "&")
    pattern = (
        r'<a title="([^"]*)" href="circleIndexRedirect\.do\?action=toNewMyClass'
        r'&type=course([^&]{0,50})&circleId=' + re.escape(circle_id) +
        r'&syllabusId=([^&]*?)&isRequired=[^&]*&studentProgress=[\d]+">')
    courses: List[EnaeaCourse] = []
    for m in re.finditer(pattern, html):
        title_tag, module, syllabus_id = m.group(1), m.group(2), m.group(3)
        body, _ = enaea_api.course_list_api(
            cache, circle_id, syllabus_id, module, retry=8)
        data = safe_json_parse(body)
        for item in json_get(data or {}, "result", "list", default=[]) or []:
            if not isinstance(item, dict):
                continue
            dto = item.get("studyCenterDTO") or {}
            if not isinstance(dto, dict):
                dto = {}
            try:
                progress = float(str(dto.get("studyProgress", 0) or 0))
            except (ValueError, TypeError):
                progress = 0.0
            try:
                course_id = str(int(dto.get("courseId", 0) or 0))
            except (ValueError, TypeError):
                course_id = str(dto.get("courseId", ""))
            remark = str(item.get("remark", "") or "")
            courses.append(EnaeaCourse(
                title_tag=title_tag,
                course_title=str(dto.get("courseTitle", "") or "") or remark,
                remark=remark,
                course_id=course_id,
                circle_id=circle_id,
                syllabus_id=syllabus_id,
                study_progress=progress,
                course_content_type=str(
                    dto.get("coursecontentType", "") or ""),
                course_external_type=str(
                    dto.get("courseExternalType", "") or ""),
                course_content_link=str(
                    dto.get("courseContentLink", "") or ""),
            ))
    return courses


def _node_list_study(setting: Setting, user: User, cache: EnaeaUserCache,
                     course: EnaeaCourse):
    """课程节点学习 - 对齐Go nodeListStudy"""
    videos = _pull_videos(cache, course)

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, display_account(cache.account), Default, "] ",
                "正在学习课程：", Yellow,
                f"【{course.title_tag}】【{course.course_title}】")

    for video in videos:
        _video_action(setting, user, cache, video)

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, display_account(cache.account), Default, "] ",
                Green, "课程", f" 【{course.title_tag}】",
                f"【{course.course_title}】 ", "学习完毕")


def _parse_video_length(length_text) -> int:
    """将 "HH:MM:SS" 解析为秒数(容错)"""
    try:
        parts = str(length_text or "").split(":")
        hours = int(parts[0]) if len(parts) > 0 and parts[0] else 0
        minutes = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        seconds = int(parts[2]) if len(parts) > 2 and parts[2] else 0
        return hours * 3600 + minutes * 60 + seconds
    except (ValueError, TypeError, IndexError):
        return 0


def _pull_videos(cache: EnaeaUserCache, course: EnaeaCourse) -> List[EnaeaVideo]:
    """拉取课程视频列表 - 对齐Go VideoListAction(video / external_link）"""
    videos: List[EnaeaVideo] = []
    if course.course_content_type == "video":
        body, _ = enaea_api.video_list_api(
            cache, course.circle_id, course.course_id, retry=8)
        data = safe_json_parse(body)
        for item in json_get(data or {}, "result", "list", default=[]) or []:
            if not isinstance(item, dict):
                continue
            try:
                progress = float(str(item.get("studyProgress", 0) or 0))
            except (ValueError, TypeError):
                progress = 0.0
            content_str = str(item.get("courseContentStr", "") or "")
            try:
                content_str = unquote(content_str)
            except Exception:
                pass
            try:
                vid_id = str(int(item.get("id", 0) or 0))
            except (ValueError, TypeError):
                vid_id = str(item.get("id", ""))
            videos.append(EnaeaVideo(
                id=vid_id,
                title_tag=course.title_tag,
                course_name=course.remark or course.course_title,
                course_content_str=content_str,
                file_name=str(item.get("filename", "") or ""),
                study_progress=progress,
                course_id=course.course_id,
                circle_id=course.circle_id,
                video_length=_parse_video_length(item.get("length")),
            ))
    elif course.course_content_type == "external_link" \
            and course.course_external_type == "icourse":
        # icourse外部课程: 从页面变量里提取真实课程与节点ID
        html, _ = enaea_api.pull_icourse_html_api(
            cache, course.circle_id, course.course_id, retry=8)
        if html:
            def _var(name: str) -> str:
                mm = re.search(r'var\s+' + name + r'\s*=\s*(\d+);', html)
                return mm.group(1) if mm else ""

            videos.append(EnaeaVideo(
                id=_var("currPlayCoursecontentId"),
                title_tag=course.title_tag,
                course_name=course.remark or course.course_title,
                course_content_str="icourse外部课程",
                study_progress=0.0,
                course_id=_var("courseId") or course.course_id,
                circle_id=_var("jsp_circleId") or course.circle_id,
            ))
    return videos


def _statistic_action(cache: EnaeaUserCache, video: EnaeaVideo) -> Optional[str]:
    """观看前统计初始化(获取SCFUCKP凭证) - 对齐Go StatisticTicForCCVideAction"""
    # 每个视频独立凭证, 先清空避免沿用上个视频的
    cache.scfuckp_key, cache.scfuckp_value = "", ""
    body, key, value, _ = enaea_api.statistic_tic_cc_video_api(
        cache, video.course_id, video.id, video.circle_id, retry=8)
    data = safe_json_parse(body)
    if data is None:
        return f"统计接口响应解析失败: {(body or '')[:120]}"
    if data.get("success") is not True:
        return str(data.get("message", data))
    if key:
        video.scfuckp_key, video.scfuckp_value = key, value
        cache.scfuckp_key, cache.scfuckp_value = key, value
    return None


def _submit_with_parse(cache: EnaeaUserCache, video: EnaeaVideo,
                       brutal: bool, study_mins: int = 1,
                       retry: int = 8):
    """提交学时并解析响应(对齐Go SubmitStudyTimeAction)

    :param study_mins: 暴力模式下本周期的学时(分钟, 由倍速换算得出)
    :return: (异常信息 or None, 是否需重登)
    """
    if brutal:
        # 暴力模式: 按倍速提交对应的整分钟学时(如16倍速时6/7分钟交替, 平均精确)
        body, _ = enaea_api.submit_study_time_fast_api(
            cache, video.circle_id, video.id, max(1, int(study_mins)),
            retry=retry)
    else:
        # 普通模式: 提交当前时间戳
        body, _ = enaea_api.submit_study_time_api(
            cache, video.circle_id, video.id, int(time.time() * 1000),
            retry=retry)
    data = safe_json_parse(body)
    if data is None:
        return f"提交学时响应解析失败: {(body or '')[:120]}", False
    if data.get("success") is not True:
        msg = str(data.get("message", data))
        if msg == "nologin":
            return "nologin", True
        if msg == "request frequently!":
            # 提交过于频繁(对齐Go: 静默忽略)
            return None, False
        return msg, False
    if data.get("progress") is None:
        return f"提交学时时服务器端返回消息异常: {(body or '')[:150]}", False
    try:
        video.study_progress = float(data.get("progress"))
    except (ValueError, TypeError):
        pass
    return None, False


def _video_action(setting: Setting, user: User, cache: EnaeaUserCache,
                  node: EnaeaVideo):
    """刷视频 - 对齐Go videoAction"""
    cc = user.courses_custom
    if cc.video_model == 0:
        return

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, display_account(cache.account), Default, "] ",
                Yellow, "正在学习视频：", Default,
                f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】 ")

    # 观看前统计初始化(告知后端开始计时)
    stat_err = _statistic_action(cache, node)
    if stat_err:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】 ",
                  BoldRed, "提交学时接口访问异常，返回信息：", stat_err)

    brutal = (cc.video_model != 1)
    # 暴力模式倍速(coursesCustom.bruteSpeed): 每25秒周期记入 speed×25 秒学时
    # 实测结论(2026-09-20): 服务端单次提交封顶5分钟(提交60分钟也只记~300秒),
    # 且提交间隔<25秒会被拒(request frequently!), 故有效倍速上限 = 300/25 = 12x
    # 口径: 2.4倍=周期记60秒(1分钟); 12倍=周期5分钟(服务端上限); >12按服务端上限执行
    speed = 2.4
    try:
        speed = float(getattr(cc, "brute_speed", 2.4) or 2.4)
    except (ValueError, TypeError):
        speed = 2.4
    if speed < 2.4:
        speed = 2.4
    elif speed > 144:
        speed = 144.0
    # 服务端单次封顶5分钟 + 25秒间隔 => 有效倍速不超过12
    effective_speed = min(speed, 12.0)
    acc = 0.0  # 分钟累加器: 保证平均倍速精确(整数提交, 避免服务端浮点解析风险)
    if brutal and node.study_progress < 100:
        if speed > 12.0:
            speed_tip = (f"暴力模式倍速: {speed:g}x -> 服务端单次封顶5分钟/次, "
                         f"实际按12x执行 (每25秒记入5.0分钟学时)")
        else:
            speed_tip = (f"暴力模式倍速: {speed:g}x "
                         f"(每25秒周期记入约{effective_speed * 25 / 60:.2f}分钟学时)")
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】 ",
                  Yellow, speed_tip)
    while True:
        if node.study_progress >= 100:
            model_print(setting.basic_setting.log_model == 0,
                        INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                        "[", Green, display_account(
                            cache.account), Default, "] ",
                        f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】",
                        Blue, " 学习完毕")
            break

        if brutal:
            acc += effective_speed * 25.0 / 60.0
            cycle_mins = max(1, int(acc))
            acc -= cycle_mins
        else:
            cycle_mins = 0
        err_msg, need_relogin = _submit_with_parse(
            cache, node, brutal, cycle_mins)
        if need_relogin:
            # 会话失效: 重登(对齐Go LoginTimeoutAfreshAction)
            if _login_timeout_afresh(cache, "nologin"):
                continue
            break
        if err_msg:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】 ",
                      BoldRed, "提交学时接口访问异常，返回信息：", err_msg)
        else:
            cycle_tip = f"(本周期记入{cycle_mins}分钟) " if brutal else ""
            model_print(setting.basic_setting.log_model == 0,
                        INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                        "[", Green, display_account(
                            cache.account), Default, "] ",
                        f" 【{node.title_tag}】【{node.course_name}】【{node.course_content_str}】  >>> ",
                        "提交状态：成功 ", cycle_tip,
                        f"观看进度：{node.study_progress:.2f}%")

        time.sleep(25)  # 每隔25s进行一次学时提交(对齐Go)
        if node.study_progress >= 100:
            break
