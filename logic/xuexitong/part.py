# -*- coding: utf-8 -*-
"""
学习通平台逻辑 - 完整重写对齐 Go 原版
对应 Go 项目的 logic/xuexitong/XueXiTongPart.go
完整实现：AES登录、课程解析(courseSquareUrl)、章节/卡片/视频提交
Go流程: ChapterFetchCardsAction → parseIframeData → ParsePointDto →
        PageMobileChapterCardAction → AttachmentsDetection → Execute*
"""
import concurrent.futures as _futures
import copy
import json
import queue as _queue_mod
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
from logic.xuexitong import captcha as xxt_captcha
from logic.platform_common import (generic_filter_account, generic_user_block,
                                   send_user_event_notice, run_stats_bump)
from logic.core.models import safe_json_parse, json_get
from logic.core.parallel import NODE_START_INTERVAL, LOGIN_WORKERS
from logic.core.cpu_pool import cpu_map
from logic.core.parse_utils import parse_iframe_data as _parse_iframe_light
from utils.log import (
    log_print, model_print, INFO, DEBUG,
    Green, Yellow, Red, Blue, Purple, Default, BoldRed, BoldGreen, DarkGray
)
from global_state.global_var import ACCOUNT_TYPE_STR

PLATFORM_TYPE = "XUEXITONG"

_users_lock = threading.Lock()
_model3_caches: Dict[str, List[XueXiTUserCache]] = {}

# 多任务点登录池队列(账号级, 跨课程共享): 存放可用session索引，
# 对齐 Go chapterStudy 中 queue := make(chan int, len(model3Caches)) 的行为
_model3_pool_queues: Dict[str, Any] = {}
_model3_pool_queues_guard = threading.Lock()

# 活跃课程计数(账号级): 用于登录池公平分配，
# 限制单个课程同时占用的session数(池大小/活跃课程数)，
# 避免先到达的课程独占整个登录池导致其他课程的任务点看起来串行
_active_course_count: Dict[str, int] = {}
_active_course_guard = threading.Lock()

# 无限制并发模式下，防止同一作业/考试被多个节点线程重复处理
# (重复处理会因 enc 失效产生 "enc error")
_work_processed: set = set()
_work_processed_guard = threading.Lock()

# 全局考试串行锁: 多个课程/账号的考试必须一个一个按顺序处理，
# 同一时间只能有一个考试在答题/交卷
_exam_serial_lock = threading.Lock()

# 多任务点无限制模式：按账号累计登录次数并实时显示状态
_account_login_counts: Dict[str, int] = {}
_account_login_guard = threading.Lock()


def _record_node_login(account: str, ok: bool, tag: str = ""):
    """记录并显示每个账号的登录次数状态（多任务点无限制模式）"""
    with _account_login_guard:
        _account_login_counts[account] = _account_login_counts.get(
            account, 0) + 1
        n = _account_login_counts[account]
    if ok:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(account), Default, "] ",
                  Yellow, f"多任务点登录状态: 该账号累计登录{n}次",
                  Default, f"({tag}登录成功)" if tag else "(登录成功)")
    else:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(account), Default, "] ",
                  Red, f"多任务点登录状态: 该账号累计登录{n}次",
                  Default, f"({tag}登录失败)" if tag else "(登录失败)")


def filter_account(config_data: JSONDataForConfig) -> List[User]:
    return generic_filter_account(config_data, PLATFORM_TYPE)


# ============ 设备特征码 ============

_DEVICE_FLAG_AES_KEY = "QrCbNY@MuK1X8HGw"


def _generate_device_flag() -> str:
    """动态生成设备特征码 - 对齐学习通APP逆向算法
    Base64(AES-128-ECB-PKCS5(随机UUID, key="QrCbNY@MuK1X8HGw"))
    """
    import base64 as _b64
    import uuid as _uuid
    raw = str(_uuid.uuid4()).encode("utf-8")
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        cipher = AES.new(_DEVICE_FLAG_AES_KEY.encode("utf-8"), AES.MODE_ECB)
        return _b64.b64encode(
            cipher.encrypt(pad(raw, AES.block_size))).decode()
    except ImportError:
        return _b64.b64encode(raw).decode()


# ============ AI答案匹配 ============

def _strip_option_prefix(opt: str) -> str:
    """去除选项的字母前缀(如"C三相笼式异步电机"→"三相笼式异步电机")"""
    opt = (opt or "").strip()
    m = re.match(r'^[A-Za-zＡ-Ｚ][\.、．:：\s]*', opt)
    return opt[m.end():].strip() if m else opt


# 判断题同义词(对/错)
_JUDGE_SYNONYMS = {
    "对": ("对", "正确", "√", "true", "True", "TRUE"),
    "错": ("错", "错误", "×", "false", "False", "FALSE"),
}


def _normalize_ai_answer_candidates(answer: str) -> List[str]:
    """把AI答案转为候选文本列表
    兼容: JSON数组(["内容"] / [{"name":"内容"}])、逗号/顿号分隔文本、纯文本
    """
    if not answer:
        return []
    text = (answer or "").strip()
    # JSON数组解析(兼容内置AI直接返回的 [{"name":"..."}] 原始串)
    try:
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        json_part = m.group() if m else text
        parsed = json.loads(json_part)
        if isinstance(parsed, list):
            cands = []
            for p in parsed:
                if isinstance(p, dict):
                    for k in ("name", "value", "text", "content",
                              "answer", "option", "title", "key"):
                        v = p.get(k)
                        if isinstance(v, str) and v.strip():
                            cands.append(v.strip())
                            break
                    else:
                        for v in p.values():
                            if isinstance(v, str) and v.strip():
                                cands.append(v.strip())
                                break
                elif isinstance(p, str) and p.strip():
                    cands.append(p.strip())
                elif isinstance(p, (int, float)):
                    cands.append(str(p))
            if cands:
                return cands
    except (ValueError, TypeError):
        pass
    # 纯文本: 按常见分隔符切分(#为AXE题库多选答案分隔符)
    cands = []
    for frag in re.split(r'[,，;；、|#]', text):
        frag = frag.strip().strip('"\'[]{} ')
        if frag and frag not in cands:
            cands.append(frag)
    # 连续字母答案(如"AC")拆成单字母候选
    expanded = []
    for c in cands:
        if re.fullmatch(r'[A-Ha-h]{2,}', c):
            for ch in c:
                if ch not in expanded:
                    expanded.append(ch.upper())
        elif c not in expanded:
            expanded.append(c)
    cands = expanded
    return cands or [text.strip().strip('"\'[]{} ')]


def _extract_plain_letter(answer: str) -> str:
    """从答案中提取纯选项字母(兜底): C / C.xxx / 选项C / 答案:C / 选C"""
    if not answer:
        return ""
    clean = (answer or "").strip().strip('"\'[]{} ')
    if re.fullmatch(r'[A-Ha-h]', clean):
        return clean.upper()
    m = re.match(r'^\s*([A-Ha-h])\s*[.、．:：]', clean)
    if m:
        return m.group(1).upper()
    m = re.search(r'(?:选项|答案|选)\s*[:：]?\s*([A-Ha-h])', clean)
    if m:
        return m.group(1).upper()
    return ""


def _normalize_judge_answer(answer: str) -> str:
    """把判断题答案文本归一化为 true/false - 对齐 Go AnswerFixedPattern"""
    judge_answer = (answer or "").strip()
    judge_answer = (judge_answer.replace("对", "正确").replace("√", "正确")
                    .replace("×", "错误").replace("true", "正确")
                    .replace("false", "错误"))
    if judge_answer == "正确" or "正确" in judge_answer or "对" in judge_answer:
        return "true"
    if judge_answer == "错误" or "错误" in judge_answer or "错" in judge_answer:
        return "false"
    return "true"  # 默认


def _match_answer_to_options(answer: str, options: List[str],
                             multi: bool = False) -> str:
    """把AI答案匹配到选项字母 - 对齐 Go SimilarityArraySelect
    选项元素可能带字母前缀(如"C三相笼式异步电机")，匹配时忽略前缀。
    支持: 单字母答案(直接按字母匹配)、判断题同义词(正确/对→A，错误/错→B)、
    JSON数组答案([{"name":"..."}] / ["内容"])。
    多选题返回多个字母拼接(如"AC")，单选返回单个字母；
    精确匹配失败时用相似度(阈值0.5)兜底取最高分选项。
    """
    if not answer or not options:
        return ""
    candidates = _normalize_ai_answer_candidates(answer)
    if not candidates:
        return ""
    matched = []
    for i, opt in enumerate(options):
        opt_clean = _strip_option_prefix(opt)
        if not opt_clean:
            continue
        # 选项字母优先取自带前缀(如"C三相笼式异步电机"→C)，否则按序号
        lm = re.match(r'^([A-Za-z])', (opt or '').strip())
        letter = lm.group(1).upper() if lm else chr(65 + i)
        for cand in candidates:
            if not cand:
                continue
            hit = False
            if len(cand) == 1 and cand.isascii() and cand.isalpha():
                # 单字母答案(仅ASCII字母): 直接按字母匹配
                hit = (cand.upper() == letter)
            else:
                hit = (cand in opt_clean or opt_clean in cand)
                # 判断题同义词: 对/正确/√ 与 错/错误/×
                if not hit:
                    for judge_key, syns in _JUDGE_SYNONYMS.items():
                        if judge_key not in opt_clean and opt_clean not in judge_key:
                            continue
                        if cand in syns:
                            hit = True
                            break
            if hit:
                if letter not in matched:
                    matched.append(letter)
                break
    if matched:
        return "".join(matched) if multi else matched[0]
    # 相似度兜底(阈值0.5): 对齐 Go SimilarityArraySelect 择优思想
    best_letter, best_score = "", 0.0
    for i, opt in enumerate(options):
        opt_clean = _strip_option_prefix(opt)
        if not opt_clean:
            continue
        lm = re.match(r'^([A-Za-z])', (opt or '').strip())
        letter = lm.group(1).upper() if lm else chr(65 + i)
        for cand in candidates:
            score = _similarity(cand, opt_clean)
            if score < 0.5 and len(cand) > 2 and (
                    cand in opt_clean or opt_clean in cand):
                score = max(score, 0.6)
            if score > best_score:
                best_score = score
                best_letter = letter
    return best_letter if best_score >= 0.5 else ""


# ============ 登录 ============

def _login_action(cache: XueXiTUserCache) -> Optional[Exception]:
    """登录动作 - 对应 Go 的 XueXiTLoginAction / XueXiTCookieLoginAction
    登录失败时(常见于频繁登录触发的临时风控)等待后重试一次
    """
    if len(cache.password) >= 50:
        cache.is_cookie_login = True
        cache.cookie_str = cache.password
        xxt_api.cookie_login_set(cache)
        uid = cache.cookie_dict.get("UID", cache.cookie_dict.get("_uid", ""))
        if uid:
            cache.uid = uid
        return None

    def _do_login():
        body, _ = xxt_api.login_api(cache, retry=8)
        if not body:
            return None, "登录响应为空"
        data = safe_json_parse(body)
        if data and data.get("status") is True:
            cache.uid = cache.cookie_dict.get(
                "UID", cache.cookie_dict.get("_uid", ""))
            return None, ""
        msg = data.get("msg2", data.get("msg1", "")) if data else ""
        return body, (msg or f"未知错误(原始响应:{body[:200]})")

    body, err_msg = _do_login()
    if err_msg and ("未知错误" in err_msg or "频繁" in err_msg
                    or "验证码" in err_msg):
        # 临时风控/异常响应: 等待后重试一次(风控通常短时解除)
        import time as _t
        _t.sleep(20)
        body, err_msg2 = _do_login()
        if not err_msg2:
            return None
        return Exception(f"登录失败(重试后仍失败): {err_msg2}")
    if err_msg:
        return Exception(f"登录失败: {err_msg}")
    return None


def user_login_operation(users: List[User]) -> List[XueXiTUserCache]:
    """登录模块（多核优化：多账号并行登录，I/O密集可超配线程）"""
    targets = [u for u in users if u.account_type == PLATFORM_TYPE]
    user_caches: List[XueXiTUserCache] = []
    if not targets:
        return user_caches

    def _login_one(u: User):
        cache = XueXiTUserCache(account=u.account, password=u.password)
        # 设备特征码: 配置了deviceFlag就用配置的，否则每次登录前动态生成
        # (每个账号对应的当前设备特征码打印到日志)
        cc_cfg = u.courses_custom
        cfg_flag = (getattr(cc_cfg, "device_flag", "") or "").strip()
        if cfg_flag:
            cache.device_flag = cfg_flag
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      Purple, f"设备特征码(来自配置): {cache.device_flag}")
        else:
            cache.device_flag = _generate_device_flag()
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      Yellow, f"未配置deviceFlag(缺乏设备特征码，可能会无法完成某些课程的考试)，"
                      f"已动态生成: {cache.device_flag}")
        return cache, _login_action(cache)

    workers = max(1, min(len(targets), LOGIN_WORKERS))
    if workers == 1 or len(targets) == 1:
        results = [_login_one(u) for u in targets]
    else:
        # 并行登录，map 保持原配置顺序，日志输出顺序不变
        with _futures.ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_login_one, targets))

    for cache, err in results:
        if err:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, cache.account, Default, "] ", Red, str(err))
            continue
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[" + cache.account + "] ", Green, "登录成功")
        user_caches.append(cache)
    return user_caches


# ============ 刷课 ============

