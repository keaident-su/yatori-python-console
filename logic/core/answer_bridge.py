# -*- coding: utf-8 -*-
"""通用多源答题桥接 (logic.core.answer_bridge, 2026-10-15)

供【全部已适配平台】统一接入 logic.core.answer_engine 多源答题引擎:
    本地缓存 -> 各题库源 -> AI, 按优先级顺序调用 + 失败自动降级回退。

平台接入方式(最小改动, 对齐学习通三段式):
    from logic.core.answer_bridge import (
        bridge_answer_one, bridge_answer_batch, bridge_cache_results,
        build_qtype_map)

    ① 答题:   answer, src = bridge_answer_one(q_text, options, "single_choice")
       批量:   results = bridge_answer_batch(questions, qtype_map=PLAT_QTYPE_MAP)
    ② 提交:   ...平台自身提交逻辑...
    ③ 缓存:   bridge_cache_results(results)   # 提交成功后写题库缓存

questions 元素格式: {"q_text","options","q_type_code","q_type"}
results  元素格式: {"q_text","answer","src","q_type"}
"""
from typing import Any, Dict, List, Optional, Tuple

from logic.core.answer_engine import (
    answer_query_detail, cache_answer_after_submit)


def build_qtype_map(mapping: Dict[str, str]) -> Dict[str, str]:
    """构造平台题型码->标准题型映射(各平台自传)"""
    return dict(mapping or {})


def bridge_answer_one(q_text: str, options: Optional[List[str]] = None,
                      q_type: str = "", q_type_code: str = "",
                      qtype_map: Optional[Dict[str, str]] = None
                      ) -> Tuple[str, str]:
    """单题多源答题: (answer, 命中源名称)"""
    qt = q_type or (qtype_map or {}).get(str(q_type_code or ""), "")
    try:
        return answer_query_detail(q_text, options=options, q_type=qt)
    except Exception:
        return "", ""


def bridge_answer_batch(questions: List[Dict[str, Any]],
                        qtype_map: Optional[Dict[str, str]] = None,
                        log=None) -> List[Dict[str, Any]]:
    """批量多源答题: 返回 [{"q_text","answer","src","q_type"}]"""
    out = []
    for q in questions or []:
        qt = q.get("q_type") or (qtype_map or {}).get(
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


def bridge_cache_results(results: List[Dict[str, Any]]) -> int:
    """提交成功后写题库缓存(替代即问即存); 返回写入条数"""
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
