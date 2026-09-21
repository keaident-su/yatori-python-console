# -*- coding: utf-8 -*-
"""
多答题源答题引擎 - 自动答题核心

功能:
1. 多答题源顺序调用(降级回退): 支持 言溪题库(emmcy) / AVXE题库(axe) / 多个AI答题源
   / 本地题库缓存(local, 独立答题源), 第一个源取不到答案自动转向下一个
2. 配置极简: 每个答题源只需填 token, 其余参数内置默认; 调用顺序由用户自定义名称控制
3. 各答题源独立启停开关(含本地题库缓存)
4. 支持多个题库组, 组内子项可自定义命名(二次命名), 自定义名称用于调用顺序排序
5. 启动时 token 有效性自检并输出结果
6. 本地题库缓存: 独立答题源(可排序/可开关), 存储格式与 questions_answers.json 一致;
   外部题库/AI 答案成功后自动回写缓存并输出日志

答题流程: 按 order 顺序依次调用各答题源(含本地缓存), 失败自动回退;
        本地缓存命中直接返回; 外部源成功后将题目/答案回写本地缓存
"""
import json
import os
import re
import threading
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from utils.log import (
    log_print, INFO, Green, Yellow, Red, BoldRed, BoldGreen, Default
)

from logic.core.tiku_client import (
    EmmcyTikuClient, AxeTikuClient, N1TikuClient, ZETikuClient,
    EveryTikuClient, _plain_options, log_debug_source
)

# ============ 常量 ============

# 答题源类型
SOURCE_EMMCY = "emmcy"   # 言溪题库
SOURCE_AXE = "axe"       # AVXE题库
SOURCE_N1 = "n1"         # N1题库(无言题库/网课搜题助手)
SOURCE_ZE = "ze"         # ZE题库(ZError)
SOURCE_EVERY = "every"   # EveryAPI题库(AI问答型)
SOURCE_AI = "ai"         # AI大模型
SOURCE_LOCAL = "local"   # 本地题库缓存(独立答题源, 可参与顺序排序)

SOURCE_TYPE_ALIAS = {
    "emmcy": SOURCE_EMMCY, "yanxi": SOURCE_EMMCY, "言溪": SOURCE_EMMCY,
    "yanxi_tiku": SOURCE_EMMCY,
    "axe": SOURCE_AXE, "avxe": SOURCE_AXE, "AXE_tiku": SOURCE_AXE,
    "n1": SOURCE_N1, "n1_tiku": SOURCE_N1, "n1题库": SOURCE_N1,
    "n1screch": SOURCE_N1, "n1screch_tiku": SOURCE_N1,
    "ze": SOURCE_ZE, "ze_tiku": SOURCE_ZE, "zerror": SOURCE_ZE,
    "ze题库": SOURCE_ZE,
    "every": SOURCE_EVERY, "everyapi": SOURCE_EVERY,
    "every_api": SOURCE_EVERY, "every_tiku": SOURCE_EVERY,
    "ai": SOURCE_AI, "ai_model": SOURCE_AI, "model": SOURCE_AI,
    "local": SOURCE_LOCAL, "local_json": SOURCE_LOCAL, "cache": SOURCE_LOCAL,
    "本地题库缓存": SOURCE_LOCAL,
}

_ANSWER_PLACEHOLDER_KW = ("很抱歉", "未找到", "没有找到", "搜索不到", "无答案")


def _answer_cacheable(ans: str, q_type: str) -> bool:
    """判断答案是否允许写入本地题库缓存(防止异常长文本污染题库)

    背景: 第三方题库/AI 偶发返回整段错误文本作为答案(如多选返回一整段文章),
    若回写缓存会被后续查询命中, 污染答题正确率。
    规则:
      - 选择题/判断题: 正常答案应很短(如 A / ABCD / A,C,D / 对 / 错);
        长度>20 或含句末标点(。；;!?!)即视为脏数据, 不缓存;
      - 其它/未知题型: 答案天然可能较长, 仅拦截超长(>500)或含换行的恶劣数据。
    """
    a = (ans or "").strip()
    if not a:
        return False
    if "\n" in a or "\r" in a:
        return False
    t = (q_type or "").lower()
    if t in ("single_choice", "multiple_choice", "judge"):
        if len(a) > 20:
            return False
        if re.search(r"[。；;!?！？]", a):
            return False
        return True
    return len(a) <= 500


