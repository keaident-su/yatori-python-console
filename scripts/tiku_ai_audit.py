# -*- coding: utf-8 -*-
"""学习通内置AI 题库批量核对与更正(试点工具, 2026-10-28)

用途
----
逐题把「题面」交给学习通内置AI(auto_exam=3 同一条 xxt_ai_api 链路)重新作答,
与本地题库 questions_answers.json 里现有答案比对:
    - 判断题 : 归一化(对/正确/√/true 与 错/错误/×/false)后比较, 不一致多次投票后更正
    - 填空题 : 只出报告不写库(实测AI返回多为长篇解释/同义改写, 自动改会改坏)
    - 选择题 : 题库无选项列表可比 -> 只出报告, 永不写库
一致 / 无法判定 / AI 返回无效 -> 保持原值不动。

保护机制(全部复用现成实现, 不另造轮子)
--------------------------------------
- 读写 : logic.core.answer_engine.LocalTikuCache
         (仅更正已存在键 / 原子替换 / 每日自动备份 / 占位词拦截 / 外部修改检测)
- 调用 : logic.xuexitong.api.xxt_ai_api (内置AI, 内部含参数页 + 流式JSON校验重试)
- 登录 : logic.xuexitong.part._login_action + _generate_device_flag
- 参数 : logic.xuexitong.part._pull_course_action (courseId/classId/cpi)
- 解析 : logic.xuexitong.part._normalize_ai_answer_candidates / _similarity

用法示例(cwd = yatori-python-console)
------------------------------------
    # 1) 试点 dry-run(默认, 不写库): 25 判断题
    python scripts/tiku_ai_audit.py --types judge --limit 25
    # 2) 试点 dry-run: 25 填空题
    python scripts/tiku_ai_audit.py --types fill --limit 25
    # 3) 确认无误后正式写入(继续同一区间)
    python scripts/tiku_ai_audit.py --types judge --limit 25 --apply --resume
    # 4) 指定题库 / 分页区间 / 断点续跑
    python scripts/tiku_ai_audit.py --path questions_answers.json --start 1000 --end 1100 --apply --resume

注意
----
- 默认 --dry-run; 必须显式 --apply 才会调用 update_many 写库。
- 内置AI链路失败(登录/参数页/TCaptcha)会如实打印原因并停止, 不换源、不用默认答案顶替。
- xxt_ai_api 内部按 courseId 加锁: 单课程时 --workers>1 也无法真并发(仅多课程账号有意义)。
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time

# ============ 路径引导(与 scripts/ 下其它脚本一致) ============
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

import urllib3  # noqa: E402

urllib3.disable_warnings()

# 控制台编码兼容: 题库里含 ℃ 类生僻字符, GBK 控制台直接 print 会抛
# UnicodeEncodeError 并中断整轮核对 -> 统一改为 utf-8 + errors=replace
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config.config import read_config, normalize_account_type  # noqa: E402
from logic.core.answer_engine import LocalTikuCache, _norm_question  # noqa: E402
from logic.core.ai_client import _extract_answer_value  # noqa: E402
from logic.xuexitong.models import XueXiTUserCache  # noqa: E402
from logic.xuexitong import part as P  # noqa: E402
from logic.xuexitong.api import xxt_ai_api, _xxt_ai_inform_api  # noqa: E402

# ============ 常量 ============

# 题型 -> 内置AI的 q_type(集中在此, 试跑后如需调整只改这里)
QTYPE_MAP = {"judge": "judge", "fill": "short",
             "choice": "short", "other": "short"}

# 允许自动更正(写库)的题型。
# 2026-10-28 实测结论: 填空题AI返回多为长篇解释/同义改写(同理心阶段->共情阶段),
# 自动更正会把正确项改成语义相近但匹配不到原选项的文字 -> 填空题降为只报告。
WRITABLE_TYPES = ("judge",)

JUDGE_TRUE = {"对", "正确", "√", "true", "t"}
JUDGE_FALSE = {"错", "错误", "×", "false", "f"}

# AI 无效答案特征(空/占位/推脱/解释性文字)
_PLACEHOLDER_KW = (
    "很抱歉", "未找到", "没有找到", "搜索不到", "无答案", "答案", "略",
    "无法确定", "无法判断", "无法回答", "不知道", "不确定", "不能确定",
    "以上", "选项", "解析",
)

# 题面空白标记 / 选题线索词 / 句读标点 / 纯字母答案
_BLANK_RE = re.compile(r"[_\uFF3F]{2,}|\(\s*\)|\uFF08\s*\uFF09")
_HINT_RE = re.compile(
    r"下列|哪项|以下|不属于|正确的是|选择|选项|均正确|以上")
_SENT_PUNCT_RE = re.compile(r"[\u3002\uFF0C\uFF1B\uFF01\uFF1F]")
_LETTER_RE = re.compile(r"[A-Ha-h]{1,8}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 过短题面(残句/乱码)缺上下文, 交给AI只能猜 -> 不当判断题写库
MIN_Q_LEN = 4
_TRAILING_PUNCT = " \t\r\n。.，,；;！!？?\"'“”‘’()（）"

DEFAULT_TYPES = "judge,fill"


# ============ 通用小工具 ============

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _abs(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))


def _file_sig(path: str):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _atomic_write(path: str, data: str):
    """原子写文本(tmp + replace), 用于状态/报告, 不影响题库文件"""
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f"{path}.{os.getpid()}_{os.urandom(3).hex()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    for _ in range(3):
        try:
            os.replace(tmp, path)
            return True
        except OSError:
            time.sleep(0.2)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def _find_config() -> str:
    for cand in (os.path.join(BASE, "config.yaml"),
                 os.path.join(BASE, "config", "config.yaml")):
        if os.path.exists(cand):
            return cand
    return ""


def _load_cfg():
    p = _find_config()
    if not p:
        return None
    try:
        return read_config(p)
    except Exception as e:
        print(f"[预检] 读取配置失败({p}): {e}")
        return None


def _resolve_account(cfg, account: str, password: str):
    """账号解析: 优先命令行; 否则取配置内第一个学习通账号"""
    pwd = (password or "").strip()
    acc = (account or "").strip()
    users = list(getattr(cfg, "users", []) or []) if cfg else []
    if acc:
        if not pwd:
            for u in users:
                if str(getattr(u, "account", "") or "") == acc:
                    pwd = str(getattr(u, "password", "") or "")
                    break
        return acc, pwd
    for u in users:
        if normalize_account_type(getattr(u, "account_type", "")) == "XUEXITONG":
            return (str(getattr(u, "account", "") or ""),
                    str(getattr(u, "password", "") or ""))
    return "", ""


def _configured_cache_path(cfg) -> str:
    try:
        p = str(getattr(cfg.setting.answer_setting,
                        "local_cache_path", "") or "").strip()
        if p:
            return p
    except Exception:
        pass
    return "questions_answers.json"


# ============ 题型分类与答案归一化 ============

def judge_bool(text):
    """判断题答案 -> True/False/None(无法判定)"""
    s = (text or "").strip().strip(_TRAILING_PUNCT).lower()
    if not s:
        return None
    if s in JUDGE_TRUE:
        return True
    if s in JUDGE_FALSE:
        return False
    return None


def judge_out(old_answer: str, value: bool) -> str:
    """把布尔结果写回成与旧答案同词族的形式(不影响提交时的判断题归一化)"""
    o = (old_answer or "").strip()
    ol = o.lower()
    if ol in ("true", "false"):
        return "true" if value else "false"
    if o in ("T", "F"):
        return "T" if value else "F"
    if o in ("正确", "错误"):
        return "正确" if value else "错误"
    return "对" if value else "错"


def _has_inner_blank(question: str) -> bool:
    """题面中间是否有空白标记(句尾的 （）/()不算)

    用于排除一类脏数据: 填空题的答案被人存成了“对/错”,
    若当判断题去问AI只能得到另一串“对/错”, 无论如何都是假改动。
    """
    s = (question or "").rstrip(" \t\u3000（）()")
    return bool(_BLANK_RE.search(s))


def classify(question: str, answer: str) -> str:
    """按答案形态+题面特征推断题型: judge / fill / choice / other"""
    a = (answer or "").strip()
    q = question or ""
    if not a:
        return "other"
    # 无中文(英语阅读/听力判断等)或题面过短: 缺上下文, AI 只能靠猜, 只报告
    if not _CJK_RE.search(q) or len(_norm_question(q)) < MIN_Q_LEN:
        return "other"
    if judge_bool(a) is not None:
        # 答案虽是判断词, 但题面中间带空位 -> 大概率是填空题存错了答案, 不当判断题改
        return "other" if _has_inner_blank(question) else "judge"
    if _LETTER_RE.fullmatch(a):
        return "choice"
    if (_BLANK_RE.search(q)
            and len(a) <= 12
            and not _SENT_PUNCT_RE.search(a)
            and not _HINT_RE.search(q)):
        return "fill"
    return "other"


def _clean_ai_text(text: str) -> str:
    s = (text or "").strip()
    s = s.strip('"').strip("'").strip("“”‘’").strip()
    return s.strip()


def _parse_ai_elements(raw: str):
    """解析内置AI返回的 JSON 数组(兼容 ["x"] / [{"name":"x"}] / 纯文本)"""
    text = (raw or "").strip()
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.DOTALL)
    part = m.group() if m else text
    try:
        data = json.loads(part)
    except Exception:
        one = _clean_ai_text(text)
        return [one] if one else []
    if isinstance(data, list):
        out = []
        for it in data:
            v = _extract_answer_value(it)
            v = _clean_ai_text(str(v))
            if v:
                out.append(v)
        return out
    if isinstance(data, dict):
        v = _clean_ai_text(str(_extract_answer_value(data)))
        return [v] if v else []
    v = _clean_ai_text(str(data))
    return [v] if v else []


def _pick_answer(raw: str, qtype: str, old_answer: str) -> str:
    """从AI返回里取一个可用的答案文本; 多元素且无法确定 -> 空(视为无效)"""
    elems = _parse_ai_elements(raw)
    if not elems:
        return ""
    if len(elems) == 1:
        return elems[0]
    if qtype == "judge":
        return elems[0]
    # 多空填空: 旧答案用 # / ### 分隔时才允许拼接, 否则视为歧义
    if "#" in (old_answer or ""):
        sep = "###" if "###" in old_answer else "#"
        return sep.join(elems)
    return ""


def ai_valid(text: str, qtype: str, question: str, old_answer: str):
    """AI 答案有效性判定; 不通过返回 None"""
    s = _clean_ai_text(text).strip(_TRAILING_PUNCT).strip()
    if not s:
        return None
    if re.fullmatch(r"[\?？。.、，,！!：:；;~～ \-_]+", s):
        return None
    limit = {"judge": 60, "fill": 20}.get(qtype, 60)
    if len(s) > limit:
        return None
    for kw in _PLACEHOLDER_KW:
        if kw in s:
            return None
    if qtype == "judge":
        return s if judge_bool(s) is not None else None
    if qtype not in WRITABLE_TYPES:
        # 非写库题型(填空/选择/其它): 仅用于报告, 不做严苛拦截
        return s
    # 填空(仅当它重新被纳入写库题型时生效): 严禁整句/解释/与题面几乎重合
    if _SENT_PUNCT_RE.search(s):
        return None
    nq, ns = _norm_question(question), _norm_question(s)
    # 与题面同构/包含题面骨架(AI把整句当答案回抛)一律视为无效:
    # 题库答案应只是空位内容, 写回整句会导致答题时匹配不到选项/空格
    if nq and ns:
        if nq == ns or nq in ns or _similarity(ns, nq) >= 0.95:
            return None
        # 首尾骨架重合≥4字 => 典型的"把整句抠空又填回"
        p = 0
        while p < min(len(nq), len(ns)) and nq[p] == ns[p]:
            p += 1
        sfx = 0
        while (sfx < min(len(nq), len(ns)) - p
               and nq[-1 - sfx] == ns[-1 - sfx]):
            sfx += 1
        if p + sfx >= 4:
            return None
    if "#" in (old_answer or "") and "#" not in s:
        return None
    return s


def _similarity(a: str, b: str) -> float:
    """复用 logic.xuexitong.part 的相似度实现"""
    try:
        return float(P._similarity(a, b))
    except Exception:
        return 0.0


def same_answer(qtype: str, old: str, new: str) -> bool:
    """答案一致性: 判断题按布尔, 填空题按归一化文本+高相似"""
    if qtype == "judge":
        bo, bn = judge_bool(old), judge_bool(new)
        return (bo is not None and bn is not None and bo == bn)
    no, nn = _norm_question(old), _norm_question(new)
    if not no or not nn:
        return False
    # 包含关系视为一致: 防止把 "定义" -> "定义阶段（Define）" 这类
    # 纯格式/后缀扩写当成错题更正(会直接导致答题时匹配不到原答案)
    if no in nn or nn in no:
        return True
    return _similarity(no, nn) >= 0.9


# ============ 登录 / 课程参数 / 内置AI询问 ============

def login_and_courses(args):
    """登录学习通 + 拉课程; 返回 (cache, courses) 或抛异常"""
    cfg = _load_cfg()
    account, password = _resolve_account(cfg, args.account, args.password)
    if not account or not password:
        raise RuntimeError("未找到可用的学习通账号(请在 --account/--password 指定)")
    print(f"[预检] 使用学习通账号: {account}")
    cache = XueXiTUserCache(account=account, password=password)
    cache.device_flag = P._generate_device_flag()
    err = P._login_action(cache)
    if err:
        raise RuntimeError(f"登录失败: {err}")
    print("[预检] 登录成功, 正在拉取课程列表...")
    courses = P._pull_course_action(cache) or []
    usable = [c for c in courses
              if str(getattr(c, "course_id", "") or "")
              and str(getattr(c, "key", "") or "")
              and str(getattr(c, "cpi", "") or "")]
    # 优先普通课程(tsjy 通识课也能取参, 但放后面优先选)
    usable.sort(key=lambda c: bool(getattr(c, "is_tsjy", False)))
    if args.course_id:
        want = str(args.course_id)
        usable = [c for c in usable if str(c.course_id) == want]
    if not usable:
        raise RuntimeError("未找到可用于取参的课程(courseId/classId/cpi 缺失)")
    print(f"[预检] 可用课程 {len(usable)} 门, 首选: "
          f"{usable[0].course_name}(courseId={usable[0].course_id}, "
          f"classId={usable[0].key}, cpi={usable[0].cpi})")
    return cache, usable


def ask_ai(cache, course, question: str, qtype: str):
    """调用内置AI; 返回 (raw_answer, err)"""
    try:
        ans, err = xxt_ai_api(
            cache, question,
            str(course.course_id), str(course.key), str(course.cpi),
            options=None, q_type=QTYPE_MAP.get(qtype, ""))
        return (ans or ""), err
    except Exception as e:  # 网络/解析异常
        return "", e


def diagnose_ai(cache, course) -> str:
    """预检失败时的诊断(参数页层面, 用于判定是否被风控/验证码拦截)"""
    try:
        html = _xxt_ai_inform_api(
            cache, str(course.key), str(course.course_id),
            str(course.cpi), retry=1)
    except Exception as e:
        return f"参数页请求异常: {e}"
    if not html:
        return "参数页拉取为空(网络超时或登录态失效)"
    low = html.lower()
    if "captcha" in low or "验证码" in html or "滑块" in html:
        return "参数页含验证码/风控字样(疑似 TCaptcha 拦截)"
    if "cozeEnc" not in html:
        return "参数页缺少 cozeEnc(登录态可能失效或被平台拦截)"
    return "参数页正常, 但AI回答未通过解析(可能模型返回格式异常)"


def preflight(cache, course) -> bool:
    """探针题: 确保内置AI链路真的可用"""
    probe_q = "1+1=2。（ ）"
    print("[预检] 内置AI探针题: 1+1=2。（ ）")
    raw, err = ask_ai(cache, course, probe_q, "judge")
    if err:
        print(f"[预检] 内置AI链路不可用: 内置AI调用异常 -> {err}")
        print(f"[预检] 诊断: {diagnose_ai(cache, course)}")
        return False
    picked = _pick_answer(raw, "judge", "")
    val = ai_valid(picked, "judge", probe_q, "")
    if val is None:
        print(f"[预检] 内置AI链路不可用: 探针回答无效 "
              f"(原始返回={(raw or '')[:120] !r})")
        print(f"[预检] 诊断: {diagnose_ai(cache, course)}")
        return False
    print(f"[预检] 内置AI可用, 探针回答: {val} (判定="
          f"{'正确' if judge_bool(val) else '错误'})")
    return True


# ============ 单题核对(询问 -> 校验 -> 比对 -> 投票) ============

def audit_one(q_text: str, old_answer: str, qtype: str, cache, course,
              votes: int):
    """核对一题; 返回 item dict(不写库)"""
    item = {
        "time": _now(), "question": q_text, "type": qtype,
        "old_answer": old_answer, "new_answer": "", "ai_raw": "",
        "ai_all": [], "votes": 0, "similarity": None,
        "status": "failed", "note": "",
    }

    def _ask_once():
        raw, err = ask_ai(cache, course, q_text, qtype)
        if err:
            item["note"] = f"调用异常: {str(err)[:120]}"
            return None, False
        item["ai_raw"] = item["ai_raw"] or (raw or "")
        picked = _pick_answer(raw, qtype, old_answer)
        val = ai_valid(picked, qtype, q_text, old_answer)
        if val is None:
            item["ai_all"].append(f"<invalid>{(raw or '')[:60]}")
            return None, True
        item["ai_all"].append(val)
        return val, True

    first, ok = _ask_once()
    if first is None:
        item["status"] = "skipped_invalid" if ok else "failed"
        return item

    item["votes"] = 1
    if same_answer(qtype, old_answer, first):
        item["status"] = "same"
        item["note"] = "AI与旧值一致"
        item["new_answer"] = old_answer
        return item
    if qtype not in WRITABLE_TYPES:
        # 选择题/其它: 题库无选项文本可比, 只出报告不改库
        item["status"] = "report_only"
        item["new_answer"] = first
        item["note"] = "无选项文本可比, 仅报告(不写库)"
        item["similarity"] = round(
            _similarity(_norm_question(old_answer), _norm_question(first)), 3)
        return item

    # 不一致 -> 追加投票
    extra = []
    for _ in range(max(0, int(votes))):
        v, ok2 = _ask_once()
        item["votes"] += 1
        if v is not None:
            extra.append(v)
        if not ok2:
            item["status"] = "failed"
            item["note"] = "投票阶段调用异常"
            return item

    pool = [first] + extra
    new_bool, old_hit, best_raw = None, 0, ""
    if qtype == "judge":
        new_bool = not judge_bool(old_answer)
        hit = sum(1 for v in pool if judge_bool(v) == new_bool)
        old_hit = sum(1 for v in pool if judge_bool(v)
                      == judge_bool(old_answer))
    else:
        # 投票比对同样用 same_answer(含包含关系/高相似判定), 避免把
        # "定义" vs "定义阶段（Define）" 这类同义扩写投成"新答案"
        old_hit = sum(1 for v in pool if same_answer(qtype, old_answer, v))
        hit_map = {}
        for v in pool:
            if same_answer(qtype, old_answer, v):
                continue
            k = _norm_question(v)
            if not k:
                continue
            hit_map.setdefault(k, [0, v])
            hit_map[k][0] += 1
        hit, best_raw = 0, ""
        for _k, (cnt, rawv) in hit_map.items():
            if cnt > hit:
                hit, best_raw = cnt, rawv

    # 投票必须全票一致才改: 2026-10-28 实测 2/3 票的改动假阳性明显偏高,
    # 故默认需要 len(pool) == 1 + votes 全部一致(至少2票)
    need = max(2, 1 + max(0, int(votes)))
    if hit >= need and hit > old_hit:
        if qtype == "judge":
            item["new_answer"] = judge_out(old_answer, new_bool)
        else:
            item["new_answer"] = best_raw
        item["status"] = "changed"
        item["note"] = f"AI {hit}/{len(pool)} 票一致, 旧值 {old_hit} 票"
        if qtype == "fill":
            item["similarity"] = round(
                _similarity(_norm_question(old_answer),
                            _norm_question(item["new_answer"])), 3)
    else:
        item["status"] = "uncertain"
        item["new_answer"] = old_answer
        item["note"] = f"投票不足(hit={hit}, old={old_hit}, need={need}), 保持原值"
    return item


# ============ 候选筛选 ============

def build_candidates(cache, types, scan_limit: int):
    """从题库生成候选 [(题面, 旧答案, 题型), ...](只读)"""
    cache.load()
    if getattr(cache, "_load_failed", False):
        raise RuntimeError("题库文件读取失败(已禁止写入), 请先修复题库文件")
    with cache._lock:
        pairs = list(cache._data.items())
    if scan_limit and scan_limit > 0:
        pairs = pairs[:scan_limit]
    out = []
    for q, a in pairs:
        t = classify(q, a)
        if t in types:
            out.append((q, a, t))
    return out


# ============ 状态与报告 ============

class State(object):
    """断点状态(与题库文件分离, 原子写)"""

    def __init__(self, path: str, tiku_path: str, types):
        self.path = path
        self.data = {"tiku_path": tiku_path, "types": list(types),
                     "done": {}, "updated": ""}

    def load(self, tiku_path: str, types):
        if not os.path.exists(self.path):
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"[续跑] 状态文件读取失败({self.path}): {e}, 按全新运行处理")
            return False
        if not isinstance(d, dict):
            return False
        if str(d.get("tiku_path", "")) != tiku_path:
            print("[续跑] 状态文件对应的是其它题库路径, 已忽略")
            return False
        if list(d.get("types") or []) != list(types):
            print("[续跑] 状态文件的题型集合不同, 已忽略")
            return False
        self.data = d
        self.data.setdefault("done", {})
        return True

    def done_record(self, q):
        return self.data["done"].get(q)

    def mark(self, q, old_answer, status):
        self.data["done"][q] = {"old": old_answer, "status": status,
                                "ts": _now()}

    def save(self):
        self.data["updated"] = _now()
        try:
            _atomic_write(self.path,
                          json.dumps(self.data, ensure_ascii=False))
        except Exception as e:
            print(f"[续跑] 状态写入失败: {e}")


class Reporter(object):
    """逐题审计日志 + JSON/CSV 报告"""

    def __init__(self, out_dir: str, ts: str):
        self.dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.ts = ts
        self.log_path = os.path.join(out_dir, f"audit_{ts}.log")
        self.items = []

    def log(self, item):
        self.items.append(item)
        line = (f"{item['time']} | {item['type']} | 判定={item['status']} | "
                f"票={item['votes']} | 相似度={item['similarity']} | "
                f"题={item['question'][:80]!r} | 旧={item['old_answer'][:40]!r} | "
                f"新={str(item['new_answer'])[:40]!r} | "
                f"AI={str(item['ai_raw'])[:120]!r} | 注={item['note']}")
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def write(self, meta: dict, summary: dict):
        jp = os.path.join(self.dir, f"report_{self.ts}.json")
        cp = os.path.join(self.dir, f"report_{self.ts}.csv")
        payload = {"meta": meta, "summary": summary, "items": self.items}
        _atomic_write(jp, json.dumps(payload, ensure_ascii=False, indent=2))
        try:
            with open(cp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["time", "question", "type", "old_answer",
                            "new_answer", "ai_raw", "votes", "similarity",
                            "status", "note"])
                for it in self.items:
                    w.writerow([it["time"], it["question"], it["type"],
                                it["old_answer"], it["new_answer"],
                                it["ai_raw"], it["votes"], it["similarity"],
                                it["status"], it["note"]])
        except Exception as e:
            print(f"[报告] CSV 写入失败: {e}")
        return jp, cp


def _print_summary(stats: dict):
    print("\n========== 汇总统计 ==========")
    rows = [
        ("候选总数", stats.get("candidates", 0)),
        ("已核对", stats.get("audited", 0)),
        ("改动", stats.get("changed", 0)),
        ("一致", stats.get("same", 0)),
        ("仅报告(不写库)", stats.get("report_only", 0)),
        ("跳过(AI无效)", stats.get("skipped_invalid", 0)),
        ("待定(投票不一致)", stats.get("uncertain", 0)),
        ("失败", stats.get("failed", 0)),
        ("续跑跳过", stats.get("skipped_resumed", 0)),
        ("已写入", stats.get("applied", 0)),
        ("写入失败", stats.get("flush_fail", 0)),
    ]
    for k, v in rows:
        print(f"  {k:<18}{v}")
    if stats.get("aborted"):
        print(f"  中止原因          {stats['aborted']}")


# ============ 主流程 ============

def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="学习通内置AI 题库批量核对与更正(默认 dry-run, 不写库)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="说明: xxt_ai_api 内部按 courseId 加锁; 单课程时 --workers>1 "
               "不会提升速度(仅多课程账号有意义)。\n"
               "默认只跑 --limit 50 条, 全量请显式给区间并自行评估耗时/风控。")
    ap.add_argument("--path", default="",
                    help="题库文件路径(默认取 config 的 localCachePath)")
    ap.add_argument("--account", default="",
                    help="学习通账号(默认取 config 内第一个 XUEXITONG)")
    ap.add_argument("--password", default="", help="学习通密码(与 --account 配套)")
    ap.add_argument("--course-id", default="",
                    help="指定课程 courseId(默认用第一门可用课程)")
    ap.add_argument("--types", default=DEFAULT_TYPES,
                    help="参与询AI的题型(逗号分隔): judge,fill,choice,other; "
                         f"默认 {DEFAULT_TYPES}(choice/other 只出报告不写库)")
    ap.add_argument("--limit", type=int, default=50,
                    help="本次最多核对条数(默认50; 0=不限)")
    ap.add_argument("--start", type=int, default=0, help="候选列表起始下标(含, 默认0)")
    ap.add_argument("--end", type=int, default=0, help="候选列表结束下标(不含, 0=不限)")
    ap.add_argument("--scan-limit", type=int, default=0,
                    help="最多扫描多少条原始记录(0=全扫, 默认0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只出报告不写库(默认行为, 可省略)")
    ap.add_argument("--apply", action="store_true",
                    help="正式写入题库(调用 update_many)")
    ap.add_argument("--resume", action="store_true", help="按状态文件断点续跑")
    ap.add_argument("--state", default="",
                    help="状态文件路径(默认 <report-dir>/state_<hash>.json)")
    ap.add_argument("--report-dir", default=os.path.join(BASE, "logs", "tiku_ai_audit"),
                    help="报告/日志目录")
    ap.add_argument("--sleep-min", type=float,
                    default=1.0, help="每题最小停顿秒(默认1.0)")
    ap.add_argument("--sleep-max", type=float,
                    default=2.5, help="每题最大停顿秒(默认2.5)")
    ap.add_argument("--workers", type=int, default=1,
                    help="并发线程数(默认1; 受课程锁限制)")
    ap.add_argument("--votes", type=int, default=2,
                    help="不一致时追加询问次数(默认2=最多3次)")
    ap.add_argument("--fill-qtype", default="fill",
                    choices=("fill", "short", "cloze"),
                    help="填空题询AI的提示词类型(默认fill); 填空已降为只报告, "
                         "该参数仅影响报告里的AI原文")
    ap.add_argument("--max-fail", type=int, default=5,
                    help="连续失败上限(默认5), 达到即中止")
    ap.add_argument("--max-change-ratio", type=float, default=0.30,
                    help="变更率熔断阈值(默认0.30), 超过则停止写入")
    ap.add_argument("--flush-every", type=int,
                    default=20, help="每多少条改动落盘一次(默认20)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.apply and args.dry_run:
        print("[参数] --apply 与 --dry-run 互斥, 请只选一个")
        return 2
    # 默认 dry-run: 只有显式 --apply 才写库
    dry_run = not args.apply
    QTYPE_MAP["fill"] = str(args.fill_qtype or "fill")
    types = [t.strip() for t in str(args.types or "").split(",") if t.strip()]
    if not types:
        types = list(DEFAULT_TYPES.split(","))
    bad = [t for t in types if t not in ("judge", "fill", "choice", "other")]
    if bad:
        print(f"[参数] 未知题型: {bad}")
        return 2

    cfg = _load_cfg()
    tiku_path = _abs(args.path or _configured_cache_path(cfg))
    if not os.path.exists(tiku_path):
        print(f"[预检] 题库文件不存在: {tiku_path}")
        return 2
    sig_before = _file_sig(tiku_path)
    print(f"[预检] 题库文件: {tiku_path}")
    print(f"[预检] 模式: {'DRY-RUN(不写库)' if dry_run else 'APPLY(会写入题库)'} | "
          f"题型: {types} | limit={args.limit} start={args.start} end={args.end}")

    cache = LocalTikuCache(tiku_path, enable=1)
    try:
        candidates = build_candidates(cache, set(types), args.scan_limit)
    except Exception as e:
        print(f"[预检] 题库读取失败: {e}")
        return 2
    print(f"[预检] 题库总条数 {cache.count}, 命中题型候选 {len(candidates)} 条")

    # 区间/上限
    start = max(0, int(args.start))
    end = int(args.end) if int(args.end) > 0 else len(candidates)
    picked = candidates[start:end]
    if args.limit and args.limit > 0:
        picked = picked[:args.limit]
    if not picked:
        print("[预检] 区间内没有候选题目, 退出")
        return 0
    print(f"[预检] 本次待核对 {len(picked)} 条 "
          f"(候选下标 {start}~{start + len(picked) - 1})")

    # 登录 + 课程 + 探针(失败即停, 零写入)
    try:
        cache_auth, courses = login_and_courses(args)
    except Exception as e:
        print(f"[预检] {e}")
        return 3
    if not preflight(cache_auth, courses[0]):
        print("[预检] 内置AI链路不可用, 已停止(未产生任何题库写入)")
        return 4

    ts = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.report_dir, exist_ok=True)
    reporter = Reporter(args.report_dir, ts)
    h = hashlib.md5(tiku_path.encode("utf-8")).hexdigest()[:8]
    # 状态文件名带上区间: 否则换一个 --start 跑同一题型会把上一个区间的进度覆盖
    state_path = args.state or os.path.join(
        args.report_dir,
        f"state_{'_'.join(types)}_{h}_{start}-{end}.json")
    state = State(state_path, tiku_path, types)
    resumed = False
    if args.resume:
        resumed = state.load(tiku_path, types)
        print(f"[续跑] 状态文件 {state_path} "
              f"{'已加载, 已完成 ' + str(len(state.data.get('done') or {})) + ' 条' if resumed else '不存在/不匹配, 本次从零开始'}")

    stats = {"candidates": len(picked), "audited": 0, "changed": 0,
             "same": 0, "report_only": 0, "skipped_invalid": 0,
             "uncertain": 0, "failed": 0, "skipped_resumed": 0,
             "applied": 0, "aborted": "", "flush_fail": 0}
    pending = []          # [(题, 新答案)]
    abort = {"flag": ""}
    fail_streak = {"n": 0}
    t0 = time.time()

    def ratio_exceeded() -> bool:
        a = stats["audited"]
        if a < 20:
            return False
        return stats["changed"] / max(1, a) > float(args.max_change_ratio)

    def flush() -> bool:
        """把待写改动交给 LocalTikuCache.update_many 落盘"""
        if not pending:
            state.save()
            return True
        if dry_run:
            pending.clear()
            state.save()
            return True
        if ratio_exceeded():
            abort["flag"] = (f"变更率熔断({stats['changed']}/{stats['audited']}"
                             f" > {args.max_change_ratio}), 已停止写入")
            stats["aborted"] = abort["flag"]
            pending.clear()
            state.save()
            return False
        batch = list(pending)
        pending.clear()
        try:
            fix_n, fail_n = cache.update_many(batch)
            stats["applied"] += int(fix_n or 0)
            stats["flush_fail"] += int(fail_n or 0)
            print(f"[写入] update_many: 更正 {fix_n} 条, 失败 {fail_n} 条")
        except Exception as e:
            stats["flush_fail"] += len(batch)
            print(f"[写入] update_many 异常: {e}")
        state.save()
        return True

    def process(idx, item_tuple):
        q, old, qtype = item_tuple
        rec = state.done_record(q) if resumed else None
        if rec and str(rec.get("old", "")) == str(old):
            return {"question": q, "type": qtype, "old_answer": old,
                    "status": "skipped_resumed", "skipped": True}
        course = courses[idx % len(courses)]
        try:
            it = audit_one(q, old, qtype, cache_auth, course, args.votes)
        except Exception as e:
            # 单题异常不得中断整轮(长时间无人值守场景)
            it = {"time": _now(), "question": q, "type": qtype,
                  "old_answer": old, "new_answer": "", "ai_raw": "",
                  "ai_all": [], "votes": 0, "similarity": None,
                  "status": "failed", "note": f"核对异常: {str(e)[:120]}"}
        time.sleep(random.uniform(max(0.0, args.sleep_min),
                                  max(args.sleep_min, args.sleep_max)))
        return it

    def handle(it, idx):
        if it.get("skipped"):
            stats["skipped_resumed"] += 1
            return
        stats["audited"] += 1
        st = it["status"]
        if st in stats:
            stats[st] += 1
        if st == "changed" and it["type"] in WRITABLE_TYPES:
            pending.append((it["question"], it["new_answer"]))
        state.mark(it["question"], it["old_answer"], st)
        fail_streak["n"] = fail_streak["n"] + 1 if st == "failed" else 0
        reporter.log(it)
        flag = {"changed": "更正", "same": "一致", "skipped_invalid": "跳过",
                "uncertain": "待定", "failed": "失败",
                "report_only": "仅报告"}.get(st, st)
        print(f"[{idx + 1}/{len(picked)}] {it['type']:<5} {flag:<4} | "
              f"{it['question'][:36]} | {it['old_answer'][:14]!r} -> "
              f"{str(it['new_answer'])[:14]!r}")
        if pending and len(pending) >= max(1, args.flush_every):
            flush()
        elif stats["audited"] % 20 == 0:
            state.save()  # 断点进度定期落盘(避免硬中断丢失整轮进度)

    print(f"[执行] 开始核对, 每题停顿 {args.sleep_min}~{args.sleep_max}s, "
          f"votes={args.votes}, workers={max(1, args.workers)}")
    try:
        if max(1, args.workers) <= 1:
            for i, tup in enumerate(picked):
                if abort["flag"]:
                    break
                handle(process(i, tup), i)
                if fail_streak["n"] >= max(1, args.max_fail):
                    abort["flag"] = (f"连续失败熔断({fail_streak['n']}题), 已中止")
                    stats["aborted"] = abort["flag"]
                    break
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
                futs = [ex.submit(process, i, tup)
                        for i, tup in enumerate(picked)]
                for i, f in enumerate(futs):
                    if abort["flag"]:
                        break
                    try:
                        it = f.result()
                    except Exception as e:
                        stats["audited"] += 1
                        stats["failed"] += 1
                        print(f"[{i + 1}/{len(picked)}] 线程异常: {e}")
                        continue
                    handle(it, i)
                    if fail_streak["n"] >= max(1, args.max_fail):
                        abort["flag"] = (f"连续失败熔断({fail_streak['n']}题), 已中止")
                        stats["aborted"] = abort["flag"]
                        break
    except KeyboardInterrupt:
        abort["flag"] = abort["flag"] or "用户中断(Ctrl+C)"
        stats["aborted"] = abort["flag"]
        print("\n[执行] 收到中断信号, 正在安全收尾...")
    finally:
        flush()
        elapsed = int(time.time() - t0)
        sig_after = _file_sig(tiku_path)
        state.save()
        jp, cp = reporter.write(
            {"started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
             "finished_at": _now(), "elapsed_sec": elapsed,
             "tiku_path": tiku_path, "dry_run": dry_run, "types": types,
             "limit": args.limit, "start": start, "end": end,
             "votes": args.votes, "workers": max(1, args.workers),
             "max_change_ratio": args.max_change_ratio,
             "state_file": state_path},
            dict(stats, tiku_count=cache.count,
                 tiku_sig_before=str(sig_before),
                 tiku_sig_after=str(sig_after),
                 tiku_changed_on_disk=(sig_before != sig_after)))
        _print_summary(stats)
        print(f"  耗时              {elapsed} 秒")
        print(f"  题库文件是否变化  {'是' if sig_before != sig_after else '否'}"
              f"(dry-run 时必须为否)")
        print(f"  审计日志          {reporter.log_path}")
        print(f"  JSON报告          {jp}")
        print(f"  CSV报告           {cp}")
        print(f"  断点状态          {state_path}")
        # 终端展示少量样例改动
        changed_items = [
            x for x in reporter.items if x["status"] == "changed"][:10]
        if changed_items:
            print("\n---------- 样例改动(最多10条) ----------")
            for it in changed_items:
                print(f"  题: {it['question'][:60]}")
                print(f"     旧: {it['old_answer'][:40]!r} -> "
                      f"新: {it['new_answer'][:40]!r} | AI原始: "
                      f"{str(it['ai_raw'])[:80]!r} | {it['note']}")
        elif dry_run:
            print("\n本次没有发现需要改动的题目(或全部无效/待定)")

    print("\n[完成] " + ("DRY-RUN 结束, 题库文件未做任何改动"
                       if dry_run else f"APPLY 结束, 已写入 {stats['applied']} 条"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