def run_brush_operation(setting: Setting, users: List[User], user_caches: List[Any]):
    # 初始化多答题源引擎(顺序调用/失败自动回退/本地题库缓存)
    from logic.core.answer_engine import configure_answer_engine
    configure_answer_engine(setting)
    # 解除多个独立账号同时进行的数量限制：所有账号同时并行执行
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              Yellow, f"共{len(user_caches)}个账号同时并行执行(独立账号数量限制已解除)")
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
        # 对齐 Go UserBlock: videoModel=3 时建立多任务点登录池
        # cxNode>0 → 预登录cxNode次形成池(同时任务点数量)
        # cxNode==-1 → 无限制模式(不预登录, 每个节点独立relogin)
        # cxNode==0/未配置 → 默认3次(对齐Go num:=3)
        node_num = 3
        if cc.cx_node is not None and cc.cx_node != 0:
            node_num = cc.cx_node
        if cache.account not in _model3_caches:
            _model3_caches[cache.account] = []
        if node_num < 0:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      Yellow, "警告，当前账号使用的是多任务点无限制模式，该账号将会同时登录非常多的次数，这将会小概率性封号(一般封十几分钟)或封IP，单个账号使用基本没有事，多个账号请酌情使用")
        else:
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      Yellow, f"警告，当前账号使用的是多任务点模式，该账号将会同时登录{node_num}次，这将会小概率性封号(一般封十几分钟)或封IP，单个账号使用基本没有事，多个账号请酌情使用")
            # 预登录池: 登录node_num个独立session副本 - 对齐 Go for i := 0; i < num; i++
            pool = _model3_caches[cache.account]
            pool.clear()  # 防止同一次运行内重复累积
            for i in range(node_num):
                pool_cache = copy.deepcopy(cache)
                rerr = xxt_api.relogin(pool_cache)
                _record_node_login(cache.account, rerr is None, "登录池")
                pool.append(pool_cache)
                log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                          "[", Green, display_account(
                              cache.account), Default, "] ",
                          "当前多任务点账户队列累计", Yellow,
                          f"{i+1}/{node_num}")
                time.sleep(1)  # 隔一下，避免登录太快
        # 初始化登录池队列(账号级, 跨课程共享): 放入所有session索引
        with _model3_pool_queues_guard:
            if cache.account not in _model3_pool_queues:
                _model3_pool_queues[cache.account] = _queue_mod.Queue()
        if node_num >= 0:
            q = _model3_pool_queues[cache.account]
            for i in range(len(_model3_caches[cache.account])):
                q.put(i)

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
    # 对齐Go courseStudy: 任务点完成度仅门控章节学习，作业和考试始终执行
    # (否则课程任务点100%后考试将永远不被处理，导致多考试课程只完成一门)
    if course.job_rate < 100 and course.state != 1:
        _chapter_study(setting, user, cache, course)
    else:
        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                  "[", Green, display_account(cache.account), Default, "] ",
                  "[", course.course_name, "] ", Blue,
                  "该课程任务点已完成或课程已结束，跳过章节学习(继续处理作业/考试)；"
                  "如任务点中个别章测/作业显示\"待批阅\"，表示已提交、等待老师批阅，无需重复操作")
    # 写课程的作业和考试
    _write_course_work_and_exam(setting, user, cache, course)
    # 增加学习次数/学习时长(课程任务点全部完成后执行)
    _add_study_count_action(setting, user, cache, course)
    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
              "[", Green, display_account(cache.account), Default, "] ",
              "[", course.course_name, "] ", Purple, "课程学习完毕")
    # 按事件实时通知: 课程完成(邮件/ShowDoc双通道, 不响提示音; 失败不影响主流程)
    run_stats_bump(ACCOUNT_TYPE_STR[PLATFORM_TYPE], user.account, "course")
    send_user_event_notice(setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE],
                           f"课程【{course.course_name}】已完成")


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
    if cc.video_model == 3:
        # Model 3 多任务点模式 - 对齐 Go chapterStudy:
        # cxNode==-1 → 无限制模式(每个节点独立 relogin 并发执行)
        # cxNode>=0(含0/未配置) → 登录池模式(从预登录池阻塞取session,
        #                          同时最多cxNode个节点并发)
        unlimited = (cc.cx_node is not None and cc.cx_node < 0)
        pool = None
        pool_q = None
        course_sem = None
        if not unlimited:
            pool = _model3_caches.get(cache.account, [])
            pool_q = _model3_pool_queues.get(cache.account)
            # 公平分配: 单课程同时占用session上限 = 池大小/活跃课程数(至少1)
            # 避免先到达的课程独占登录池, 导致其他课程任务点看似串行
            with _active_course_guard:
                _active_course_count[cache.account] = (
                    _active_course_count.get(cache.account, 0) + 1)
                active_n = _active_course_count[cache.account]
            if pool:
                course_sem = threading.BoundedSemaphore(
                    max(1, len(pool) // max(active_n, 1)))
        node_threads = []
        progress_lock = threading.Lock()
        progress_state = {"done": 0}
        for index, node_id in enumerate(nodes):
            node_str = str(node_id)
            if node_str in finished_map:
                total, finished = finished_map[node_str]
                if total >= 0 and total == finished:
                    # 已完成节点(2026-09-21 需求): 测验/作业类节点明确告知用户——
                    # 页面可能显示"待批阅", 实际已提交完成, 无需重复操作
                    _km = knowledge_map.get(
                        node_id) or knowledge_map.get(node_str) or {}
                    _nname = str(_km.get("name", "")) if isinstance(
                        _km, dict) else ""
                    if any(k in _nname for k in
                           ("测验", "测试", "小测", "练习", "作业", "考试", "检测")):
                        log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                                  "[", Green, display_account(
                                      cache.account), Default, "] ",
                                  "[", course.course_name, "] ", Green,
                                  f"[{_nname}] 该任务点已完成"
                                  f"（若页面显示\"待批阅\"，表示已提交、等待老师批阅，无需重复操作），已自动跳过")
                    with progress_lock:
                        progress_state["done"] += 1
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
                    with progress_lock:
                        progress_state["done"] += 1
                    continue

            def _run_node_session(sess_cache, idx, nid, si=None):
                try:
                    _node_run(setting, user, sess_cache,
                              course, nodes, idx, nid, knowledge_map)
                except Exception as e:
                    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                              "[", Green, display_account(
                                  cache.account), Default, "] ",
                              "[", course.course_name, "] ", BoldRed,
                              f"节点{nid}运行异常: {e}")
                finally:
                    # 用完放回池队列 - 对齐 Go defer queue <- idx
                    if si is not None and pool_q is not None:
                        pool_q.put(si)
                    # 实时显示任务点进度
                    with progress_lock:
                        progress_state["done"] += 1
                        done = progress_state["done"]
                    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                              "[", Green, display_account(
                                  cache.account), Default, "] ",
                              "[", course.course_name, "] ",
                              Yellow, f"任务点进度: {done}/{len(nodes)}")

            if unlimited:
                # 无限制模式：每个节点独立 relogin 后并发执行（对齐 Go CxNode=-1）
                def _run_unlimited(idx=index, nid=node_id):
                    res_cache = copy.deepcopy(cache)
                    rerr = xxt_api.relogin(res_cache)
                    _record_node_login(cache.account, rerr is None, f"节点{nid}")
                    _run_node_session(res_cache, idx, nid)
                t = threading.Thread(target=_run_unlimited, daemon=True)
                node_threads.append(t)
                t.start()
                # 多核优化：启动间隔随 CPU 核心数缩短（保留最小节流防风控）
                time.sleep(NODE_START_INTERVAL)
            else:
                # 登录池模式：阻塞等待空闲session - 对齐 Go idx := <-queue
                # (池为空时队列未初始化, 回退为该节点独立relogin)
                if pool_q is None or not pool:
                    def _run_fallback(idx=index, nid=node_id):
                        res_cache = copy.deepcopy(cache)
                        rerr = xxt_api.relogin(res_cache)
                        _record_node_login(cache.account, rerr is None,
                                           f"节点{nid}")
                        _run_node_session(res_cache, idx, nid)
                    t = threading.Thread(target=_run_fallback, daemon=True)
                    node_threads.append(t)
                    t.start()
                    time.sleep(NODE_START_INTERVAL)
                    continue
                # 课程级并发上限(公平分配): 占满则等待本课程的节点完成
                if course_sem is not None:
                    course_sem.acquire()
                sess_idx = pool_q.get()  # 阻塞直到有空闲session

                def _run_pool(idx=index, nid=node_id, si=sess_idx):
                    try:
                        _run_node_session(pool[si], idx, nid, si)
                    finally:
                        if course_sem is not None:
                            course_sem.release()
                t = threading.Thread(target=_run_pool, daemon=True)
                node_threads.append(t)
                t.start()

        if course_sem is not None:
            with _active_course_guard:
                _active_course_count[cache.account] = max(
                    0, _active_course_count.get(cache.account, 1) - 1)
        for t in node_threads:
            t.join()
    else:
        # Sequential node execution (model 1/2)
        for index, node_id in enumerate(nodes):
            node_str = str(node_id)
            if node_str in finished_map:
                total, finished = finished_map[node_str]
                if total >= 0 and total == finished:
                    log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                              "[", Green, display_account(
                                  cache.account), Default, "] ",
                              "[", course.course_name, "] ",
                              Yellow, f"任务点进度: {index+1}/{len(nodes)}")
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
            # 实时显示任务点进度
            log_print(INFO, f"[{ACCOUNT_TYPE_STR[PLATFORM_TYPE]}]",
                      "[", Green, display_account(
                          cache.account), Default, "] ",
                      "[", course.course_name, "] ",
                      Yellow, f"任务点进度: {index+1}/{len(nodes)}")


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
            rerr = xxt_api.relogin(cache)
            _record_node_login(cache.account, rerr is None, f"节点{node_id}重登")
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
    # 多核优化：将所有卡片的 iframe 解析(CPU密集)批量送入进程池并行执行，
    # 绕开 GIL 真正吃满多核；进程池不可用时自动降级为内联解析
    _card_desc_pairs = []
    for card_idx, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        description = card.get("description", "")
        if not description:
            continue
        _card_desc_pairs.append((card_idx, card, description))

    _parsed_iframes = cpu_map(
        _parse_iframe_light, [d for _, _, d in _card_desc_pairs])

    point_dtos: List[PointDto] = []
    # 未能识别为标准类型的任务点(知识结构/引导问题/单文字/PPT/文档文章等):
    # 收集起来统一"尽力完成", 避免被静默跳过导致任务点迟迟不变绿
    other_points: List[Dict] = []
    for (card_idx, card, _desc), iframe_list in zip(_card_desc_pairs, _parsed_iframes):
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
            if _point_dto_is_set(dto):
                point_dtos.append(dto)
            else:
                other_points.append({
                    "card_index": card_idx,
                    "card": card,
                    "module": module_type,
                    "data": tp_data,
                })

    if not point_dtos and not other_points:
        return

    # === Step 2.5: 对齐 Go ChapterFetchCardsAction - cords2 补全视频参数 ===
    # Go在iframe解析后对每个视频再调FetchChapterCords2, 用attachments里的
    # jobid匹配并覆盖 OtherInfo/JobID/PlayTime(长视频分段时iframe的jobid
    # 与卡片attachment的jobid不一致, 会导致误判为非任务点而跳过)
    _cords2_cache: Dict[int, Optional[Dict]] = {}
    for _pt in point_dtos:
        if not _pt.video.is_set:
            continue
        vd = _pt.video
        kid = vd.knowledge_id
        if kid not in _cords2_cache:
            try:
                c2_body, _ = xxt_api.fetch_chapter_cords2(
                    cache, str(class_id_int), str(course_id_int),
                    str(kid), str(cpi_int), retry=3)
                _cords2_cache[kid] = xxt_api.parse_marg_json(
                    c2_body or "") or {}
            except Exception:
                _cords2_cache[kid] = {}
        c2 = _cords2_cache.get(kid) or {}
        atts = c2.get("attachments", [])
        if not isinstance(atts, list):
            continue
        for att in atts:
            if not isinstance(att, dict):
                continue
            res_jobid = _extract_jobid(att)
            if not res_jobid or res_jobid != vd.job_id:
                continue
            other_info = att.get("otherInfo", "")
            if isinstance(other_info, str) and len(other_info) > 80:
                vd.other_info = other_info
                top_jobid = att.get("jobid")
                if isinstance(top_jobid, str):
                    vd.job_id = top_jobid
                elif isinstance(top_jobid, (int, float)):
                    vd.job_id = str(int(top_jobid))
            play_time = att.get("playTime")
            if isinstance(play_time, (int, float)):
                vd.play_time = int(play_time) // 1000

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

    # 文档/其它类任务点处理后的停留秒数
    # (用户诉求: 不低于30秒, 给服务端充分时间标记任务点完成)
    try:
        _other_stay = int(getattr(cc, "other_task_stay", 30))
    except (ValueError, TypeError):
        _other_stay = 30
    if _other_stay < 0:
        _other_stay = 0

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

            # 对齐Go: 不因 is_job 提前跳过视频，交给 _execute_video 内的
            # VideoDtoFetchAction(ananas/status) 判断是否可播放
            # (长视频分段时卡片attachment匹配不到会误判为非任务点)
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
            # 模拟阅读: 停留期间周期重新打开卡片(模拟点击/滑动), 结尾上报阅读行为
            _simulated_browse(cache, class_id_int, course_id_int,
                              ddto.knowledge_id, ddto.card_index, cpi_int,
                              _other_stay)

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
                # 已完成章测: 进一步检测具体状态(待批阅/已批阅/已截止), 明确告知用户
                _st = _detect_work_review_status(cache, wdto)
                if _st == "待批阅":
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ", Green,
                              "该章测已完成提交（待批阅——等待老师批阅），无需重复操作，已自动跳过")
                elif _st == "已批阅":
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ", Green,
                              "该章测已批阅完成，无需重复操作，已自动跳过")
                elif _st == "已截止":
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ", Yellow,
                              "该章测已过截止时间且未批阅，无法作答，已自动跳过")
                else:
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

    # === 其它类型任务点(知识结构/引导问题/单文字/PPT/文档文章等) ===
    # 尽力尝试完成后停留 _other_stay 秒
    if other_points:
        _handle_other_task_points(
            setting, user, cache, course, knowledge_item, other_points,
            class_id_int, course_id_int, knowledge_id, cpi_int)


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
        # 人脸识别绕过 - 对齐 Go PassFacePhoneAction(卡片人脸流程)
        platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
        acct = display_account(cache.account)
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ", Yellow,
                  "触发人脸识别，正在尝试自动绕过...")
        err = xxt_api.pass_face_phone_action(
            cache, str(course_id), str(class_id), str(cpi),
            str(knowledge_id))
        if err:
            if "没有历史人脸" in str(err):
                return None, "", Exception("过人脸失败，该账号可能从未进行过人脸识别，请先进行一次人脸识别")
            if "活体检测不通过" in str(err):
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

    elif (module_type or "").lower() == "insertreadv2":
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


def _point_dto_is_set(dto: PointDto) -> bool:
    """判断 PointDto 是否已识别为标准任务点(六类之一)"""
    return bool(
        dto.video.is_set or dto.work.is_set or dto.document.is_set or
        dto.hyperlink.is_set or dto.live.is_set or dto.bbs.is_set
    )


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


def _detect_work_review_status(cache: XueXiTUserCache, wdto: PointWorkDto) -> str:
    """检测已完成章测的具体状态(待批阅/已批阅/已截止), 供日志明确告知用户

    章测卡片 attachment 的 job=False 仅表示"非任务点(已完成)", 无法区分
    "待批阅/已批阅"; 此处拉取一次章测页面解析关键字。失败返回空串。
    """
    try:
        body, _ = xxt_api.work_fetch_question_api(cache, wdto, retry=3)
    except Exception:
        return ""
    if not body:
        return ""
    if "已批阅" in body:
        return "已批阅"
    if "待批阅" in body:
        return "待批阅"
    if "已截止" in body or "不能作答" in body:
        return "已截止"
    return ""