# ============ 答题源 ============

class AnswerSource:
    """归一化后的答题源(题库组子项)"""

    # 连续多次网络级失败后进入冷却(避免失效源拖慢每题查询)
    _FAIL_COOLDOWN_SEC = 300

    def __init__(self, name: str, s_type: str, enable: int = 1,
                 token: str = "", ai_type: str = "", model: str = "",
                 url: str = ""):
        self.name = (name or "").strip() or s_type
        self.type = SOURCE_TYPE_ALIAS.get((s_type or "").strip().lower(),
                                          (s_type or "").strip().lower())
        self.enable = 1 if enable else 0
        self.token = (token or "").strip()
        self.ai_type = (ai_type or "").strip().upper()
        self.model = (model or "").strip()
        self.url = (url or "").strip()
        # 运行时状态(不参与配置签名)
        self._fails = 0
        self._cooldown_until = 0.0
        self._client = None

    def client_key(self) -> tuple:
        return (self.name, self.type, self.enable, self.token,
                self.ai_type, self.model, self.url)

    def check(self) -> Tuple[bool, str]:
        """token有效性自检 (仅第三方题库与AI)"""
        if not self.token:
            return False, "未填写token"
        if self.type == SOURCE_EMMCY:
            return EmmcyTikuClient(self.url, self.token).check()
        if self.type == SOURCE_AXE:
            return AxeTikuClient(self.url, self.token).check()
        if self.type == SOURCE_N1:
            return N1TikuClient(self.url, self.token).check()
        if self.type == SOURCE_ZE:
            return ZETikuClient(self.url, self.token).check()
        if self.type == SOURCE_EVERY:
            return EveryTikuClient(self.url, self.token, self.model).check()
        if self.type == SOURCE_AI:
            from logic.core.ai_client import AIClient
            err = AIClient(self.url, self.model, self.token,
                           self.ai_type).check()
            if err:
                return False, str(err)
            return True, "可用"
        return False, f"未知答题源类型: {self.type}"

    def _get_client(self):
        """获取/复用题库客户端(携带last_error用于失败检测)"""
        if self._client is None:
            if self.type == SOURCE_EMMCY:
                self._client = EmmcyTikuClient(self.url, self.token)
            elif self.type == SOURCE_AXE:
                self._client = AxeTikuClient(self.url, self.token)
            elif self.type == SOURCE_N1:
                self._client = N1TikuClient(self.url, self.token)
            elif self.type == SOURCE_ZE:
                self._client = ZETikuClient(self.url, self.token)
            elif self.type == SOURCE_EVERY:
                self._client = EveryTikuClient(
                    self.url, self.token, self.model)
        return self._client

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "") -> str:
        """查询答案, 查不到返回空串"""
        if not self.enable or not self.token:
            return ""
        if time.time() < self._cooldown_until:
            log_debug_source(
                self.name, "处于连续失败冷却期, 本次跳过(冷却结束后自动恢复)")
            return ""
        try:
            if self.type in (SOURCE_EMMCY, SOURCE_AXE, SOURCE_N1,
                             SOURCE_ZE, SOURCE_EVERY):
                client = self._get_client()
                ans = client.query(question, options, q_type)
                if ans:
                    self._fails = 0
                    return ans
                # 连续网络级失败达到上限后进入冷却
                if getattr(client, "last_error", ""):
                    self._fails += 1
                    if self._fails >= 3:
                        self._cooldown_until = time.time() + self._FAIL_COOLDOWN_SEC
                        self._fails = 0
                        log_debug_source(
                            self.name,
                            f"连续请求失败, 已暂停调用{self._FAIL_COOLDOWN_SEC // 60}分钟")
                else:
                    self._fails = 0
                return ""
            if self.type == SOURCE_AI:
                from logic.core.ai_client import AIClient
                return AIClient(self.url, self.model, self.token,
                                self.ai_type).ask(question, options, q_type)
        except Exception as e:
            log_debug_source(self.name, f"查询异常: {e}")
        return ""


