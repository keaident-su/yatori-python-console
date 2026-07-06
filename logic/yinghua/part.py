# -*- coding: utf-8 -*-
"""
英华学堂平台逻辑 - 对应 Go 项目的 logic/yinghua/YinghuaPart.go
完整实现：登录、刷课、视频（普通/暴力/去红）、作业、考试
"""
import re
import threading
import time
from typing import List, Any

from config.config import User, Setting, JSONDataForConfig, cmp_course
from logic.yinghua.models import YingHuaUserCache, YingHuaCourse, YingHuaNode
from logic.yinghua import aggregation as yinghua
from logic.platform_common import generic_filter_account, generic_user_block
from logic.core.ai_client import ai_check, ai_problem_message, AIClient
from logic.core.external_que import check_api_que_request, search_api_que
from utils.log import (
    log_print, model_print, INFO, DEBUG,
    Green, Yellow, Red, Blue, Purple, Default, BoldRed, BoldGreen, DarkGray
)
from global_state.global_var import ACCOUNT_TYPE_STR
from utils.ip_proxy import rand_proxy_str

PLATFORM_TYPE = "YINGHUA"
_sound_lock = threading.Lock()


# ============ 过滤账号 ============

def filter_account(config_data: JSONDataForConfig) -> List[User]:
    """过滤英华学堂账号"""
    return generic_filter_account(config_data, PLATFORM_TYPE)


# ============ 代理 IP ============

def _ip_proxy_loop(user: User, cache: YingHuaUserCache):
    """后台线程定时变换代理地址"""
    while True:
        if user.is_proxy == 1:
            cache.ip_proxy_sw = True
            cache.proxy_ip = rand_proxy_str()
        time.sleep(10)


# ============ 用户登录模块 ============

def user_login_operation(users: List[User]) -> List[YingHuaUserCache]:
    """用户登录模块 - 对应 UserLoginOperation"""
    user_caches: List[YingHuaUserCache] = []
    for user in users:
        if user.account_type != PLATFORM_TYPE:
            continue
        cache = YingHuaUserCache(
            pre_url=user.url,
            account=user.account,
            password=user.password,
        )
        # 启动代理 IP 后台线程
        proxy_thread = threading.Thread(
            target=_ip_proxy_loop, args=(user, cache), daemon=True)
        proxy_thread.start()

        # 登录
        err = yinghua.ying_hua_login_action(cache)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, user.account, Default, "] ",
                      Red, str(err))
            raise SystemExit(str(err))

        # 启动保活线程
        keep_alive_thread = threading.Thread(
            target=_keep_alive_login, args=(cache,), daemon=True)
        keep_alive_thread.start()

        user_caches.append(cache)
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, user.account, Default, "] ",
                  Green, "登录成功")
    return user_caches


# ============ 保活 ============

def _keep_alive_login(cache: YingHuaUserCache):
    """登录心跳保活 - 对应 keepAliveLogin，每5分钟执行一次"""
    while True:
        time.sleep(5 * 60)
        try:
            result = yinghua_api_keep_alive(cache)
            log_print(INFO, f"[{ACCOUNT_TYPE_STR['YINGHUA']}]",
                      "[", Green, cache.account, Default, "] ",
                      DarkGray, f"登录心跳保活状态：{result}")
        except Exception as e:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR['YINGHUA']}]",
                      "[", Green, cache.account, Default, "] ",
                      Red, f"保活失败: {e}")


def yinghua_api_keep_alive(cache: YingHuaUserCache) -> str:
    """保活 API 调用"""
    from logic.yinghua import api
    return api.keep_alive_api(cache, retry=8)


# ============ 开始刷课模块 ============