def _parse_job_flag(val, default: bool = False) -> bool:
    """解析附件 job 标记(兼容 bool/字符串"true"/"1"; val为None时返回 default)"""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


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
            # jobid 位置兜底: property.jobid / property._jobid / 附件顶层 jobid
            jobid = prop.get("jobid") or prop.get("_jobid") or a.get("jobid")
            if (ddto.object_id and objectid == ddto.object_id) or \
               (jobid is not None and ddto.job_id == str(jobid)):
                ddto.title = prop.get("name", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                # 任务点判定(2026-09-21 修复"无效的请求参数"): 对齐页面 documentJob.js
                # 的 isJob() —— 只有"附件顶层 jobid"存在的文档才是真任务点;
                # 无顶层 jobid 的普通文档(如仅 property._jobid)不是任务点, 若上报
                # 会被服务器拒绝(msg: 无效的请求参数), 故 is_job=False 跳过。
                _job_flag = a.get("job")
                _top_jobid = a.get("jobid")
                if _job_flag is not None:
                    ddto.is_job = _parse_job_flag(_job_flag, default=True)
                else:
                    ddto.is_job = _top_jobid not in (None, "")
                break

        elif type_str == "insertbook":
            jobid = prop.get("jobid") or prop.get("_jobid") or a.get("jobid")
            if (jobid is not None and ddto.job_id == str(jobid)):
                ddto.title = prop.get("bookname", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                # 任务点判定对齐 documentJob.js isJob()(详见上方注释)
                _job_flag = a.get("job")
                _top_jobid = a.get("jobid")
                if _job_flag is not None:
                    ddto.is_job = _parse_job_flag(_job_flag, default=True)
                else:
                    ddto.is_job = _top_jobid not in (None, "")
                break

        elif type_str == "read":
            jobid = prop.get("jobid") or prop.get("_jobid") or a.get("jobid")
            if jobid is not None and ddto.job_id == str(jobid):
                ddto.title = prop.get("title", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                # 任务点判定对齐 documentJob.js isJob()(详见上方注释)
                _job_flag = a.get("job")
                _top_jobid = a.get("jobid")
                if _job_flag is not None:
                    ddto.is_job = _parse_job_flag(_job_flag, default=True)
                else:
                    ddto.is_job = _top_jobid not in (None, "")
                break

        else:
            # 通用fallback
            objectid = prop.get("objectid")
            jobid = prop.get("jobid") or prop.get("_jobid") or a.get("jobid")
            if (ddto.object_id and objectid == ddto.object_id) or \
               (jobid is not None and ddto.job_id == str(jobid)):
                ddto.title = prop.get("name", ddto.title)
                ddto.jtoken = a.get("jtoken", "")
                # 任务点判定对齐 documentJob.js isJob()(详见上方注释)
                _job_flag = a.get("job")
                _top_jobid = a.get("jobid")
                if _job_flag is not None:
                    ddto.is_job = _parse_job_flag(_job_flag, default=True)
                else:
                    ddto.is_job = _top_jobid not in (None, "")
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
        rerr = xxt_api.relogin(cache)
        _record_node_login(cache.account, rerr is None, "视频提交重登")
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
        if video.attachment is not None and not video.is_job:
            # attachment明确标记为非任务点(或已完成)
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title or f"任务点{video.knowledge_id}", "】 >>> ",
                      Blue, "该视频/音频非任务点或已完成，已自动跳过")
        else:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", video.title or f"任务点{video.knowledge_id}", "】 >>> ",
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
            # 服务端偶发返回异常页(HTML/空体, 非JSON): 原状态重试一次再放弃(2026-09-21)
            time.sleep(2)
            retry_body, _ = _video_submit_with_relogin(
                cache, video, playing_time, isdrag, mode)
            retry_data = safe_json_parse(retry_body) if retry_body else None
            if retry_data and "isPassed" in retry_data:
                body, resp_data = retry_body, retry_data
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", k_label, "】",
                          "【", video.title, "】 >>> ",
                          BoldRed, f"视频提交返回异常(已重试1次): "
                          f"{(retry_body or body or 'empty')[:200]}")
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
        rerr = xxt_api.relogin(cache)
        _record_node_login(cache.account, rerr is None, "音频提交重登")
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
        if audio.attachment is not None and not audio.is_job:
            # attachment明确标记为非任务点(或已完成)
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title or f"任务点{audio.knowledge_id}", "】 >>> ",
                      Blue, "该视频/音频非任务点或已完成，已自动跳过")
        else:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", audio.title or f"任务点{audio.knowledge_id}", "】 >>> ",
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
    """执行文档学习 - 对应 Go ExecuteDocument
    按类型分派: insertbook→book上报, insertreadv2→readv2上报,
    其余(document/insertdoc)→document上报
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    if not ddto.job_id:
        return

    try:
        if ddto.type == "insertbook":
            body, resp = xxt_api.document_book_report_api(
                cache, ddto.job_id, str(ddto.knowledge_id),
                ddto.course_id, ddto.class_id, ddto.jtoken, retry=5)
        elif ddto.type == "insertreadv2":
            body, resp = xxt_api.document_readv2_report_api(
                cache, ddto.job_id, str(ddto.knowledge_id),
                ddto.course_id, ddto.class_id, ddto.jtoken, retry=5)
        else:
            body, resp = xxt_api.document_read_report_api(
                cache, ddto.job_id, str(ddto.knowledge_id),
                ddto.course_id, ddto.class_id, ddto.jtoken, retry=5)
    except Exception as e:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", ddto.title, "】 >>> ",
                  BoldRed, f"文档提交异常: {e}")
        return

    # 对齐Go: 触发500时重新登录后重试一次
    if resp is not None and resp.status_code == 500:
        xxt_api.relogin(cache)
        try:
            if ddto.type == "insertbook":
                body, resp = xxt_api.document_book_report_api(
                    cache, ddto.job_id, str(ddto.knowledge_id),
                    ddto.course_id, ddto.class_id, ddto.jtoken, retry=5)
            elif ddto.type == "insertreadv2":
                body, resp = xxt_api.document_readv2_report_api(
                    cache, ddto.job_id, str(ddto.knowledge_id),
                    ddto.course_id, ddto.class_id, ddto.jtoken, retry=5)
            else:
                body, resp = xxt_api.document_read_report_api(
                    cache, ddto.job_id, str(ddto.knowledge_id),
                    ddto.course_id, ddto.class_id, ddto.jtoken, retry=5)
        except Exception:
            pass

    resp_data = safe_json_parse(body) if body else None

    # 对齐Go: 仅status为布尔true视为完成
    if resp_data and resp_data.get("status") is True:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", ddto.title, "】 >>> ",
                  "文档阅览状态：", Green, "True")
        # 首次阅读行为上报(模拟打开文档开始阅读, 辅助任务点变绿)
        try:
            xxt_api.read_point_report_api(
                cache, ddto.course_id, str(ddto.knowledge_id))
        except Exception:
            pass
    else:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", ddto.title, "】 >>> ",
                  BoldRed, f"文档提交异常: {body[:200] if body else 'empty'}")


# ============ 模拟浏览(空任务点/文档类任务点) ============

def _simulated_browse(cache: XueXiTUserCache, class_id: int, course_id: int,
                      knowledge_id: int, card_index: int, cpi: int,
                      stay: int, rounds: int = 3):
    """模拟真实浏览行为(替代纯sleep): 停留期间周期性重新打开卡片页(模拟点击/反复
    进入任务点), 并在中途/结尾上报阅读行为(模拟滑动、滚动到底部)。

    - 卡片页重开: 代表"点击进入任务点"行为
    - read_point_report: 上报阅读字数/滚动高度, 供服务端判定任务点真实阅读
    总时长≈stay秒; 失败全部静默(best-effort)
    """
    try:
        stay = int(stay)
    except (ValueError, TypeError):
        stay = 30
    if stay <= 0:
        return
    rounds = max(2, min(int(rounds), 6)) if stay >= 4 else 1
    per = max(1, stay // rounds)
    for i in range(rounds):
        # 模拟点击重新进入任务点(刷新卡片页)
        try:
            xxt_api.page_mobile_chapter_card_api(
                cache, class_id, course_id, knowledge_id, card_index, cpi,
                retry=2)
        except Exception:
            pass
        # 中途与结尾各上报一次阅读行为(模拟滑动阅读)
        if i >= rounds - 2 and rounds > 1:
            try:
                xxt_api.read_point_report_api(
                    cache, str(course_id), str(knowledge_id))
            except Exception:
                pass
        time.sleep(per if i < rounds - 1
                   else max(0, stay - per * (rounds - 1)))


# ============ 其它类型任务点处理 ============

def _handle_other_task_points(setting: Setting, user: User,
                              cache: XueXiTUserCache, course: XueXiTCourse,
                              knowledge: KnowledgeItem, other_points: List[Dict],
                              class_id: int, course_id: int,
                              knowledge_id: int, cpi: int):
    """处理未能识别为标准类型的任务点(知识结构/引导问题/单文字/PPT/文档文章等)

    - 尽力尝试完成: 若存在jobid则构造文档DTO走文档上报(best-effort)
    - 处理完成后停留 otherTaskStay 秒(默认30), 给服务端充分时间标记完成
    """
    if not other_points:
        return
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    cc = user.courses_custom
    try:
        stay = int(getattr(cc, "other_task_stay", 30))
    except (ValueError, TypeError):
        stay = 30
    # 用户要求: 空/其它任务点至少停留30秒并模拟滑动点击
    if stay < 30:
        stay = 30

    k_label = (f"{knowledge.label} {knowledge.name}".strip()
               if knowledge.label else knowledge.name)

    for op in other_points:
        module_type = op.get("module", "")
        tp_data = op.get("data", {}) or {}
        card_index = op.get("card_index", 0)
        title = (tp_data.get("title") or tp_data.get("name") or module_type)

        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  "【", k_label, "】 ",
                  DarkGray,
                  f"检测到其它类型任务点(module={module_type})，"
                  f"尝试尽力完成并停留{stay}秒...")

        job_id = _extract_jobid(tp_data)
        if not job_id:
            # 无jobid无法上报: 模拟点击/滑动浏览(停留期间反复打开卡片页)
            _simulated_browse(cache, class_id, course_id, knowledge_id,
                              card_index, cpi, stay)
            continue

        # best-effort: 构造文档DTO并尝试上报
        try:
            dto = PointDocumentDto()
            dto.card_index = card_index
            dto.course_id = str(course_id)
            dto.class_id = str(class_id)
            dto.knowledge_id = knowledge_id
            dto.cpi = str(cpi)
            dto.title = title
            dto.job_id = job_id
            dto.type = "document"
            dto.is_set = True

            _card, _enc, err = _page_mobile_chapter_card_action(
                setting, cache, class_id, course_id,
                knowledge_id, card_index, cpi)
            if err:
                if "章节未开放" in str(err):
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】 ", BoldRed,
                              "该章节未开放，已自动跳过")
                    return
            elif _card is not None:
                _attachments_detection_document(dto, _card)
            _execute_document(cache, course, dto)
        except Exception as e:
            log_print(DEBUG, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】", DarkGray,
                      f"其它任务点({module_type})尽力处理异常: {e}")

        # 模拟点击/滑动浏览(替代纯sleep, 满足停留≥30秒+滑动手势模拟)
        _simulated_browse(cache, class_id, course_id, knowledge_id,
                          card_index, cpi, stay)


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

    # 4. 根据答题模式获取回答内容(讨论回复仅走AI答题源)
    content = ""
    if cc.auto_exam in (1, 2):
        try:
            from logic.core.answer_engine import answer_query
            prompt = topic_title
            if topic_content:
                prompt = topic_title + "\n" + topic_content
            answer = answer_query(prompt, q_type="short", only_ai=True)
            content = answer if answer else "同意"
        except Exception:
            content = "同意"
    elif cc.auto_exam == 3:
        try:
            body, _ = xxt_api.xxt_ai_api(
                cache, topic_title,
                course.course_id, course.key, str(course.cpi))
            content = body.strip() if body and body.strip() else "同意"
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

    # 多选题: 尝试分割AI答案 (常见分隔符: ，、, \n ; # 等; #为AXE题库分隔符)
    # 对齐Go: for _, item := range ch.Answers { answers += SimilarityArraySelect(item, candidateSelects) }
    parts = re.split(r'[,，、;#\n|/]+', target)
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

    # 章测已截止/已批阅(只读视图, 无作答控件): 跳过
    # 区分已批阅(学生已交/老师已批改, 正常完成)与未批阅(超时未做)
    reviewed = "已批阅" in body
    expired = "已截止" in body or "不能作答" in body
    if reviewed or expired:
        k_label = (f"{knowledge.label} {knowledge.name}".strip()
                   if knowledge.label else knowledge.name)
        title_m = re.search(
            r'chapter-title[^>]*>([^<]+)<', body)
        zc_title = title_m.group(1).strip() if title_m else ""
        if reviewed:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", zc_title or "章测", "】 ",
                      Green, "该章测已批阅(已完成)，无需作答，已自动跳过")
        else:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      "【", k_label, "】",
                      "【", zc_title or "章测", "】 ",
                      Yellow, "该章测已过截止时间且未批阅，无法作答，已自动跳过")
        return

    # 解析题目并提取元数据 (图片题干/选项自动OCR)
    _img_ocr = _make_img_ocr(
        cache, enabled=(getattr(setting.basic_setting, "ocr_image_question", 1) == 1))
    questions, meta = _parse_work_questions_v2(body, img_ocr=_img_ocr)
    if not questions:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Yellow, "该章测无题目，已自动跳过")
        return

    mode_str = ""
    if cc.auto_exam in (1, 2):
        mode_str = "多源答题"
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
    for _qi, q in enumerate(questions):
        q_type = q.get("type", "")
        q_text = q.get("text", "")
        q_id = q.get("id", "")
        answer = ""
        answer_src = ""  # 命中的答题源名称(用于日志)

        # 提取选项纯文本(去掉 "A." 前缀) - 对齐Go TurnStandardQuestion
        raw_options = q.get("options", [])
        opt_texts_for_ai = []
        for opt in raw_options:
            dot_idx = opt.find(".")
            if dot_idx >= 0:
                opt_texts_for_ai.append(opt[dot_idx+1:].strip())
            else:
                opt_texts_for_ai.append(opt)

        if cc.auto_exam in (1, 2):
            # 多答题源顺序调用: 本地题库缓存 -> 各题库/AI源按顺序回退
            try:
                from logic.core.answer_engine import answer_query_detail
                answer, answer_src = answer_query_detail(
                    q_text, options=opt_texts_for_ai, q_type=q_type)
            except Exception:
                answer = ""
        elif cc.auto_exam == 3:
            try:
                ai_body, _ = xxt_api.xxt_ai_api(
                    cache, q_text, course.course_id, course.key, str(
                        course.cpi),
                    options=opt_texts_for_ai, q_type=q_type)
                answer = ai_body.strip() if ai_body else ""
                if answer:
                    answer_src = "内置AI(学习通)"
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

        # 每题答题来源日志: 明确标注本题由哪个题库/AI源回答成功(含课程/章节归属)
        if cc.auto_exam in (1, 2, 3):
            _q_brief = q_text.replace("\n", " ").replace("\r", " ")[:50]
            _k_label = f"{knowledge.label} {knowledge.name}".strip()
            if answer:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", _k_label, "】",
                          f"<{mode_str}>", "第", str(_qi + 1), "题",
                          Yellow, f" 使用【{answer_src or '默认'}】回答: ",
                          Default, f"{answer[:80]}",
                          DarkGray, f" | 题目: {_q_brief}")
            else:
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】",
                          "【", _k_label, "】",
                          f"<{mode_str}>", "第", str(_qi + 1), "题",
                          Red, " 所有答题源均未命中",
                          DarkGray, f" | 题目: {_q_brief}")

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

    # 检查答题源是否可用 - 如果所有源都没有给出实际答案，跳过提交
    if ai_answered == 0 and cc.auto_exam in (1, 2, 3) and questions:
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  "【", f"{knowledge.label} {knowledge.name}".strip(), "】",
                  "【", title, "】",
                  Yellow, f"所有答题源均未返回答案，跳过提交")
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
            # 对齐Go: "正确"→true, "错误"→false; 兼容"对/错/√/×/T/F/A/B"等
            # (2026-09-21 修复: 原实现仅认"正确/错误", 正确答案为"错"时
            #  会误默认 true, 导致判断题提交错误内容)
            judge_answer = (answer or "").strip()
            if judge_answer in ("正确", "对", "√", "是", "true", "True",
                                "T", "A", "a"):
                judge_answer = "true"
            elif judge_answer in ("错误", "错", "×", "否", "false", "False",
                                  "F", "B", "b"):
                judge_answer = "false"
            else:
                # 未知格式: 默认 true(对)
                judge_answer = "true"
            submit_data[f"answer{q_id}"] = judge_answer
            submit_data[f"answertype{q_id}"] = aw_type

        elif q_type == "fill":
            # 对齐Go: answer{qid}{index} → tiankongsize → answertype
            # 多空支持(2026-09-21): 题库用 ### 分隔多个空的答案, 按空序号依次填入;
            # 无 ### 或单空时保持原行为(所有空填同一答案)
            _blanks = [b.strip()
                       for b in str(answer).split("###") if b.strip()]
            if not _blanks:
                _blanks = [str(answer)]
            answer_fields = q.get("answer_fields", {})
            for k, v in answer_fields.items():
                if k.startswith(f"answer{q_id}"):
                    _m = re.search(r"(\d+)$", k[len(f"answer{q_id}"):])
                    _idx = int(_m.group(1)) if _m else 1
                    if len(_blanks) > 1:
                        submit_data[k] = _blanks[_idx -
                                                 1] if 1 <= _idx <= len(_blanks) else _blanks[-1]
                    else:
                        submit_data[k] = _blanks[0]
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

    # 第二层保护：提交前再次验证答题源答案不为空
    if ai_answered == 0 and cc.auto_exam in (1, 2, 3):
        log_print(INFO, f"[{platform}]",
                  "[", Green, acct, Default, "] ",
                  f"<{mode_str}>",
                  "【", course.course_name, "】",
                  "【", f"{knowledge.label} {knowledge.name}".strip(), "】",
                  "【", title, "】",
                  Yellow, f"[保护] 所有答题源均未返回答案，阻止提交(ai_answered={ai_answered})")
        return

    # 详细调试: 输出所有答案字段
    answer_debug = []
    for q in questions:
        q_id = q.get('id', '')
        q_type = q.get('type', '')
        raw_ans = q.get('answer', '')
        submitted = submit_data.get(f'answer{q_id}')
        if submitted is None:
            # 填空题等按 answer{qid}{空序} 分字段提交, 汇总展示各空提交值
            _pref = f'answer{q_id}'

            def _blank_idx(key):
                _bm = re.search(r'(\d+)$', key[len(_pref):])
                return int(_bm.group(1)) if _bm else 0

            _cands = sorted(
                (k for k in submit_data if isinstance(k, str)
                 and k.startswith(_pref)), key=_blank_idx)
            submitted = ('|'.join(str(submit_data.get(k, ''))
                                  for k in _cands[:5]) if _cands else '<MISSING>')
        answer_debug.append(
            f"q{q_id}({q_type}):raw={repr(raw_ans[:30])}→sub={repr(str(submitted)[:30])}")
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


# ============ 图片题目 OCR ============

# 匹配 <img> 的惰性加载/真实地址(data-src 优先)
_IMG_SRC_RE = re.compile(
    r'<img[^>]+?(?:data-src|data-original|src)=["\']([^"\']+)["\']',
    re.IGNORECASE)


def _normalize_img_url(url: str) -> str:
    """规范化图片URL(补全协议/域名, 还原HTML实体)"""
    if not url:
        return ""
    url = url.strip().replace("&amp;", "&")
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://mooc1.chaoxing.com" + url
    return url


def _ocr_from_html(fragment: str, img_ocr, limit: int = 10) -> str:
    """从HTML片段中提取所有<img>并OCR, 返回拼接文本"""
    if not fragment or img_ocr is None:
        return ""
    texts: List[str] = []
    seen = set()
    for m in _IMG_SRC_RE.finditer(fragment):
        if len(texts) >= limit:
            break
        raw = m.group(1)
        if not raw or raw.startswith("data:"):
            continue
        url = _normalize_img_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        t = img_ocr(url)
        if t:
            texts.append(t)
    return " ".join(texts).strip()


def _ocr_from_node(node, img_ocr, limit: int = 10) -> str:
    """从BeautifulSoup节点中提取所有<img>并OCR, 返回拼接文本"""
    if node is None or img_ocr is None:
        return ""
    try:
        imgs = node.find_all("img")
    except Exception:
        return ""
    if not imgs:
        return ""
    texts: List[str] = []
    seen = set()
    for img in imgs:
        if len(texts) >= limit:
            break
        raw = (img.get("data-src") or img.get("data-original")
               or img.get("src") or "")
        if not raw or raw.startswith("data:"):
            continue
        url = _normalize_img_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        t = img_ocr(url)
        if t:
            texts.append(t)
    return " ".join(texts).strip()


def _make_img_ocr(cache: XueXiTUserCache, enabled: bool = True,
                  max_imgs: int = 30):
    """构造图片OCR解析器 callable(url)->str(带下载+识别缓存与限流)

    不可用(未开启/未安装依赖)时返回 None
    :param enabled: 是否开启(对应 basicSetting.ocrImageQuestion)
    :param max_imgs: 单次解析最多识别的图片数量(防止图片过多拖慢)
    """
    if not enabled:
        return None
    from logic.core import ocr_utils
    if not ocr_utils.ocr_available():
        ocr_utils.warn_missing_once()
        return None

    state: Dict[str, Any] = {"client": None, "cache": {}, "count": 0}

    def _resolve(url: str) -> str:
        if not url:
            return ""
        cache_map = state["cache"]
        if url in cache_map:
            return cache_map[url]
        if state["count"] >= max_imgs:
            return ""
        state["count"] += 1
        client = state["client"]
        if client is None:
            try:
                client = xxt_api._build_client(cache)
                state["client"] = client
            except Exception:
                cache_map[url] = ""
                return ""
        try:
            img_bytes, _ = client.get_image(url, retry=2)
        except Exception:
            img_bytes = None
        text = ocr_utils.ocr_bytes(img_bytes) if img_bytes else ""
        cache_map[url] = text
        return text

    return _resolve


def _parse_work_questions_v2(html_body: str,
                             img_ocr=None) -> Tuple[List[Dict], Dict]:
    """从作业页面HTML解析题目列表+元数据 - 对齐Go ParseWorkQuestionAction
    使用 BeautifulSoup + div.Py-mian1 块解析每道题（与Go的ParseQuestionSets完全对齐）
    :param img_ocr: 可选的图片OCR解析器 callable(url)->str, 用于回填图片题干/选项
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
        # 题型判定(2026-09-21 修复"作业提交失败"): 学习通有时将判断题渲染为
        # [单选题]显示文本, 但真实题型以页面 hidden answertype{qid} 与结构为准。
        # 优先级: answerList.panduan结构 > hidden answertype > 显示文本
        _aw_to_key = {"0": "single_choice", "1": "multiple_choice",
                      "2": "fill", "3": "judge", "4": "short",
                      "5": "term_explanation", "6": "essay", "11": "matching"}
        hidden_aw = ""
        aw_input = node.find(
            "input", attrs={"name": f"answertype{qid}"})
        if aw_input is not None:
            hidden_aw = str(aw_input.get("value", "") or "").strip()
        has_panduan = node.find(
            class_=lambda c: c and "answerList" in c and "panduan" in c) is not None
        if has_panduan:
            q_type = "judge"
        elif hidden_aw in _aw_to_key:
            q_type = _aw_to_key[hidden_aw]
        else:
            q_type = type_cn_to_key.get(type_text, "short")
        aw_type = type_to_answertype.get(q_type, hidden_aw or "0")

        # 提取题目文本 (Go: .Py-m1-title .workTextWrap)
        text = ""
        if title_div:
            text_wrap = title_div.find(class_="workTextWrap")
            if text_wrap:
                text = text_wrap.get_text(strip=True)
            # 图片题干OCR回填
            ocr_text = _ocr_from_node(title_div, img_ocr)
            if ocr_text:
                text = (text + " " + ocr_text).strip() if text else ocr_text
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
                        # 图片选项OCR回填
                        ocr_opt = _ocr_from_node(li, img_ocr)
                        if ocr_opt:
                            opt_text = (opt_text + " " + ocr_opt).strip() \
                                if opt_text else ocr_opt
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

    # 答题源可用性检查(多答题源: 题库+AI, 含本地题库缓存)
    if cc.auto_exam in (1, 2):
        from logic.core.answer_engine import engine_is_ready
        if not engine_is_ready():
            log_print(INFO, f"[{platform}]",
                      BoldRed, "未配置可用的答题源(题库/AI)且本地题库缓存为空，跳过作业与考试")
            return

    # 作业
    if (cc.cx_work_sw or 0) == 1:
        _work_action(setting, user, cache, course)

    # 考试 - 全局串行: 无论账号以何种模式运作，
    # 考试必须一个一个按顺序处理，不能同时处理多个考试
    if (cc.cx_exam_sw or 0) == 1:
        with _exam_serial_lock:
            _exam_action(setting, user, cache, course)


