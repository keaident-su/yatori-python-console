# -*- coding: utf-8 -*-
"""智慧树(ZHIHUISHU) 多源答题桥接 (2026-10-15)

统一接入 logic.core.answer_engine 多源答题引擎
(本地缓存 -> 各题库源 -> AI, 按优先级顺序调用 + 失败自动降级回退)。

用法:
    from logic.zhihuishu.answer_bridge import (
        zhs_answer_question, zhs_answer_questions, zhs_cache_answers)
    results = zhs_answer_questions(questions)   # 批量答题
    ...提交...
    zhs_cache_answers(results)                  # 提交成功后写题库缓存

questions 元素格式:
    {"q_text": str, "options": [str], "q_type_code": str, "q_type": str}
    (q_type 缺省时按智慧树题型码映射, 对齐学习通 _wt_code_map)
"""
from typing import Any, Dict, List, Optional, Tuple

from logic.core.answer_engine import (
    answer_query_detail, cache_answer_after_submit)

# 智慧树题型码 -> 标准题型映射 (对齐学习通 _wt_code_map)
ZHS_QTYPE_MAP = {
    "0": "single_choice",
    "1": "multiple_choice",
    "2": "fill",
    "3": "judge",
    "4": "short",
    "5": "essay",
    "6": "matching",
    "7": "composite",
    "8": "short",
    "9": "composite",
    "11": "matching",
}


def zhs_answer_question(q_text: str, options: Optional[List[str]] = None,
                        q_type_code: str = "",
                        q_type: str = "") -> Tuple[str, str]:
    """单题多源答题: 返回 (answer, 命中源名称)

    顺序调用各答题源(本地缓存->题库->AI), 失败自动降级回退。
    """
    qt = q_type or ZHS_QTYPE_MAP.get(str(q_type_code or ""), "")
    try:
        return answer_query_detail(q_text, options=options, q_type=qt)
    except Exception:
        return "", ""


def zhs_answer_questions(questions: List[Dict[str, Any]], log=None) -> List[Dict[str, Any]]:
    """批量多源答题(智慧树统一入口)

    questions: [{"q_text","options","q_type_code","q_type"}]
    返回: [{"q_text","answer","src","q_type"}]
    """
    out = []
    for q in questions or []:
        qt = q.get("q_type") or ZHS_QTYPE_MAP.get(
            str(q.get("q_type_code") or ""), "")
        try:
            ans, src = answer_query_detail(
                q.get("q_text") or "", options=q.get("options"), q_type=qt)
        except Exception:
            ans, src = "", ""
        out.append({"q_text": q.get("q_text") or "", "answer": ans,
                    "src": src, "q_type": qt})
        if log:
            try:
                log("  答题: %s -> %s [%s]" % (
                    (q.get("q_text") or "")[:16], (ans or "")[:24], src))
            except Exception:
                pass
    return out


def zhs_cache_answers(results: List[Dict[str, Any]]) -> int:
    """全部提交成功后写题库缓存(对齐学习通规范, 替代即问即存)

    返回写入条数。
    """
    n = 0
    for r in results or []:
        try:
            if cache_answer_after_submit(
                    r.get("q_text", ""), r.get("answer", ""),
                    q_type=r.get("q_type", ""), answer_src=r.get("src", "")):
                n += 1
        except Exception:
            pass
    return n