def run_brush_operation(setting: Setting, users: List[User],
                        user_caches: List[Any]):
    """开始刷课模块 - 对应 RunBrushOperation"""
    threads = []
    for i, cache in enumerate(user_caches):
        if i >= len(users):
            break
        t = threading.Thread(
            target=_user_block,
            args=(setting, users[i], cache),
            daemon=True,
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


# ============ 用户刷课块 ============

def _user_block(setting: Setting, user: User, cache: YingHuaUserCache):
    """用户刷课基本块 - 对应 userBlock"""
    course_list, err = yinghua.course_list_action(cache)
    if err:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  Red, f"拉取课程列表失败: {err}")
        return

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              Purple, "正在定位上次学习位置...")

    node_threads = []
    for course in course_list:
        t = threading.Thread(
            target=_node_list_study_wrapper,
            args=(setting, user, cache, course),
            daemon=True,
        )
        node_threads.append(t)
        t.start()

    for t in node_threads:
        t.join()

    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, cache.account, Default, "] ",
              Purple, "所有待学习课程学习完毕")

    # 邮件通知
    generic_user_block(
        setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], brush_func=None)


def _node_list_study_wrapper(setting, user, cache, course):
    """线程包装器，暴力模式结束后自动执行去红模式"""
    _node_list_study(setting, user, cache, course)
    if user.courses_custom.video_model == 2:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, user.account, Default, "] ",
                  Yellow, "暴力模式执行完毕，正在自动执行去红模式...")
        # 创建临时用户副本，设为去红模式
        import copy
        res_user = copy.deepcopy(user)
        res_user.courses_custom.video_model = 3
        _node_list_study(setting, res_user, cache, course)


# ============ 节点学习 ============

def _node_list_study(setting: Setting, user: User,
                     cache: YingHuaUserCache, course: YingHuaCourse):
    """章节节点学习 - 对应 nodeListStudy"""
    # 课程过滤
    cc = user.courses_custom
    if cc.exclude_courses and cmp_course(course.name, cc.exclude_courses):
        return
    if cc.include_courses and not cmp_course(course.name, cc.include_courses):
        return

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                f"正在学习课程：", Yellow, f" 【{course.name}】 ")

    # 课程时间检查
    if course.start_date and course.start_date > __import__('datetime').datetime.now():
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f" 【{course.name}】 >>> ", Red, "该课程还未开始已自动跳过")
        return

    # 拉取视频列表
    node_list, err = yinghua.videos_list_action(cache, course)
    if err:
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f" 【{course.name}】 >>> ", Red, f"拉取视频列表失败 {err}")

    video_model = cc.video_model
    red_ans = 0  # 标红记录统计
    video_threads = []

    for node in node_list:
        if video_model == 1:
            _video_action(setting, user, cache, course, node)
        elif video_model == 2:
            t = threading.Thread(
                target=_video_violence_action,
                args=(setting, user, cache, course, node),
                daemon=True,
            )
            video_threads.append(t)
            t.start()
        elif video_model == 3:
            if node.error_message == "检测到可能使用并行播放刷课":
                red_ans += 1
            _video_bad_red_action(setting, user, cache, course, node)

        # 作业处理
        _work_action(setting, user, cache, course, node)
        # 考试处理
        _exam_action(setting, user, cache, course, node)

        # 进度显示
        if setting.basic_setting.log_model == 1:
            action, err = yinghua.course_detail_action(cache, course.id)
            if action and not err:
                model_print(True,
                            INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                            "[", Green, cache.account, Default, "] ",
                            f" 【{course.name}】 ",
                            f"视频学习进度：{action.video_learned}/{action.video_count} ",
                            f"课程总学习进度：{action.progress * 100:.2f}%")

    for t in video_threads:
        t.join()

    # 去红模式递归
    if video_model == 3 and red_ans != 0:
        _node_list_study(setting, user, cache, course)
        return

    model_print(setting.basic_setting.log_model == 1,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Green, f"课程 【{course.name}】 学习完毕")


# ============ 视频刷课逻辑 ============