# ============ 增加学习次数/学习时长(参照 yatori-free / chaoxing_tool 的 setlog 机制) ============

_STUDY_PV_COUNT_URL = "https://stat2-ans.chaoxing.com/stat2/study-pv/chart"


def _get_study_pv_count(client, course: XueXiTCourse) -> Optional[int]:
    """读取课程学习次数(stat2 study-pv chart) - 参照 chaoxing_tool get_count_log"""
    try:
        import datetime
        now = datetime.datetime.now()
        body, _ = client.post_form(
            _STUDY_PV_COUNT_URL,
            {
                "clazzid": course.key,
                "courseid": course.course_id,
                "cpi": str(course.cpi),
                "ut": "s",
                "year": str(now.year),
                "month": f"{now.month:02d}",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            retry=2, use_multipart=False)
        data = safe_json_parse(body or "")
        if data:
            total = data.get("total")
            if total is not None and int(total or 0) > 0:
                return int(total)
            # total 恒0的月份兜底: 用每日 count 数组求和(实测 total 可能为0)
            counts = data.get("count")
            if isinstance(counts, list) and counts:
                try:
                    return int(sum(int(x or 0) for x in counts))
                except (ValueError, TypeError):
                    pass
            if total is not None:
                return int(total)
    except Exception:
        pass
    return None


def _add_study_count_action(setting: Setting, user: User,
                            cache: XueXiTUserCache, course: XueXiTCourse):
    """增加学习次数/学习时长 - 对齐 yatori-free 的三指标设计

    yatori-free 每课程(账号)可设置 StudyIncrement{visitCount, videoStudyMinutes,
    readMinutes}, 默认均为0(即不增加); 本实现与之对齐:
      学习次数     -> setlog 学习记录上报(参照 chaoxing_tool set_log, 间隔默认30s)
      视频观看时长 -> 视频播放进度上报(尽量把课程视频刷满, 参照 chaoxing_tool set_time)
      阅读时长     -> 阅读行为上报(ac_mark/readPoint, 对阅读类任务点循环上报)
    前提: 课程所有可访问任务点已完成(服务端任务点进度100%)。
    """
    cc = user.courses_custom
    if int(getattr(cc, "add_study_sw", 0) or 0) != 1:
        return
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    # 读取三指标(边界对齐 yatori-free 界面限制: 次数<=400, 时长<=4000分钟)
    count = int(getattr(cc, "add_study_count", 0) or 0)
    video_minutes = int(getattr(cc, "add_study_video_minutes", 0) or 0)
    read_minutes = int(getattr(cc, "add_study_read_minutes", 0) or 0)
    delay = int(getattr(cc, "add_study_delay", 30) or 30)
    count = max(0, min(400, count))
    video_minutes = max(0, min(4000, video_minutes))
    read_minutes = max(0, min(4000, read_minutes))
    delay = max(30, delay)

    if count == 0 and video_minutes == 0 and read_minutes == 0:
        # 对齐 yatori-free 默认参数(均为0): 未设置时不做任何增加
        return

    # 复查课程完成度: 任务点全部完成才执行(重新拉取服务端进度)
    try:
        _fetch_course_status(cache, [course])
    except Exception:
        pass
    if course.job_rate < 100:
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Yellow, f"任务点未全部完成(进度{course.job_rate:.0f}%)，本次不执行增加学习次数/时长")
        return

    # 预计总耗时: 次数×间隔/60 + 视频(真实节奏约1:1) + 阅读轮数×间隔/60
    _est_min = 0.0
    if count > 0:
        _est_min += count * delay / 60.0
    if video_minutes > 0:
        _est_min += video_minutes
    if read_minutes > 0:
        _est_min += read_minutes * delay / 60.0

    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              Yellow, f"任务点已全部完成，开始增加学习次数/学习时长"
              f"(学习次数{count}, 视频观看时长{video_minutes}分钟, "
              f"阅读时长{read_minutes}分钟, 间隔{delay}秒, "
              f"预计总耗时约{_est_min:.0f}分钟)...")
    t0 = time.time()

    # ===== 1) 学习次数(setlog 机制) =====
    _res_count = 0
    if count > 0:
        _res_count = _add_study_setlog_times(cache, course, count, delay)

    # ===== 2) 视频观看时长(视频播放进度上报) =====
    _res_video = 0
    if video_minutes > 0:
        _res_video = _add_video_watch_minutes(
            cache, course, video_minutes, delay)

    # ===== 3) 阅读时长(阅读行为上报) =====
    _res_read = 0
    if read_minutes > 0:
        _res_read = _add_read_minutes(cache, course, read_minutes, delay)

    # 结束汇总: 实际增加量与总耗时(不改变任何既有行为)
    _done_parts = []
    if count > 0:
        _done_parts.append(f"学习次数+{_res_count}次(目标{count}次)")
    if video_minutes > 0:
        _done_parts.append(f"视频观看时长约+{_res_video}分钟(目标{video_minutes}分钟)")
    if read_minutes > 0:
        _done_parts.append(f"阅读时长约+{_res_read}轮(目标{read_minutes}分钟)")
    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              Green, f"增加学习次数/学习时长执行完毕"
              f"（{'；'.join(_done_parts)}；总耗时约{(time.time() - t0) / 60.0:.1f}分钟）")