def _flatten_sources(cfg) -> List[AnswerSource]:
    """将配置(题库组/子项)展平为答题源列表"""
    result: List[AnswerSource] = []

    def _one(node, inherit_type: str = ""):
        s_type = getattr(node, "type", "") or inherit_type
        return AnswerSource(
            name=getattr(node, "name", ""),
            s_type=s_type,
            enable=getattr(node, "enable", 1),
            token=getattr(node, "token", ""),
            ai_type=getattr(node, "ai_type", ""),
            model=getattr(node, "model", ""),
            url=getattr(node, "url", ""),
        )

    for group in getattr(cfg, "sources", None) or []:
        items = getattr(group, "items", None) or []
        if items:
            # 组内含多个子项: 逐个生成, 子项自定义名称用于排序
            for item in items:
                src = _one(item, inherit_type=getattr(group, "type", ""))
                if not src.token:
                    src.token = (getattr(group, "token", "") or "").strip()
                if not src.enable or not getattr(group, "enable", 1):
                    src.enable = 0
                result.append(src)
        else:
            result.append(_one(group))
    return result


def _apply_order(sources: List[AnswerSource],
                 order: List[str]) -> List[AnswerSource]:
    """按用户自定义名称排序(未列出的保持定义顺序排在后面)"""
    if not order:
        return sources
    named = [s.strip() for s in order if str(s or "").strip()]
    if not named:
        return sources
    ordered: List[AnswerSource] = []
    used_idx = set()
    for target in named:
        for i, src in enumerate(sources):
            if i in used_idx:
                continue
            if src.name == target:
                ordered.append(src)
                used_idx.add(i)
    for i, src in enumerate(sources):
        if i not in used_idx:
            ordered.append(src)
    return ordered


# ============ 本地题库缓存 ============

_PUNCT_RE = re.compile(
    r"[\s\u3000\xa0，。、；：？！,.;:?!()（）\[\]【】<>《》\"'“”‘’]+")


def _norm_question(text: str) -> str:
    """题目归一化(去空白/常见标点, 用于缓存匹配)"""
    return _PUNCT_RE.sub("", (text or "")).lower()