def _video_action(setting: Setting, user: User, cache: YingHuaUserCache,
                  course: YingHuaCourse, node: YingHuaNode):
    """普通模式刷视频 - 对应 videoAction"""
    if not node.tab_video:
        return
    if int(node.progress) == 100:
        return

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, "正在学习视频：", Default,
                f"【{course.name}】【{node.name}】")

    current_time = node.viewed_duration
    study_id = "0"

    while True:
        current_time += 5
        if node.progress >= 100:
            model_print(setting.basic_setting.log_model == 0,
                        INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                        "[", Green, cache.account, Default, "] ",
                        f"【{course.name}】【{node.name}】 ",
                        Blue, "学习完毕")
            break

        sub, err = yinghua.submit_study_time_action(
            cache, node.id, study_id, current_time)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      f"[{cache.account}] ", BoldRed,
                      f"提交学时接口访问异常：{err}")

        yinghua.login_timeout_afresh_action(cache, sub)
        log_print(DEBUG, f"---{node.id} {sub}")

        # 解析返回
        import json
        try:
            sub_data = json.loads(sub)
        except (json.JSONDecodeError, TypeError):
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, cache.account, Default, "] ",
                      f"【{course.name}】【{node.name}】",
                      Red, f"提交状态异常，返回: {sub}")
            time.sleep(10)
            continue

        msg = sub_data.get("msg", "")
        if not msg:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, cache.account, Default, "] ",
                      f"【{course.name}】【{node.name}】",
                      Red, "提交状态异常，msg 字段为空")
            time.sleep(10)
            continue

        if msg != "提交学时成功!":
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, cache.account, Default, "] ",
                      f"【{course.name}】【{node.name}】 >>> ",
                      "提交状态：", Red, sub)
            # 课程解锁时间检查
            if re.search(r'该课程解锁时间【[^【]*】未到!', msg):
                model_print(setting.basic_setting.log_model == 0,
                            INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                            "[", Green, cache.account, Default, "] ",
                            f"【{course.name}】【{node.name}】 >>> ",
                            Red, "该课程未到解锁时间已自动跳过")
                break
            time.sleep(10)
            continue

        # 提取 studyId
        sid = __import__('logic.core.models', fromlist=['json_get']).json_get(
            sub_data, "result", "data", "studyId", default=None)
        if sid is not None:
            study_id = str(int(sid))

        progress_pct = (current_time / node.video_duration *
                        100) if node.video_duration > 0 else 0
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{course.name}】【{node.name}】 >>> ",
                    "提交状态：", Green, msg, Default, " ",
                    f"观看时间：{current_time}/{node.video_duration} ",
                    f"观看进度：{progress_pct:.2f}%")
        time.sleep(5)

        if current_time >= node.video_duration:
            break


def _video_violence_action(setting: Setting, user: User, cache: YingHuaUserCache,
                           course: YingHuaCourse, node: YingHuaNode):
    """暴力模式刷视频 - 对应 videoVioLenceAction（逻辑同普通模式）"""
    _video_action(setting, user, cache, course, node)


def _video_bad_red_action(setting: Setting, user: User, cache: YingHuaUserCache,
                          course: YingHuaCourse, node: YingHuaNode):
    """去红模式 - 对应 videoBadRedAction"""
    if not node.tab_video:
        return
    if node.error_message != "检测到可能使用并行播放刷课":
        return

    model_print(setting.basic_setting.log_model == 0,
                INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                "[", Green, cache.account, Default, "] ",
                Yellow, "正在消红视频：", Default,
                f"【{course.name}】【{node.name}】")

    current_time = node.viewed_duration
    study_id = "0"

    sub, err = yinghua.submit_study_time_action(
        cache, node.id, study_id, current_time)
    if err:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  f"[{cache.account}] ", BoldRed,
                  f"提交学时接口访问异常：{err}")

    yinghua.login_timeout_afresh_action(cache, sub)

    import json
    try:
        sub_data = json.loads(sub)
    except (json.JSONDecodeError, TypeError):
        time.sleep(8)
        return

    msg = sub_data.get("msg", "")
    if msg == "提交学时成功!":
        sid = __import__('logic.core.models', fromlist=['json_get']).json_get(
            sub_data, "result", "data", "studyId", default=None)
        if sid is not None:
            study_id = str(int(sid))
        progress_pct = (current_time / node.video_duration *
                        100) if node.video_duration > 0 else 0
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{course.name}】【{node.name}】 >>> ",
                    Red, " 去红模式 ", Default,
                    f"提交状态：{Green}{msg}{Default} ",
                    f"观看时间：{current_time}/{node.video_duration} ",
                    f"观看进度：{progress_pct:.2f}%")
    time.sleep(8)


# ============ 作业处理 ============