def _add_study_setlog_times(cache: XueXiTUserCache, course: XueXiTCourse,
                            count: int, delay: int):
    """学习次数上报(setlog) - 参照 chaoxing_tool set_log"""
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)
    client = xxt_api._build_client(cache)
    try:
        before = _get_study_pv_count(client, course)
        if before is not None:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      f"当前学习次数: {before}次")
        _est_min = max(1, (count * delay + 59) // 60)
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  f"开始增加学习次数(共{count}次, 每次间隔{delay}秒, "
                  f"预计耗时约{_est_min}分钟)...")

        # 打开课程学习页, 提取学习记录上报链接(setlog)
        page_url = (
            "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
            f"?courseid={course.course_id}&clazzid={course.key}"
            f"&cpi={course.cpi}&ut=s&t={int(time.time() * 1000)}")
        page, _ = client.get(page_url, retry=3)
        setlog_url = ""
        if page:
            m = re.search(
                r'(https://fystat-ans\.chaoxing\.com/log/setlog[^"\'<>\s\\]+)',
                page)
            if m:
                setlog_url = m.group(1)
        if not setlog_url:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      Red, "未能提取学习记录上报链接(页面结构可能已变化), 本次跳过学习次数增加")
            return 0

        ok_times = 0
        for i in range(count):
            _, resp = client.get(setlog_url, retry=2)
            status = resp.status_code if resp is not None else "无响应"
            if resp is not None and resp.status_code == 200:
                ok_times += 1
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      f"增加学习次数 第{i + 1}/{count}次 (状态: {status})")
            if i < count - 1:
                time.sleep(delay)

        after = _get_study_pv_count(client, course)
        if before is not None and after is not None:
            _delta = max(0, after - before)
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      Green, f"学习次数变化: {before}→{after}次"
                      f" (本次成功上报{ok_times}次, 实际增加{_delta}次)")
            return _delta
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Green, f"学习次数上报完成(本次成功上报{ok_times}次, 未能读取前后次数对比)")
        return ok_times
    finally:
        client.close()


def _collect_course_resources(cache: XueXiTUserCache, course: XueXiTCourse,
                              need_videos: bool = True,
                              need_docs: bool = False):
    """收集课程章节中的视频/文档任务点DTO(供增加视频时长/阅读时长使用)

    need_videos=True 时对视频执行 cords2 参数补全(otherInfo/jobId/playTime,
    对齐 _node_run 中 ChapterFetchCardsAction 的补全逻辑)
    """
    videos: List[PointVideoDto] = []
    documents: List[PointDocumentDto] = []
    try:
        cid, clz, cpi = int(course.course_id), int(course.key), int(course.cpi)
    except (ValueError, TypeError):
        return videos, documents

    body, _ = xxt_api.pull_chapter_api(cache, clz, cpi, retry=5)
    data = safe_json_parse(body or "")
    klist = []
    ditems = (data or {}).get("data", [])
    if isinstance(ditems, list) and ditems and isinstance(ditems[0], dict):
        cobj = ditems[0].get("course", {})
        cinfo = cobj
        inner = cobj.get("data")
        if isinstance(inner, list) and inner:
            cinfo = inner[0]
        kobj = cinfo.get("knowledge", []) if isinstance(cinfo, dict) else []
        if isinstance(kobj, dict):
            klist = kobj.get("data", [])
        elif isinstance(kobj, list):
            klist = kobj

    for item in klist:
        if not isinstance(item, dict):
            continue
        nid = item.get("id", 0)
        if not nid:
            continue
        try:
            c_body, _ = xxt_api.fetch_chapter_cords(cache, nid, cid, retry=3)
        except Exception:
            continue
        c_data = safe_json_parse(c_body or "")
        craw = (c_data or {}).get("data", [])
        cards = []
        if isinstance(craw, list) and craw and isinstance(craw[0], dict):
            cards = craw[0].get("card", {}).get("data", [])
        for ci, card in enumerate(cards):
            if not isinstance(card, dict):
                continue
            desc = card.get("description", "") or ""
            if not desc:
                continue
            parsed = _parse_iframe_light(desc)
            for point in parsed:
                mt = point.get("other", {}).get("module", "")
                if not point.get("has_data"):
                    continue
                dto = PointDto()
                _fill_dto_from_iframe(dto, mt, point.get("data", {}),
                                      ci, cid, clz,
                                      card.get("knowledgeid", 0),
                                      cpi, card, cache)
                if need_videos and dto.video.is_set:
                    videos.append(dto.video)
                elif need_docs and dto.document.is_set:
                    documents.append(dto.document)

    # cords2 补全视频参数(otherInfo/jobId/playTime) - 对齐 _node_run
    if need_videos and videos:
        _cords2_cache: Dict[int, Optional[Dict]] = {}
        for vd in videos:
            kid = vd.knowledge_id
            if kid not in _cords2_cache:
                try:
                    c2_body, _ = xxt_api.fetch_chapter_cords2(
                        cache, str(clz), str(cid), str(kid), str(cpi), retry=3)
                    _cords2_cache[kid] = xxt_api.parse_marg_json(
                        c2_body or "") or {}
                except Exception:
                    _cords2_cache[kid] = {}
            c2 = _cords2_cache.get(kid) or {}
            atts = c2.get("attachments", [])
            if not isinstance(atts, list):
                continue
            for att in atts:
                if not isinstance(att, dict):
                    continue
                res_jobid = _extract_jobid(att)
                if not res_jobid or res_jobid != vd.job_id:
                    continue
                other_info = att.get("otherInfo", "")
                if isinstance(other_info, str) and len(other_info) > 80:
                    vd.other_info = other_info
                    top_jobid = att.get("jobid")
                    if isinstance(top_jobid, str):
                        vd.job_id = top_jobid
                    elif isinstance(top_jobid, (int, float)):
                        vd.job_id = str(int(top_jobid))
                play_time = att.get("playTime")
                if isinstance(play_time, (int, float)):
                    vd.play_time = int(play_time) // 1000
                break
    return videos, documents