class LocalTikuCache:
    """本地题库缓存 - 格式与 questions_answers.json 一致 {"题目": "答案"}"""

    def __init__(self, path: str, enable: int = 1):
        self.path = path or "questions_answers.json"
        self.enable = bool(enable)
        self._lock = threading.RLock()
        self._data: Dict[str, str] = {}
        self._norm_index: Dict[str, str] = {}
        self._bucket: Dict[int, List[str]] = {}  # 长度分桶(大题库加速)
        self.loaded = False
        self._load_failed = False  # 读取失败时禁止写回(防止覆盖损坏文件)
        self._disk_sig = None      # 磁盘文件签名(mtime_ns,size): 检测外部修改

    def _disk_signature(self):
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def load(self):
        with self._lock:
            if self.loaded:
                return
            self.loaded = True
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data = {str(k): str(v)
                                  for k, v in data.items() if str(k).strip()}
                    self._rebuild_index()
                self._disk_sig = self._disk_signature()
            except Exception as e:
                # 已存在但读取失败: 标记为禁止覆写, 避免清空原有题库
                self._load_failed = True
                log_print(INFO, BoldRed,
                          f"[答题源] 本地题库缓存读取失败({self.path}): {e}")
                log_print(INFO, BoldRed,
                          "[答题源] 为避免覆盖损坏文件, 已暂停写入该缓存文件")

    def _rebuild_index(self):
        self._norm_index = {}
        self._bucket = {}
        for k, v in self._data.items():
            nk = _norm_question(k)
            if nk and nk not in self._norm_index:
                self._norm_index[nk] = v
        # 长度分桶(每8字符一桶, 供包含/模糊匹配快速筛选)
        for nk in self._norm_index:
            self._bucket.setdefault(len(nk) // 8, []).append(nk)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._data)

    def lookup(self, question: str) -> Tuple[str, str]:
        """查找答案 -> (答案, 命中的原题), 未命中返回空"""
        if not self.enable or not question:
            return "", ""
        self.load()  # 懒加载: 首次访问自动读取题库文件
        q = question.strip()
        with self._lock:
            # 1. 原文精确
            v = self._data.get(q)
            if v:
                return v, q
            # 2. 归一化精确
            nq = _norm_question(q)
            if nq:
                v = self._norm_index.get(nq)
                if v:
                    return v, q
            if len(nq) < 6:
                return "", ""
            nqlen = len(nq)
            # 3. 包含匹配(双向, 仅扫相近长度桶, 避免大题库全量扫描)
            for b in range(max(0, nqlen // 16 - 1), nqlen // 4 + 2):
                for k in self._bucket.get(b, ()):
                    if len(k) >= 8 and (k in nq or nq in k):
                        return self._norm_index[k], question
            # 4. 相似度匹配(仅扫长度接近的桶, 控制开销)
            best_v, best_score = "", 0.0
            candidates = []
            for b in range(max(0, int(nqlen * 0.6) // 8 - 1),
                           int(nqlen * 1.6) // 8 + 2):
                for k in self._bucket.get(b, ()):
                    if not k:
                        continue
                    ratio = len(k) / max(nqlen, 1)
                    if 0.6 <= ratio <= 1.6:
                        candidates.append(k)
            candidates.sort(key=lambda k: abs(len(k) - nqlen))
            for k in candidates[:400]:
                score = SequenceMatcher(None, nq, k).ratio()
                if score > best_score:
                    best_score, best_v = score, self._norm_index[k]
            if best_score >= 0.85:
                return best_v, question
            return "", ""

    def save(self, question: str, answer: str) -> bool:
        """写入新答案(格式严格对齐 questions_answers.json)"""
        q = (question or "").strip()
        a = (answer or "").strip()
        if not self.enable or not q or not a:
            return False
        if any(kw in a for kw in _ANSWER_PLACEHOLDER_KW):
            return False
        self.load()  # 懒加载: 确保已有数据不丢失
        if self._load_failed:
            return False
        with self._lock:
            # 外部修改检测: 题库文件被其它程序/工具替换或更新时,
            # 重新加载磁盘最新内容后再写入, 避免覆盖外部新数据(如大题库导入)
            cur_sig = self._disk_signature()
            if cur_sig is not None and self._disk_sig is not None and cur_sig != self._disk_sig:
                old_count = len(self._data)
                log_print(INFO, Yellow,
                          f"[答题源] 检测到本地题库文件被外部修改({self.path}), "
                          f"正在重新加载合并(内存{old_count}条 -> 磁盘最新)...")
                self.loaded = False
                self._load_failed = False
                self.load()
                if self._load_failed:
                    return False
                log_print(INFO, Green,
                          f"[答题源] 已重新加载题目 {len(self._data)} 条")
            if q in self._data:
                return False
            self._data[q] = a
            nq = _norm_question(q)
            if nq:
                self._norm_index.setdefault(nq, a)
                self._bucket.setdefault(len(nq) // 8, []).append(nq)
            try:
                dir_name = os.path.dirname(os.path.abspath(self.path))
                if dir_name:
                    os.makedirs(dir_name, exist_ok=True)
                tmp_path = self.path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=4)
                os.replace(tmp_path, self.path)
                self._disk_sig = self._disk_signature()
                return True
            except Exception as e:
                log_print(INFO, BoldRed,
                          f"[答题源] 本地题库缓存写入失败({self.path}): {e}")
                return False


# ============ 答题引擎 ============

class AnswerEngine:
    """多答题源顺序调用引擎"""

    def __init__(self, sources: List[AnswerSource], order: List[str],
                 cache: Optional[LocalTikuCache],
                 token_check: int = 1):
        self.sources = _apply_order(list(sources), order or [])
        self.cache = cache
        self.token_check = bool(token_check)
        # 本地缓存是否作为答题源参与(存在已启用的local类型答题源)
        self._cache_active = bool(cache) and any(
            s.type == SOURCE_LOCAL and s.enable for s in self.sources)

    @property
    def enabled_sources(self) -> List[AnswerSource]:
        return [s for s in self.sources
                if s.enable and (s.token or s.type == SOURCE_LOCAL)]

    def is_ready(self) -> bool:
        """引擎是否具备答题能力(有启用的远程答题源 或 本地缓存有数据)"""
        for s in self.sources:
            if s.enable and s.type != SOURCE_LOCAL and s.token:
                return True
        if self._cache_active and self.cache.count > 0:
            return True
        return False

    def query(self, question: str, options: Optional[List[str]] = None,
              q_type: str = "", only_ai: bool = False,
              use_cache: bool = True) -> Tuple[str, str]:
        """按顺序调用各答题源 -> (答案, 命中源名称); 全部失败返回 ("", "")

        日志要求: 每个答题源每次被处理都留下日志(禁用/跳过/命中/未命中/异常/
        本地缓存每次调用/写入缓存), 便于查看每题到底由哪个源回答成功
        """
        question = (question or "").strip()
        if not question:
            return "", ""
        use_cache = bool(use_cache and self._cache_active)
        plain_opts = _plain_options(options)
        total = len(self.sources)

        for pos, src in enumerate(self.sources, 1):
            tag = f"[{pos}/{total}]"
            # ---- 禁用/不适用: 也留日志(说明该源本次未被调用) ----
            if not src.enable:
                log_debug_source(src.name, f"{tag} 已禁用(enable=0), 跳过")
                continue
            if only_ai and src.type != SOURCE_AI:
                log_debug_source(src.name, f"{tag} 当前场景仅用AI源, 跳过")
                continue
            # ---- 本地题库缓存(独立答题源, 参与顺序排序) ----
            if src.type == SOURCE_LOCAL:
                if not use_cache:
                    log_debug_source(src.name, f"{tag} 本地缓存本次未启用, 跳过")
                    continue
                self.cache.load()  # 确保首次查询前已加载, 计数准确
                log_debug_source(
                    src.name,
                    f"{tag} 正在查询本地题库缓存(当前{self.cache.count}条记录)"
                    f" | 题目: {question[:40]}")
                ans, _hit_q = self.cache.lookup(question)
                if ans:
                    log_debug_source(
                        src.name,
                        f"{tag} 命中答案: {ans[:80]} | 题目: {question[:40]}")
                    return ans, src.name
                log_debug_source(src.name, f"{tag} 未命中, 继续下一个答题源")
                continue
            # ---- 第三方题库/AI ----
            if not src.token:
                log_debug_source(src.name, f"{tag} 未配置token, 跳过")
                continue
            log_debug_source(src.name, f"{tag} 发起查询 | 题目: {question[:40]}")
            try:
                ans = src.query(question, plain_opts, q_type)
            except Exception as e:
                log_debug_source(
                    src.name, f"{tag} 查询异常: {e}, 自动回退下一个答题源")
                ans = ""
            if ans:
                ans = ans.strip()
                # 外部题库/AI 成功 -> 将题目与答案回写本地题库缓存
                # 防污染(2026-09-21): 疑似异常答案(超长/含句末标点的脏数据)不写入
                if use_cache:
                    if not _answer_cacheable(ans, q_type):
                        log_debug_source(
                            "本地题库缓存",
                            f"本次未写入(答案疑似异常数据, 已拦截防污染): "
                            f"{ans[:60]}")
                    elif self.cache.save(question, ans):
                        log_debug_source(
                            "本地题库缓存",
                            f"已写入本地题库缓存: 题目: {question[:40]}... "
                            f"-> 答案: {ans[:60]}")
                    else:
                        log_debug_source(
                            "本地题库缓存",
                            "本次未写入(题目已存在缓存或缓存不可写)")
                log_debug_source(
                    src.name, f"{tag} 命中答案: {ans[:80]} | 题目: {question[:40]}")
                return ans, src.name
            log_debug_source(src.name, f"{tag} 无结果, 自动回退下一个答题源")

        log_debug_source("答题引擎",
                         f"所有答题源均未命中 | 题目: {question[:50]}")
        return "", ""

    def check_all(self) -> Tuple[int, int]:
        """启动自检所有已配置答题源 -> (可用数, 已启用总数)"""
        configured = [s for s in self.sources]
        enabled = [s for s in configured if s.enable]
        ok_count = 0

        if not configured:
            log_print(INFO, Yellow,
                      "[答题源自检] 未配置任何答题源(可在配置文件的 "
                      "setting.answerSetting.sources 中配置)")
            return 0, 0

        log_print(INFO, f"[答题源自检] 共配置 {len(configured)} 个答题源, "
                  f"已启用 {len(enabled)} 个:")
        for src in configured:
            if not src.enable:
                log_print(INFO, "  [答题源自检] ", Default, src.name,
                          Yellow, " 已禁用(跳过自检)")
                continue
            # 本地题库缓存(独立答题源): 展示缓存文件加载情况
            if src.type == SOURCE_LOCAL:
                if not self.cache:
                    continue
                self.cache.load()
                if self.cache._load_failed:
                    log_print(INFO, "  [答题源自检] ", Default, src.name, " ",
                              BoldRed,
                              f"✗ 缓存文件读取失败(已暂停写入): {self.cache.path}")
                else:
                    ok_count += 1
                    log_print(INFO, "  [答题源自检] ", Default, src.name, " ",
                              Green,
                              f"✓ 已加载 {self.cache.count} 条题库记录 "
                              f"({self.cache.path})")
                continue
            if not src.token:
                log_print(INFO, "  [答题源自检] ", Default, src.name,
                          Red, " 未填写token(跳过自检)")
                continue
            try:
                ok, detail = src.check()
            except Exception as e:
                ok, detail = False, f"自检异常: {e}"
            if ok:
                ok_count += 1
                log_print(INFO, "  [答题源自检] ", Default, src.name, " ",
                          Green, f"✓ 可用 ({detail})")
            else:
                log_print(INFO, "  [答题源自检] ", Default, src.name, " ",
                          BoldRed, f"✗ 不可用 - {detail}")

        return ok_count, len(enabled)


# ============ 全局单例 ============

_engine_lock = threading.Lock()
_engine: Optional[AnswerEngine] = None
_engine_signature: tuple = ()


def _build_engine(setting) -> Optional[AnswerEngine]:
    """根据 Setting 构建引擎(含旧版AI配置兼容与本地缓存自动补源)"""
    ans_cfg = getattr(setting, "answer_setting", None)
    sources = _flatten_sources(ans_cfg) if ans_cfg else []

    # 兼容旧配置: 未配置任何答题源时, 若旧 aiSetting 填写了apiKey则作为兜底AI源
    if not sources:
        ai = getattr(setting, "ai_setting", None)
        if ai and (getattr(ai, "api_key", "") or "").strip():
            sources = [AnswerSource(
                name="AI(旧配置)", s_type=SOURCE_AI, enable=1,
                token=ai.api_key, ai_type=ai.ai_type, model=ai.model,
                url=ai.ai_url)]

    cache_enable = 1
    cache_path = "questions_answers.json"
    order: List[str] = []
    token_check = 1
    if ans_cfg:
        cache_enable = getattr(ans_cfg, "local_cache_enable", 1)
        cache_path = getattr(ans_cfg, "local_cache_path", "") or cache_path
        order = list(getattr(ans_cfg, "order", None) or [])
        token_check = getattr(ans_cfg, "token_check", 1)

    # 本地题库缓存作为独立答题源: 未显式配置 local 类型源时,
    # 按旧配置(localCacheEnable)自动补一个并置于最前(保持旧行为: 缓存优先)
    local_srcs = [s for s in sources if s.type == SOURCE_LOCAL]
    if not local_srcs and cache_enable:
        sources.insert(0, AnswerSource(
            name="本地题库缓存", s_type=SOURCE_LOCAL, enable=1))
        local_srcs = [sources[0]]
    # 缓存文件路径: 本地答题源条目的 url 可覆盖 localCachePath
    for s in local_srcs:
        if s.url:
            cache_path = s.url
            break

    cache = LocalTikuCache(cache_path, enable=1)
    return AnswerEngine(sources, order, cache, token_check)


def configure_answer_engine(setting, do_check: bool = False) -> AnswerEngine:
    """构建/更新全局答题引擎(幂等, 配置未变化时不重建)"""
    global _engine, _engine_signature
    ans_cfg = getattr(setting, "answer_setting", None)
    sig = (
        tuple(str(getattr(s, "client_key", lambda: s)()) for s in
              (_flatten_sources(ans_cfg) if ans_cfg else [])),
        str(getattr(ans_cfg, "local_cache_enable", 1)) if ans_cfg else "1",
        str(getattr(ans_cfg, "local_cache_path", "")) if ans_cfg else "",
        tuple(getattr(ans_cfg, "order", None) or []) if ans_cfg else (),
        str(getattr(getattr(setting, "ai_setting", None), "api_key", "")),
    )
    with _engine_lock:
        if _engine is None or sig != _engine_signature:
            _engine = _build_engine(setting)
            _engine_signature = sig
        engine = _engine
    if do_check and engine is not None:
        engine.check_all()
    return engine


def get_answer_engine() -> Optional[AnswerEngine]:
    return _engine


def engine_is_ready() -> bool:
    eng = _engine
    return bool(eng and eng.is_ready())


def answer_query_detail(question: str, options: Optional[List[str]] = None,
                        q_type: str = "", only_ai: bool = False) -> Tuple[str, str]:
    """统一答题入口(明细版): 顺序调用各答题源 -> (答案, 命中的答题源名称)"""
    eng = _engine
    if eng is None:
        return "", ""
    return eng.query(question, options, q_type, only_ai=only_ai)


def answer_query(question: str, options: Optional[List[str]] = None,
                 q_type: str = "", only_ai: bool = False) -> str:
    """统一答题入口: 顺序调用各答题源, 返回答案(失败为空串)"""
    ans, _ = answer_query_detail(question, options, q_type, only_ai=only_ai)
    return ans


def run_startup_token_check(setting) -> None:
    """程序启动时的 token 自检(输出检查结果)"""
    engine = configure_answer_engine(setting)
    if engine is None:
        return
    if not engine.token_check:
        log_print(INFO, "[答题源自检] 已关闭启动自检(tokenCheck=0), 跳过")
        return
    t0 = time.time()
    ok_count, enabled_count = engine.check_all()
    if enabled_count > 0:
        log_print(INFO, "[答题源自检] 检查完毕: ",
                  BoldGreen if ok_count > 0 else BoldRed,
                  f"{ok_count}/{enabled_count} 个已启用答题源可用",
                  Default, f" (耗时{time.time() - t0:.1f}s)")
    # 预加载本地题库缓存
    if engine.cache and engine.cache.enable:
        engine.cache.load()