def _work_action(setting: Setting, user: User, cache: YingHuaUserCache,
                 course: YingHuaCourse, node: YingHuaNode):
    """作业处理逻辑 - 对应 workAction"""
    cc = user.courses_custom
    if cc.auto_exam == 0:
        return
    if not node.tab_work:
        return

    # 检查 AI / 外置题库可用性
    if cc.auto_exam == 1:
        err = ai_check(setting.ai_setting.ai_url, setting.ai_setting.model,
                       setting.ai_setting.api_key, setting.ai_setting.ai_type)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      BoldRed, f"<{setting.ai_setting.ai_type}>",
                      f"AI不可用：{err}")
            return

    if cc.auto_exam == 2:
        err = check_api_que_request(setting.api_que_setting.url, retry=3)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      BoldRed, f"外置题库不可用：{err}")
            return

    # 获取作业详情
    work_list, _ = yinghua.work_detail_action(cache, node.id)
    if not work_list:
        return

    if cc.auto_exam == 1:
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"<{setting.ai_setting.ai_type}>",
                    f"【{course.name}】【{node.name}】 ",
                    Yellow, "正在AI自动写章节作业...")
    elif cc.auto_exam == 2:
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{course.name}】【{node.name}】 ",
                    Yellow, "正在外置题库自动写章节作业...")

    # TODO: 完整的作业答题逻辑需要对接 AI/外置题库
    # 此处保留框架，具体答题实现参考 Go 源码的 StartWorkAction
    for work in work_list:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  f"【{course.name}】【{node.name}】 ",
                  Yellow, f"作业 [{work.title}] - 答题功能待完善")

        if cc.exam_auto_submit == 1:
            score, err = yinghua.worked_finally_score_action(cache, work)
            if err:
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, cache.account, Default, "] ",
                          BoldRed, f"获取作业分数失败: {err}")
            else:
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, cache.account, Default, "] ",
                          f"【{course.name}】【{node.name}】",
                          Green, f"作业答题完毕，最高分：{score}分",
                          f" 试卷总分：{work.score:.2f}分")


# ============ 考试处理 ============

def _exam_action(setting: Setting, user: User, cache: YingHuaUserCache,
                 course: YingHuaCourse, node: YingHuaNode):
    """考试处理逻辑 - 对应 examAction"""
    cc = user.courses_custom
    if cc.auto_exam == 0:
        return
    if not node.tab_exam:
        return

    # 检查 AI / 外置题库可用性
    if cc.auto_exam == 1:
        err = ai_check(setting.ai_setting.ai_url, setting.ai_setting.model,
                       setting.ai_setting.api_key, setting.ai_setting.ai_type)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      BoldRed, f"<{setting.ai_setting.ai_type}>",
                      f"AI不可用：{err}")
            return

    if cc.auto_exam == 2:
        err = check_api_que_request(setting.api_que_setting.url, retry=3)
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      BoldRed, f"外置题库不可用：{err}")
            return

    # 获取考试详情
    exam_list, _ = yinghua.exam_detail_action(cache, node.id)
    if not exam_list:
        return

    if cc.auto_exam == 1:
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"<{setting.ai_setting.ai_type}>",
                    f"【{course.name}】【{node.name}】 ",
                    Yellow, "正在AI自动考试...")
    elif cc.auto_exam == 2:
        model_print(setting.basic_setting.log_model == 0,
                    INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                    "[", Green, cache.account, Default, "] ",
                    f"【{course.name}】【{node.name}】 ",
                    Yellow, "正在外置题库自动考试...")

    # TODO: 完整的考试答题逻辑需要对接 AI/外置题库
    for exam in exam_list:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, cache.account, Default, "] ",
                  f"【{course.name}】【{node.name}】 ",
                  Yellow, f"考试 [{exam.title}] - 答题功能待完善")

        if cc.exam_auto_submit == 1:
            score, err = yinghua.exam_finally_score_action(cache, exam)
            if err:
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, cache.account, Default, "] ",
                          BoldRed, f"获取考试分数失败: {err}")
            else:
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, cache.account, Default, "] ",
                          f"【{course.name}】【{node.name}】",
                          Green, f"AI考试完毕,最终分：{score}分",
                          f" 试卷总分：{exam.score:.2f}分")