def _add_video_watch_minutes(cache: XueXiTUserCache, course: XueXiTCourse,
                             target_minutes: int, delay: int) -> int:
    """增加视频观看时长 - 对课程视频任务点做播放进度上报(参照 chaoxing_tool set_time)

    从视频当前进度逐分钟上报至视频结束, 两次上报间隔58秒(实测逼近真实播放节奏:
    过快上报服务器不计入进度), 因此增加1分钟时长≈等待1分钟;
    每刷满一个视频约增加该视频分钟数的学习时长; 累计达到目标分钟后停止。
    返回本次估计增加分钟数(best-effort)。
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    videos, _ = _collect_course_resources(cache, course,
                                          need_videos=True, need_docs=False)
    if not videos:
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Yellow, "该课程未找到视频任务点，跳过增加视频观看时长")
        return 0

    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              f"共找到{len(videos)}个视频任务点; 增加视频观看时长按真实播放节奏"
              f"执行, 预计耗时约{target_minutes}分钟, 请耐心等待...")

    added = 0
    for vd in videos:
        if added >= target_minutes:
            break
        if not _video_dto_fetch_action(cache, vd):
            continue
        if vd.duration <= 0:
            continue
        v_min = max(1, int(round(vd.duration / 60.0)))
        start = vd.play_time if 0 <= vd.play_time < vd.duration else 0
        if start >= vd.duration:
            # 已看完的视频: 结尾重报一次(尽力而为, 部分课程可继续累计)
            try:
                _video_submit_with_relogin(cache, vd, vd.duration, 0, 1)
            except Exception:
                pass
            continue

        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  f"'{vd.title}' 正在增加观看时长(从{start // 60}分钟到{v_min}分钟)...")
        try:
            _video_submit_with_relogin(cache, vd, start, 3, 1)
        except Exception:
            pass
        t = start + 60 - (start % 60)
        code = 0
        ok = True
        while t <= vd.duration:
            body, resp = _video_submit_with_relogin(cache, vd, t, 0, 1)
            code = resp.status_code if resp else 0
            if code in (202, 400, 403, 500):
                ok = False
                break
            # 关键: 上报间隔必须接近真实播放节奏(实测过快上报服务器不计入进度,
            # 参照 chaoxing_tool run_video 的 sleep(59.8s)); 刷1分钟时长≈等待1分钟
            time.sleep(58)
            t += 60
        # 结尾补点
        try:
            _video_submit_with_relogin(cache, vd, vd.duration, 0, 1)
        except Exception:
            pass
        if ok:
            gain = max(0, v_min - start // 60)
            added += gain
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      Green, f"'{vd.title}' 增加观看时长约{gain}分钟 "
                      f"(累计{added}/{target_minutes}分钟)")
        else:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】",
                      Yellow, f"'{vd.title}' 上报受阻(status={code})，已跳过")

    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              Green, f"增加视频观看时长执行完毕(本次估计增加约{added}分钟/目标{target_minutes}分钟)")
    return added


def _add_read_minutes(cache: XueXiTUserCache, course: XueXiTCourse,
                      target_minutes: int, delay: int) -> int:
    """增加阅读时长 - 对课程阅读类任务点循环"阅读行为上报"(ac_mark/readPoint)

    每轮对课程所有阅读类任务点各上报一次(模拟阅读滑动行为), 轮数与目标
    分钟数一致(间隔delay秒); 返回成功执行轮数(best-effort)。
    """
    platform = ACCOUNT_TYPE_STR[PLATFORM_TYPE]
    acct = display_account(cache.account)

    _, documents = _collect_course_resources(cache, course,
                                             need_videos=False, need_docs=True)
    if not documents:
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  Yellow, "该课程未找到阅读类任务点，跳过增加阅读时长")
        return 0

    est = max(1, (target_minutes * delay) // 60)
    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              Yellow, f"开始增加阅读时长(目标{target_minutes}分钟, "
              f"对{len(documents)}个阅读任务点每轮各上报一次, "
              f"间隔{delay}秒, 预计耗时约{est}分钟)...")

    ok_rounds = 0
    for r in range(target_minutes):
        for dd in documents:
            try:
                xxt_api.read_point_report_api(
                    cache, dd.course_id, str(dd.knowledge_id))
            except Exception:
                pass
        ok_rounds += 1
        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】",
                  f"增加阅读时长 第{r + 1}/{target_minutes}轮上报完成")
        if r < target_minutes - 1:
            time.sleep(delay)

    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
              "【", course.course_name, "】",
              Green, f"增加阅读时长执行完毕(共完成{ok_rounds}/{target_minutes}轮上报)")
    return ok_rounds


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


def _html_work_question_turn_entity(html: str, img_ocr=None) -> Dict:
    """解析作业题目HTML提取元数据 - 对应 Go HtmlWorkQuestionTurnEntity
    :param img_ocr: 可选的图片OCR解析器, 用于回填图片题干/选项
    """
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
        raw_title = title_match.group(1)
        content = re.sub(r'<[^>]+>', '', raw_title).strip()
        # 图片题干OCR回填
        ocr_title = _ocr_from_html(raw_title, img_ocr)
        if ocr_title:
            content = (content + " " +
                       ocr_title).strip() if content else ocr_title
        q["questionContent"] = content
    # Extract options from div.centerSpan
    # 新版作业页面结构: <div aria-hidden="true" id="A" class="centerSpan workWrap">
    # (id在class前、class为多值) + 旧版: <div class="centerSpan" id="A">
    # 统一按"开标签含centerSpan"匹配, 再从开标签中提取选项字母id
    options = {}
    for opt_m in re.finditer(
            r'<div[^>]*\bclass=["\'][^"\']*\bcenterSpan\b[^"\']*["\'][^>]*>(.*?)</div>',
            html, re.IGNORECASE | re.DOTALL):
        opt_full = opt_m.group(0)
        opt_tag = opt_full[:opt_full.index(">") + 1] if ">" in opt_full else ""
        id_m = re.search(r'\bid=["\']([A-Za-z]+)["\']', opt_tag)
        letter = (id_m.group(1).strip().upper() if id_m else "")
        if len(letter) != 1:
            continue
        raw_opt = opt_m.group(1)
        text = re.sub(r'<[^>]+>', '', raw_opt).strip()
        # 图片选项OCR回填
        ocr_opt = _ocr_from_html(raw_opt, img_ocr)
        if ocr_opt:
            text = (text + " " + ocr_opt).strip() if text else ocr_opt
        if text and letter not in options:
            options[letter] = text
    q["options"] = [options.get(l, "")
                    for l in "ABCDEFGHIJKLMN" if options.get(l, "")]

    # Extract all metadata hidden fields
    for field_id in ["courseId", "testUserRelationId", "answerId",
                     "workRelationAnswerId", "classId", "type", "isphone",
                     "imei", "subCount", "remainTime", "tempSave", "timeOver",
                     "encRemainTime", "encLastUpdateTime", "cpi", "enc", "source",
                     "userId", "enterPageTime", "answeredView", "paperGroupId",
                     "workId", "currentTime", "currentCpi", "currentUploadEnc",
                     "matchEnc", "cfid", "addTimes", "limitWorkSubmitTimes",
                     "encWork", "index"]:
        q[field_id] = _html_input_get(html, field_id)
    q["score"] = _html_input_name_get(html, f"score{qid}")
    return q


def _extract_exam_question_text(tit) -> str:
    """对齐 Go extractQuestion: 跳过 h3 与 span[aria-label=题干]，拼接文本节点"""
    parts = []

    def _walk(node):
        for child in getattr(node, "children", []) or []:
            name = getattr(child, "name", None)
            if name is None:  # 文本节点
                text = str(child).strip()
                if text:
                    parts.append(text)
                continue
            if name == "h3":
                continue
            if name == "span" and (child.get("aria-label") or "") == "题干":
                continue
            _walk(child)

    _walk(tit)
    return "".join(parts).strip()


def _html_exam_question_turn_entity(html: str, img_ocr=None) -> Dict:
    """解析考试题目HTML提取元数据 - 对应 Go HtmlQuestionTurnEntity
    选项解析对齐 Go singleTurn/multipleTurn/trueOrFalseTurn:
    - 单选: div.singleChoice[name=X] 内 .answerInfo(含<cc>标签)文本
    - 多选: div.mulChoice[name=X](兼容multiChoice) 同上
    - 判断: .answerList 内 .No(字母)+.answerInfo(文本)
    :param img_ocr: 可选的图片OCR解析器, 用于回填图片题干/选项
    """
    q = {}
    qid = _html_input_get(html, "questionId")
    q["questionId"] = qid
    q["questionTypeCode"] = _html_input_name_get(html, f"type{qid}")
    q["questionTypeStr"] = _html_input_name_get(html, f"typeName{qid}")

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        soup = None

    if soup is not None:
        # 题目内容 - 对齐 Go: .tit 且跳过 h3/题干标记
        tit = soup.find(class_="tit")
        if tit:
            content = _extract_exam_question_text(tit)
            # 图片题干OCR回填
            ocr_tit = _ocr_from_node(tit, img_ocr)
            if ocr_tit:
                content = (content + " " + ocr_tit).strip() \
                    if content else ocr_tit
            if content:
                q["questionContent"] = content

        # 选项解析
        qtype_code = q.get("questionTypeCode", "")
        options = {}
        if qtype_code in ("0", "1"):
            # 单选用singleChoice，多选用mulChoice(旧版兼容multiChoice)
            cls_list = ["singleChoice"] if qtype_code == "0" else [
                "mulChoice", "multiChoice"]
            for cls_name in cls_list:
                for opt_div in soup.find_all(
                        "div", class_=lambda c: c and cls_name in c.split()):
                    letter = (opt_div.get("name") or "").strip().upper()
                    if not letter:
                        continue
                    info = opt_div.find(class_="answerInfo")
                    text = (info.get_text(" ", strip=True) if info
                            else opt_div.get_text(" ", strip=True))
                    # 图片选项OCR回填(优先answerInfo节点, 否则整个选项div)
                    ocr_opt = _ocr_from_node(
                        info if info is not None else opt_div, img_ocr)
                    if ocr_opt:
                        text = re.sub(r"\s+", "", text) + ocr_opt
                    else:
                        text = re.sub(r"\s+", "", text)
                    if text and letter not in options:
                        options[letter] = letter + text
        elif qtype_code == "3":
            # 判断题 - 对齐 Go trueOrFalseTurn
            for al in soup.find_all(
                    "div", class_=lambda c: c and "answerList" in c.split()):
                no_el = al.find(class_="No")
                info_el = al.find(class_="answerInfo")
                if no_el is not None and info_el is not None:
                    letter = no_el.get_text(strip=True)
                    text = info_el.get_text(strip=True)
                    # 图片选项OCR回填
                    ocr_opt = _ocr_from_node(info_el, img_ocr)
                    if ocr_opt:
                        text = (text + " " + ocr_opt).strip() if text else ocr_opt
                    if text:
                        if not letter:
                            letter = chr(65 + len(options))
                        options[letter] = letter + text
                    continue
                # 兼容: 单个answerList内包含多个选项块(li/子div)
                for sub in al.find_all(["li", "div"]):
                    sub_no = sub.find(class_="No")
                    sub_info = sub.find(class_="answerInfo")
                    if sub_no is not None and sub_info is not None:
                        letter = sub_no.get_text(strip=True)
                        text = sub_info.get_text(strip=True)
                        # 图片选项OCR回填
                        ocr_opt = _ocr_from_node(sub_info, img_ocr)
                        if ocr_opt:
                            text = (text + " " +
                                    ocr_opt).strip() if text else ocr_opt
                        if text:
                            if not letter:
                                letter = chr(65 + len(options))
                            options[letter] = letter + text
        elif qtype_code in ("2", "4", "5", "6"):
            # 填空/简答/名词解释/论述 - 对齐 Go: .completionList .grayTit
            for cl in soup.find_all(
                    "div", class_=lambda c: c and "completionList" in c.split()):
                gray = cl.find(class_="grayTit")
                if gray:
                    t = gray.get_text(strip=True)
                    # 图片题干/填空OCR回填
                    ocr_t = _ocr_from_node(gray, img_ocr)
                    if ocr_t:
                        t = (t + " " + ocr_t).strip() if t else ocr_t
                    if t:
                        options[t] = t
        q["options"] = [options.get(l, "")
                        for l in "ABCDEFGHIJKLMN" if options.get(l, "")]
        if not q["options"] and qtype_code in ("2", "4", "5", "6"):
            q["options"] = [v for v in options.values() if v]

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
        # 待批阅/已批阅作业: 已提交待老师批改, 无需作答（明确告知，避免用户误以为漏做）
        if status in ("待批阅", "已批阅"):
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work.get("name", ""), "】",
                      Green, f"该作业已完成提交（状态：{status}），无需重复操作，已跳过")
            continue
        if status not in ("待做", "未交", "待重做"):
            continue

        task_ref_id = work.get("taskrefId", "")
        work_name = work.get("name", "")
        enc_task = work.get("enc_task", "")
        msg_id = work.get("msgId", "0")

        # 并发去重：同一作业只处理一次（防止无限制模式下重复提交产生 enc error）
        _wk = (cache.account, course.course_id, "work", task_ref_id)
        with _work_processed_guard:
            if _wk in _work_processed:
                continue
            _work_processed.add(_wk)

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

        # 滑块验证 - 对应 Go EnterWorkAction：存在captchaCaptchaId则过滑块
        # (Go作业流程拉题不传validate，过滑块用于建立服务器端会话)
        captcha_id_val = _html_input_get(enter_body, "captchaCaptchaId")
        if captcha_id_val:
            referer_url = str(enter_resp.url) if enter_resp is not None else ""
            try:
                xxt_captcha.pass_cx_slider_captcha(
                    cache, captcha_id_val, referer_url, attempts=5,
                    log_tag=f"[{platform}][{acct}]【{course.course_name}】【{work_name}】 ")
            except Exception as e:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Red, f"作业滑块验证码处理失败: {e}")
                continue

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

        # 已结课课程的作业不支持作答(页面为只读视图/无提交表单)
        if "本课程已结课" in enter_body and "作业不支持作答" in enter_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Yellow, "本课程已结课，作业不支持作答，已跳过")
            continue

        # 进入作业(创建/激活作答记录, 2026-09-21 二次修复):
        # 必须先用完整版URL发一次"进入作业"请求(复刻浏览器 jump() 的"开始/继续
        # 答题"), 否则服务器认为无有效作答记录, 后续提交会报"无效的作答记录"。
        # 返回内容丢弃(可能是断点题), 随后正常按索引拉题。
        try:
            xxt_api.pull_work_question_api(
                cache, course.course_id, course.key,
                task_ref_id, 0, cpi_val,
                work_answer_id=answer_id, enc=enc_val,
                msg_id=msg_id, retry=3, entry=True)
        except Exception:
            pass

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
        # 图片题干/选项自动OCR解析器(整份作业复用, 带URL缓存与限流)
        _img_ocr = _make_img_ocr(
            cache, enabled=(getattr(setting.basic_setting, "ocr_image_question", 1) == 1))
        # 翻页去重集合(2026-09-21): 防止服务器翻页失效时把同一题答案重复提交
        _seen_qids = set()
        _work_aborted = False
        # 本次是否实际提交成功过任一题(用于"作业完成"事件通知: 仅通知本次实际完成的作业)
        _work_submitted = False
        for qi in range(question_total):
            # 拉取题目
            q_body, _ = xxt_api.pull_work_question_api(
                cache, course.course_id, course.key,
                task_ref_id, qi, cpi_val,
                work_answer_id=answer_id, enc=enc_val,
                msg_id=msg_id, retry=3)
            if not q_body:
                continue

            q_entity = _html_work_question_turn_entity(
                q_body, img_ocr=_img_ocr)
            q_text_raw = q_entity.get("questionContent", "")
            q_type_code = q_entity.get("questionTypeCode", "0")
            qid = q_entity.get("questionId", "")

            # 翻页校验 + 防污染(2026-09-21 重大修复):
            # 若本次拉到的题目与前面题目重复(说明服务器翻页失效固定返回第1题),
            # 绝不能重复提交同一题(否则会造成"作业提交成功但只有第1题有答案"的污染);
            # 先重试拉题, 重试仍失败则中止本作业且不做整卷提交
            _pg_tries = 0
            while qid and qid in _seen_qids and _pg_tries < 3:
                _pg_tries += 1
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Yellow,
                          f"第{qi + 1}题翻页异常(返回重复题目)，正在重试({_pg_tries}/3)...")
                time.sleep(1.5 * _pg_tries)
                q_body, _ = xxt_api.pull_work_question_api(
                    cache, course.course_id, course.key,
                    task_ref_id, qi, cpi_val,
                    work_answer_id=answer_id, enc=enc_val,
                    msg_id=msg_id, retry=3)
                if not q_body:
                    continue
                q_entity = _html_work_question_turn_entity(
                    q_body, img_ocr=_img_ocr)
                q_text_raw = q_entity.get("questionContent", "")
                q_type_code = q_entity.get("questionTypeCode", "0")
                qid = q_entity.get("questionId", "")
            if qid and qid in _seen_qids:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          BoldRed,
                          f"作业翻页失败(第{qi + 1}题仍为重复题目)，已中止本作业以避免重复提交；"
                          f"已成功提交{len(_seen_qids)}题，本次不做整卷提交，下次运行将继续")
                _work_aborted = True
                break
            if qid:
                _seen_qids.add(qid)

            # 无可作答题目(批阅视图/上传类作业/无效授权等)：
            # 快速跳过，不调用AI、不提交空enc(区分具体原因, 便于用户排查)
            if not qid and not q_text_raw:
                if "无效的权限" in q_body or "无权限" in q_body:
                    _reason = "无作答权限(可能已结课/已交卷或权限受限)"
                elif "已批阅" in q_body or "已提交" in q_body:
                    _reason = "已批阅（无需作答）"
                else:
                    _reason = "无可作答内容(批阅类/上传类/无效授权)"
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Yellow, f"该作业{_reason}，自动跳过")
                break
            q_text = q_text_raw or q_body[:500]

            # 新版作业页面: answerId/workRelationAnswerId 在题目页中,
            # enter页无此字段——补全供后续翻页/提交使用
            if not answer_id:
                answer_id = (q_entity.get("testUserRelationId", "")
                             or q_entity.get("answerId", "")
                             or q_entity.get("workRelationAnswerId", ""))

            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Yellow, f"写作业状态中，正在回答第{qi+1}题")

            # 自动答题(多答题源顺序调用)
            answer = ""
            answer_src = ""
            if cc.auto_exam in (1, 2):
                try:
                    from logic.core.answer_engine import answer_query_detail
                    # 对齐Go: 传递题型和选项
                    _wt_code_map = {'0': 'single_choice', '1': 'multiple_choice',
                                    '2': 'fill', '3': 'judge', '4': 'short',
                                    '5': 'term_explanation', '6': 'essay',
                                    '11': 'matching', '8': 'short'}
                    _wt = _wt_code_map.get(q_type_code, '')
                    _w_opts = q_entity.get('options', [])
                    answer, answer_src = answer_query_detail(
                        q_text, options=_w_opts, q_type=_wt)
                except Exception:
                    answer = ""
            elif cc.auto_exam == 3:
                try:
                    _wt3_map = {'0': 'single_choice', '1': 'multiple_choice',
                                '2': 'fill', '3': 'judge', '4': 'short',
                                '5': 'term_explanation', '6': 'essay',
                                '11': 'matching', '8': 'short'}
                    ai_body, _ = xxt_api.xxt_ai_api(
                        cache, q_text, course.course_id, course.key, cpi_val,
                        options=q_entity.get('options', []),
                        q_type=_wt3_map.get(q_type_code, ''))
                    answer = ai_body.strip() if ai_body else ""
                    if answer:
                        answer_src = "内置AI(学习通)"
                except Exception:
                    answer = ""
            if not answer:
                answer = "A" if q_type_code in ("0", "1") else (
                    "true" if q_type_code == "3" else "答案")

            # 答题来源日志: 明确标注本题由哪个题库/AI源回答成功
            _ans_src_show = answer_src or "默认"
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Yellow, f"第{qi+1}题 答题源【{_ans_src_show}】原始答案: ",
                      Default, f"{str(answer)[:80]}",
                      DarkGray, f" | 题目: {q_text.replace(chr(10), ' ')[:50]}")

            # 判断答案格式 - 对齐Go的SimilarityArraySelect逻辑
            # 忽略选项字母前缀匹配内容，AI返回对象数组/文本/字母均兼容
            options = q_entity.get("options", [])
            if q_type_code in ("0", "1"):
                # 匹配答案到选项字母
                answer_letter = ""
                if options:
                    answer_letter = _match_answer_to_options(
                        answer, options, multi=(q_type_code == "1"))
                if not answer_letter:
                    answer_letter = _extract_plain_letter(answer)
                answer = answer_letter or ("A" if q_type_code == "0" else "A")
            elif q_type_code == "3":
                # 判断题: 先匹配选项(A.对 B.错)，失败时文本判断
                judge_letter = _match_answer_to_options(
                    answer, options) if options else ""
                if judge_letter == "A":
                    judge_answer = "true"
                elif judge_letter == "B":
                    judge_answer = "false"
                else:
                    judge_answer = _normalize_judge_answer(answer)
                answer = judge_answer
            elif options and answer and q_type_code not in ("2", "4", "5", "6"):
                # 其他带选项的题型: 也尝试匹配字母
                answer_letter = _match_answer_to_options(answer, options)
                if answer_letter:
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
            # 新版页面: answerId/workRelationAnswerId 存在于题目页, 优先采用
            work_answer_id = (q_entity.get("testUserRelationId", "")
                              or q_entity.get("answerId", "")
                              or q_entity.get("workRelationAnswerId", "")
                              or answer_id)

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
                # 多空支持(2026-09-21): 题库用 ### 分隔多个空的答案, 拆分为
                # answer{qid}1..N 逐空提交, blankNum 为空的个数; 单空保持原行为
                _blanks = [b.strip() for b in str(answer).split("###")]
                _blanks = [b for b in _blanks if b != ""] or [str(answer)]
                for _bi, _bv in enumerate(_blanks, 1):
                    submit_data.append((f"answer{qid}{_bi}", _bv))
                submit_data.append((f"blankNum{qid}", f"{len(_blanks)},"))
            else:  # 简答/论述
                submit_data.append((f"answer{qid}", answer))

            submit_body, submit_resp = xxt_api.submit_work_answer_api(
                cache, submit_data, is_submit=is_submit, retry=3)
            submit_status = submit_resp.status_code if submit_resp else 0
            submit_str = submit_body or ""
            # 响应验证 - 兼容布尔true与字符串"success"两种成功标识
            submit_ok = False
            try:
                sj = safe_json_parse(submit_str)
                if sj and sj.get("status") in (True, "success"):
                    submit_ok = True
            except Exception:
                pass
            if submit_ok:
                _work_submitted = True
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Green, f"第{qi+1}题回答成功(答题源: {_ans_src_show}, 提交值: {str(answer)[:40]})，服务器返回:{submit_str[:200]}")
            else:
                # enc 失效(该作业可能已被提交，如章测已先行提交)：静默跳过
                if "enc error" in submit_str:
                    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】【", work_name, "】",
                              Green, "该作业已提交(enc已失效)，自动跳过")
                    break
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", work_name, "】",
                          Red, f"第{qi+1}题提交失败(答题源: {_ans_src_show}, status={submit_status})，服务器返回:{submit_str[:300]}")

        if _work_aborted:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Yellow, "本次作业未完成（已中止，答案已暂存），下次运行将继续处理")
        else:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", work_name, "】",
                      Green, "作业已完成")
            # 按事件实时通知: 仅"本次实际完成"(有成功提交)的作业才发送
            if _work_submitted:
                run_stats_bump(
                    ACCOUNT_TYPE_STR[PLATFORM_TYPE], user.account, "work")
                if cc.exam_auto_submit in (1, 2):
                    _notice_line = (
                        f"课程【{course.course_name}】-作业【{work_name}】已完成提交"
                        f"（状态：待批阅——等待老师批阅；若已自动批阅请以学习通页面为准）")
                else:
                    _notice_line = (
                        f"课程【{course.course_name}】-作业【{work_name}】已完成作答"
                        f"（未自动交卷模式，答案已保存）")
                send_user_event_notice(
                    setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], _notice_line)


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

    # 考试优先级排序: 待做(含限时进入的补考)最紧迫优先处理，
    # 避免被前面的长考试/交卷延时耽误而错过限时进入窗口
    _status_priority = {"待做": 0, "待重考": 1, "待重做": 2, "已完成": 3}
    exam_list = sorted(
        exam_list,
        key=lambda e: _status_priority.get(e.get("status", ""), 9)
        if isinstance(e, dict) else 9)

    for exam in exam_list:
        if not isinstance(exam, dict):
            continue
        status = exam.get("status", "")
        # 已过期/已截止/已结束考试: 明确告知(用户要求截止的任务点必须在日志中说明)
        if status in ("已过期", "已截止", "已结束", "已失效"):
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam.get("name", ""), "】",
                      Yellow, f"该考试{status}，无法参加，已跳过")
            continue
        # 待批阅/已批阅考试: 已完成提交, 无需重复操作（明确告知）
        if status in ("待批阅", "已批阅"):
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam.get("name", ""), "】",
                      Green, f"该考试已完成提交（状态：{status}），无需重复操作，已跳过")
            continue
        # 待做/待重考/待重做直接作答; 已完成需检查分数(<60且可重考则自动重做)
        if status not in ("待做", "待重考", "待重做", "已完成"):
            continue
        is_finished_exam = (status == "已完成")

        task_ref_id = exam.get("taskrefId", "")
        exam_name = exam.get("name", "")
        enc_task = exam.get("enc_task", "")
        msg_id = exam.get("msgId", "0")

        # 并发去重：同一考试只处理一次
        _wk = (cache.account, course.course_id, "exam", task_ref_id)
        with _work_processed_guard:
            if _wk in _work_processed:
                continue
            _work_processed.add(_wk)

        # 进入考试 - 对应 Go EnterExamAction
        enter_body, enter_resp = xxt_api.enter_exam_api(
            cache, task_ref_id, enc_task, course.course_id, course.key,
            str(course.cpi), retry=3)
        if not enter_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Red, "进入考试失败")
            continue

        # 检测限时进入考试的超时提示页(服务器规则: 开始后N分钟内必须进入，
        # 超时后服务器返回"不允许参加考试"提示页，拉题必然无questionId)
        if "不允许参加考试" in enter_body or "不允许参加该考试" in enter_body:
            tl_m = re.search(
                r'限时进入[：:][^<]{0,60}?(\d+)\s*分钟[^<]{0,30}不允许参加',
                enter_body)
            tl_str = f"(开始{tl_m.group(1)}分钟内必须进入)" if tl_m else ""
            begin_m = re.search(
                r'开始时间[：:][^<]*?<span[^>]*>([^<]+)</span>', enter_body)
            end_m = re.search(
                r'截止时间[：:][^<]*?<span[^>]*>([^<]+)</span>', enter_body)
            time_str = ""
            if begin_m and end_m:
                time_str = f"(开始{begin_m.group(1).strip()} 截止{end_m.group(1).strip()})"
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, f"该考试已超过限时进入时间{tl_str}{time_str}，服务器不允许参加，已跳过")
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

        # 检查重考 - 对齐 Go EnterExamAction 的 bnt_retake 处理
        # 支持重考且还有重考机会(已重考<允许重考)且分数<60时才自动重做
        # 已完成考试: 从入口页解析成绩(本次成绩/最终成绩)，<60分且可重考→自动重做
        # cxExamSwAgain=1: 只要支持重考(还有重考机会)不管分数一律强制重考
        force_re_exam = ((cc.cx_exam_sw_again or 0) == 1)
        is_re_exam = False
        re_exam_url = ""
        retake_match = re.search(
            r'本次考试允许重考[\s\S]*?<span[^>]*>(\d+)</span>次[\s\S]*?已重考[\s\S]*?<span[^>]*>(\d+)</span>次',
            enter_body)
        retake_allow = int(retake_match.group(1)) if retake_match else 0
        retake_used = int(retake_match.group(2)) if retake_match else 0
        # 分数解析(入口页"本次成绩/最终成绩"结构: <b>数字</b>分)
        score_val = None
        score_match = re.search(
            r'(?:本次成绩|最终成绩|考试成绩|得分)[\s\S]{0,200}?<b[^>]*>\s*(\d+(?:\.\d+)?)\s*</b>[\s\S]{0,10}?分',
            enter_body)
        if score_match:
            try:
                score_val = float(score_match.group(1))
            except (ValueError, TypeError):
                score_val = None
        # 重考按钮URL: 新版用href=(且在class前面)，旧版用data=，均兼容
        _retake_tag = re.search(
            r'<a\b[^>]*class=["\']bnt_retake["\'][^>]*>', enter_body)
        if _retake_tag:
            _attr = re.search(
                r'(?:href|data)=["\']([^"\']+)["\']', _retake_tag.group(0))
            if _attr:
                re_exam_url = _attr.group(1)

        if force_re_exam and retake_match and retake_used < retake_allow:
            # cxExamSwAgain=1: 支持重考且还有机会→不管分数一律强制重考
            is_re_exam = True
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow,
                      f"cxExamSwAgain=1: 考试支持重考(允许{retake_allow}次已重考{retake_used}次)，强制重考...")
        elif is_finished_exam:
            # 已完成考试: 仅分数<60且可重考时自动重做
            if score_val is None:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Green, "考试已完成(入口页未展示成绩，无法判断是否达标)，跳过")
                continue
            if score_val >= 60:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Green, f"考试已通过(成绩{score_val}分≥60)，无需重考")
                continue
            # 分数<60
            if retake_match and retake_used >= retake_allow:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Yellow,
                          f"考试未达标({score_val}分<60)但重考机会已用完(允许{retake_allow}次已重考{retake_used}次)，跳过")
                continue
            is_re_exam = True
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow,
                      f"考试未达标({score_val}分<60)且允许重考{retake_allow}次已重考{retake_used}次，自动重考...")
        elif retake_match:
            # 待做/待重考/待重做考试
            if score_val is not None and score_val >= 60:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Green,
                          f"考试分数{score_val}分(≥60)且允许重考{retake_allow}次已重考{retake_used}次，无需重考")
            elif retake_used < retake_allow:
                is_re_exam = True
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Yellow,
                          f"考试未达标(分数{score_val if score_val is not None else '未知'})且允许重考{retake_allow}次已重考{retake_used}次，自动重考...")
            else:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Yellow,
                          f"考试重考机会已用完(允许{retake_allow}次已重考{retake_used}次)，跳过重考")
        # 提取hidden fields (来自完成页)
        # 注意: 已完成考试的入口页字段名为examRelationId/answerId，
        # 待做/重做页为testPaperId/testUserRelationId，均兼容
        exam_relation_id = (_html_input_get(enter_body, "testPaperId")
                            or _html_input_get(enter_body, "examRelationId"))
        answer_id = (_html_input_get(enter_body, "testUserRelationId")
                     or _html_input_get(enter_body, "answerId"))
        cpi_val = _html_input_get(enter_body, "cpi") or str(course.cpi)

        # 如果是重考: 对齐官方页面JS顺序 restartOp → 重新进入考试
        # restartOp成功服务器会将考试重置为待做状态，重新进入拿到重做后的入口页
        if is_re_exam and exam_relation_id and answer_id:
            try:
                _client = xxt_api._build_client(
                    cache, custom_ua=xxt_api.XXTEXAMUA)
                re_resp_body, _ = _client.get(
                    f"https://mooc1-api.chaoxing.com/exam-ans/exam/phone/restartOp"
                    f"?examId={exam_relation_id}&examAnswerId={answer_id}"
                    f"&courseId={course.course_id}&classId={course.key}&source=0&code=",
                    retry=3)
                _client.close()
                re_data = safe_json_parse(re_resp_body or "")
                if re_data and re_data.get("status") is True:
                    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】【", exam_name, "】",
                              Green, "重考请求成功，考试已重置")
                    # 重新进入考试，获取重做后的入口页(含题目数/滑块参数)
                    _new_body, _new_resp = xxt_api.enter_exam_api(
                        cache, task_ref_id, enc_task, course.course_id,
                        course.key, str(course.cpi), retry=3)
                    if _new_body:
                        enter_body = _new_body
                        enter_resp = _new_resp
                        # 重新提取重做后的hidden fields
                        exam_relation_id = (_html_input_get(
                            enter_body, "testPaperId")
                            or _html_input_get(enter_body, "examRelationId")
                            or exam_relation_id)
                        answer_id = (_html_input_get(
                            enter_body, "testUserRelationId")
                            or _html_input_get(enter_body, "answerId")
                            or answer_id)
                        cpi_val = _html_input_get(
                            enter_body, "cpi") or cpi_val
                else:
                    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】【", exam_name, "】",
                              Red, f"重考请求失败，服务器返回:{str(re_resp_body or '')[:200]}")
            except Exception as e:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, f"重考请求异常: {e}")

        # 提取题目数量
        qt_match = re.search(r'共包含\s*(\d+)\s*道题目', enter_body)
        question_total = int(qt_match.group(1)) if qt_match else 0

        # 检测仅限手机APP作答/需客户端签名的考试(服务器侧硬限制,
        # 纯HTTP程序无法过原生签名，Go原版同样无法处理)
        if "只能在手机学习通APP参加" in enter_body:
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, "该考试仅限手机学习通APP作答，已跳过")
            continue

        # 滑块验证 - 对应 Go EnterExamAction：存在captchaCaptchaId则过滑块，
        # 拿到的validate传入拉试卷接口的captchavalidate参数（否则拉题被拒→提交报无权限）
        captcha_id_val = _html_input_get(enter_body, "captchaCaptchaId")
        captcha_validate = ""
        if captcha_id_val:
            referer_url = str(enter_resp.url) if enter_resp is not None else ""
            try:
                captcha_validate = xxt_captcha.pass_cx_slider_captcha(
                    cache, captcha_id_val, referer_url, attempts=5,
                    log_tag=f"[{platform}][{acct}]【{course.course_name}】【{exam_name}】 ")
            except Exception as e:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, f"考试滑块验证码处理失败: {e}")
                continue

        # 拉取考试试卷 - 对应 Go PullExamPaperHtmlApi / PullReDoExamPaperHtmlApi
        api_imei = xxt_api._IMEI
        paper_body, paper_resp = xxt_api.pull_exam_paper_api(
            cache, course.course_id, course.key,
            exam_relation_id, cpi_val,
            exam_answer_id=answer_id,
            imei=api_imei, captcha_validate=captcha_validate,
            redo=is_redo_exam, retry=3)
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
                imei=api_imei, captcha_validate=captcha_validate,
                redo=is_redo_exam, retry=3)
            if not paper_body or "访问异常" in paper_body:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, "考试访问异常，iPhone UA重试仍失败，跳过")
                xxt_api.XXTEXAMUA = xxt_api.get_ua("mobile")  # 恢复
                continue

        # 人脸识别拦截: 服务器明确提示"人脸识别对比不通过，不允许进入考试"
        # (该考试启用了考前人脸认证，纯HTTP程序无法完成真实人脸采集与比对)
        if "人脸识别对比不通过" in paper_body or (
                "人脸识别" in paper_body and "不允许进入考试" in paper_body):
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, "该考试要求人脸识别，服务器人脸比对未通过"
                              "(纯HTTP无法完成考前人脸认证)，已跳过")
            xxt_api.XXTEXAMUA = xxt_api.get_ua("mobile")
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

        # 检测需客户端签名的考试(返回开始页isStartPage=1且无enc字段):
        # 需APP客户端签名(CLIENT_FORM_SIGN)才能进入答题页。
        # 签名算法已还原(exam_sign.py, RSA PKCS1v15+APK内嵌私钥)，
        # 设备特征码登录时已确定(cache.device_flag: 配置的deviceFlag或动态生成)
        if "isStartPage" in paper_body and not enc_val:
            sign_ok = False
            try:
                device_flag = (getattr(cache, "device_flag", "") or "").strip()
                if not device_flag:
                    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】【", exam_name, "】",
                              Yellow, "该考试需手机APP客户端签名且未配置设备特征码(deviceFlag)，已跳过。"
                                      "获取方法: 手机学习通APP内打开 https://doc.micono.eu.org/tools/device 复制特征码")
                else:
                    import html as _html_mod
                    from urllib.parse import quote as _quote
                    from logic.xuexitong import exam_sign

                    # 解析开始页的 signConfig 与 faceDetection
                    sign_config = {}
                    sc_match = re.search(
                        r'id=["\']signConfig["\'][^>]*value=["\']([^"\']*)["\']',
                        paper_body)
                    if sc_match:
                        try:
                            sign_config = safe_json_parse(
                                _html_mod.unescape(sc_match.group(1))) or {}
                        except Exception:
                            sign_config = {}
                    fd_match = re.search(
                        r'id=["\']faceDetection["\'][^>]*value=["\']([^"\']*)["\']',
                        paper_body)
                    fd_val = fd_match.group(1) if fd_match else "0"

                    sig = exam_sign.compute_start_exam_sign(
                        test_user_relation_id, course.key,
                        device_flag=device_flag,
                        sign_config=sign_config or None)

                    # 模拟开始页JS跳转: phone/start + 签名参数
                    jump_url = (
                        f"https://mooc1-api.chaoxing.com/exam-ans/exam/phone/start"
                        f"?courseId={course.course_id}&classId={course.key}"
                        f"&examId={test_paper_id}&source=0"
                        f"&examAnswerId={test_user_relation_id}"
                        f"&faceDetection=1&keyboardDisplayRequiresUserAction=1"
                        f"&code=&imei={api_imei}&faceDetection={fd_val}&facekey=&sdlkey=&faceDetectionResult="
                        f"&captchavalidate={captcha_validate}&jt=0&_v={time.time()}"
                        f"&cxcid={_quote(sig['cxcid'])}&cxtime={sig['cxtime']}&signt={sig['signt']}"
                        f"&_signcode={sig['_signcode']}&_signc={sig['_signc']}&_signe={sig['_signe']}"
                        f"&signk={_quote(sig['signk'])}")
                    _client = xxt_api._build_client(
                        cache, custom_ua=xxt_api.XXTEXAMUA)
                    try:
                        sign_body, _ = _client.get(jump_url, retry=2)
                    finally:
                        _client.close()
                    if sign_body and 'id="enc"' in sign_body:
                        paper_body = sign_body
                        paper_entity = _html_exam_question_turn_entity(
                            paper_body)
                        enc_val = paper_entity.get("enc", "")
                        sign_ok = bool(enc_val)
                        if sign_ok:
                            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                                      "【", course.course_name, "】【", exam_name, "】",
                                      Green, "客户端签名验证通过，已进入考试答题页")
            except Exception as e:
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, f"客户端签名流程异常: {e}")
            if not sign_ok:
                # 恢复UA，避免影响后续其他考试的请求
                xxt_api.XXTEXAMUA = xxt_api.get_ua("mobile")
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Yellow, "该考试需手机APP客户端签名，签名未通过，已跳过")
                continue

        if not question_total:
            question_total = 1

        # 记录成功进入考试的时间戳(用于开考限时交卷的计算起点)
        exam_start_time = time.time()

        log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                  "【", course.course_name, "】【", exam_name, "】",
                  Yellow, f"正在考试中(共{question_total}题)...")

        # 逐题回答
        exam_skipped = False
        # 本次是否实际提交成功过(用于"考试完成"事件通知: 仅通知本次实际完成的考试)
        _exam_submitted = False
        _last_exam_submit_str = ""
        # 翻页去重集合(2026-09-21): 考试同样防止翻页失效导致重复提交同一题
        _exam_seen_qids = set()
        # 图片题干/选项自动OCR解析器(整场考试复用, 带URL缓存与限流)
        _img_ocr = _make_img_ocr(
            cache, enabled=(getattr(setting.basic_setting, "ocr_image_question", 1) == 1))
        for qi in range(question_total):
            # 拉取题目 - 使用 reVersionTestStartNew URL
            # 对齐 Go: relationAnswerLastUpdateTime 传试卷中的 encLastUpdateTime
            # (而非当前时间戳)，为空时回退到当前时间戳
            last_update_param = enc_last_update_time or str(
                int(time.time() * 1000))
            q_body, _ = xxt_api.pull_exam_question_api(
                cache, course.course_id, course.key,
                test_paper_id, test_user_relation_id,
                cpi_val, enc_remain_time,
                enc_val, last_update_param,
                index=qi, retry=3)
            if not q_body:
                continue

            q_entity = _html_exam_question_turn_entity(
                q_body, img_ocr=_img_ocr)
            q_text = q_entity.get("questionContent", q_body[:500])
            q_type_code = q_entity.get("questionTypeCode", "0")
            q_type_str = q_entity.get("questionTypeStr", "")
            qid = q_entity.get("questionId", "")
            # 拉题返回异常页(无questionId,如"无权限访问"信息提示页):
            # 首题就异常说明该考试入口验证未通过(缺滑块validate/人脸/签名)，直接跳过
            if qid and qid in _exam_seen_qids:
                # 翻页失效(返回重复题目): 中止本考试且不交卷, 避免重复提交污染
                log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Yellow,
                          f"考试翻页异常(第{qi+1}题返回重复题目)，已中止本考试(不交卷)，下次运行将继续")
                exam_skipped = True
                break
            if not qid:
                if "无权限访问" in q_body or "无权限" in q_body:
                    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】【", exam_name, "】",
                              Yellow, "拉题被服务器拒绝(无权限: 需人脸识别/客户端签名或入口校验未通过)，跳过该考试")
                else:
                    log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】【", exam_name, "】",
                              Red, f"第{qi+1}题拉取异常(无questionId)，跳过该考试")
                exam_skipped = True
                break
            _exam_seen_qids.add(qid)

            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, f"考试状态中，正在回答第{qi+1}题，总共{question_total}题")

            # 自动答题(多答题源顺序调用)
            answer = ""
            answer_src = ""
            if cc.auto_exam in (1, 2):
                try:
                    from logic.core.answer_engine import answer_query_detail
                    # 对齐Go: 传递题型和选项
                    _wt_code_map = {'0': 'single_choice', '1': 'multiple_choice',
                                    '2': 'fill', '3': 'judge', '4': 'short',
                                    '5': 'term_explanation', '6': 'essay',
                                    '11': 'matching', '8': 'short'}
                    _wt = _wt_code_map.get(q_type_code, '')
                    _w_opts = q_entity.get('options', [])
                    answer, answer_src = answer_query_detail(
                        q_text, options=_w_opts, q_type=_wt)
                except Exception:
                    answer = ""
            elif cc.auto_exam == 3:
                try:
                    _wt3_map = {'0': 'single_choice', '1': 'multiple_choice',
                                '2': 'fill', '3': 'judge', '4': 'short',
                                '5': 'term_explanation', '6': 'essay',
                                '11': 'matching', '8': 'short'}
                    ai_body, _ = xxt_api.xxt_ai_api(
                        cache, q_text, course.course_id, course.key, cpi_val,
                        options=q_entity.get('options', []),
                        q_type=_wt3_map.get(q_type_code, ''))
                    answer = ai_body.strip() if ai_body else ""
                    if answer:
                        answer_src = "内置AI(学习通)"
                except Exception:
                    answer = ""
            if not answer:
                answer = "A" if q_type_code in ("0", "1") else (
                    "true" if q_type_code == "3" else "答案")

            # 答题来源日志: 明确标注本题由哪个题库/AI源回答成功
            _ans_src_show = answer_src or "默认"
            log_print(INFO, f"[{platform}]", "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, f"第{qi+1}题 答题源【{_ans_src_show}】原始答案: ",
                      Default, f"{str(answer)[:80]}",
                      DarkGray, f" | 题目: {q_text.replace(chr(10), ' ')[:50]}")

            # 匹配答案到选项 - 对齐Go的SimilarityArraySelect逻辑
            # 忽略选项字母前缀匹配内容，AI返回对象数组/文本/字母均兼容
            options = q_entity.get("options", [])
            if q_type_code in ("0", "1"):
                answer_letter = ""
                if options:
                    answer_letter = _match_answer_to_options(
                        answer, options, multi=(q_type_code == "1"))
                if not answer_letter:
                    # 选项解析失败或未匹配: 尝试从答案直接提取字母
                    answer_letter = _extract_plain_letter(answer)
                answer = answer_letter or ("A" if q_type_code == "0" else "A")
            elif q_type_code == "3":  # 判断题 - 对齐Go: SimilarityArraySelect→A→"true", else→"false"
                judge_letter = _match_answer_to_options(
                    answer, options) if options else ""
                if judge_letter == "A":
                    judge_answer = "true"
                elif judge_letter == "B":
                    judge_answer = "false"
                else:
                    judge_answer = _normalize_judge_answer(answer)
                answer = judge_answer
            elif options and answer and q_type_code not in ("2", "4", "5", "6"):
                # 其他带选项的题型(如阅读理解/完形填空等): 也尝试匹配字母
                answer_letter = _match_answer_to_options(answer, options)
                if answer_letter:
                    answer = answer_letter

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
            # 处理限制提交时间的考试 - 从成功进入考试那一刻开始计算，
            # 在开考N分钟+30秒后自动交卷；若仍报不允许提交，则每1分钟重试一次直到成功
            time_match = re.search(
                r'考试(\d+)分钟内不允许提交考试', submit_str)
            if time_match:
                min_time = int(time_match.group(1))
                wait_until = exam_start_time + min_time * 60 + 30
                wait_secs = wait_until - time.time()
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Green, f"检测到考试限制开考{min_time}分钟内不允许提交，将在开考{min_time}分30秒后自动交卷...")
                if wait_secs > 0:
                    time.sleep(wait_secs)
                # 循环尝试交卷，每1分钟重试一次直到成功
                submit_body, submit_resp = xxt_api.submit_exam_answer_api(
                    cache, submit_data, is_submit=is_submit, retry=3)
                submit_str = submit_body or ""
                while True:
                    _ok = False
                    try:
                        _j = safe_json_parse(submit_str)
                        if _j and _j.get("status") in (True, "success"):
                            _ok = True
                    except Exception:
                        pass
                    if _ok:
                        break
                    if "不允许提交" in submit_str:
                        log_print(INFO, f"[{platform}]",
                                  "[", Green, acct, Default, "] ",
                                  "【", course.course_name, "】【", exam_name, "】",
                                  Yellow, "仍在开考限制时间内，1分钟后重试交卷...")
                        time.sleep(60)
                        submit_body, submit_resp = xxt_api.submit_exam_answer_api(
                            cache, submit_data, is_submit=is_submit, retry=3)
                        submit_str = submit_body or ""
                        continue
                    break
                submit_status = submit_resp.status_code if submit_resp else 0

            if "考试时间已用完" in submit_str:
                # 作答时间耗尽: 对齐官方"作答时间耗尽，试卷已提交"行为
                # 若开启自动交卷，则正式交卷(tempSave=false)完成考试，
                # 否则视为跳过(下次运行将继续尝试)
                if cc.exam_auto_submit in (1, 2):
                    try:
                        fin_body, _ = xxt_api.submit_exam_answer_api(
                            cache, submit_data, is_submit=True, retry=3)
                        # 交卷后恢复UA - 对齐 Go SubmitExamAnswerAction
                        xxt_api.XXTEXAMUA = xxt_api.get_ua("mobile")
                        fin_str = fin_body or ""
                        fin_ok = False
                        fj = safe_json_parse(fin_str)
                        if fj and fj.get("status") in (True, "success"):
                            fin_ok = True
                        if fin_ok:
                            log_print(INFO, f"[{platform}]",
                                      "[", Green, acct, Default, "] ",
                                      "【", course.course_name, "】【", exam_name, "】",
                                      Green, f"作答时间耗尽，已自动交卷，服务器返回:{fin_str[:200]}")
                            break
                        log_print(INFO, f"[{platform}]",
                                  "[", Green, acct, Default, "] ",
                                  "【", course.course_name, "】【", exam_name, "】",
                                  Red, f"作答时间耗尽，交卷失败，服务器返回:{fin_str[:300]}")
                        exam_skipped = True
                        break
                    except Exception:
                        pass
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, "考试时间已用完，已自动跳过")
                exam_skipped = True
                break

            # 响应验证 - 兼容布尔true与字符串"success"两种成功标识
            exam_submit_ok = False
            try:
                ej = safe_json_parse(submit_str)
                if ej and ej.get("status") in (True, "success"):
                    exam_submit_ok = True
            except Exception:
                pass
            if exam_submit_ok:
                _exam_submitted = True
                _last_exam_submit_str = submit_str
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Green, f"第{qi+1}题回答成功(答题源: {_ans_src_show}, 提交值: {str(answer)[:40]})，服务器返回:{submit_str[:200]}")
            else:
                # enc 失效(该考试可能已被提交)：静默跳过
                if "enc error" in submit_str:
                    log_print(INFO, f"[{platform}]",
                              "[", Green, acct, Default, "] ",
                              "【", course.course_name, "】【", exam_name, "】",
                              Green, "该考试已提交(enc已失效)，自动跳过")
                    exam_skipped = True
                    break
                log_print(INFO, f"[{platform}]",
                          "[", Green, acct, Default, "] ",
                          "【", course.course_name, "】【", exam_name, "】",
                          Red, f"第{qi+1}题提交失败(答题源: {_ans_src_show}, status={submit_status})，服务器返回:{submit_str[:300]}")

        if exam_skipped:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Yellow, "考试未完成(已跳过，下次运行将继续尝试)")
        else:
            log_print(INFO, f"[{platform}]",
                      "[", Green, acct, Default, "] ",
                      "【", course.course_name, "】【", exam_name, "】",
                      Green, "考试已完成")
            # 按事件实时通知: 仅"本次实际完成"的考试才发送
            if _exam_submitted:
                run_stats_bump(
                    ACCOUNT_TYPE_STR[PLATFORM_TYPE], user.account, "exam")
                _notice_line = (
                    f"课程【{course.course_name}】-考试【{exam_name}】已完成")
                _sc = re.search(r"(\d+(?:\.\d+)?)分",
                                _last_exam_submit_str or "")
                if _sc:
                    _notice_line += f"（成绩：{_sc.group(1)}分）"
                else:
                    _notice_line += ("（已交卷；若含主观题将处于待批阅——等待老师批阅，"
                                     "成绩可在学习通查看）")
                send_user_event_notice(
                    setting, user, ACCOUNT_TYPE_STR[PLATFORM_TYPE], _notice_line)
