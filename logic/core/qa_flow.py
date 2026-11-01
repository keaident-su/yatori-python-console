# -*- coding: utf-8 -*-
"""通用答题流程骨架 (logic.core.qa_flow, 2026-10-15)

所有平台的"作业/考试"答题流程统一骨架:
    题目列表 -> 逐题多源答题(bridge) -> 平台提交回调 -> 交卷 -> 题库缓存

平台接入方式(极简):
    from logic.core.qa_flow import run_qa_flow
    questions = [...]  # 平台自己解析出的题目:
                       # [{"q_text","options","q_type","q_type_code","raw"}]
    def _submit(qn, answers, is_final):
        platform_api.submit(cache, qn["raw_id"], answers, "1" if is_final else "0")
    results, cached = run_qa_flow(questions, submit_fn=_submit,
                                  qtype_map=MY_QTYPE_MAP,
                                  auto_submit_final=bool(cc.exam_auto_submit),
                                  transform=my_answer_transform, log=...)
"""
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


def run_qa_flow(questions: List[Dict[str, Any]],
                submit_fn: Callable[[Dict[str, Any], List[str], bool], Any],
                qtype_map: Optional[Dict[str, str]] = None,
                auto_submit_final: bool = True,
                transform: Optional[Callable[[
                    str, Dict[str, Any]], List[str]]] = None,
                log=None,
                pace: float = 0.8) -> Tuple[List[Dict[str, Any]], int]:
    """通用答题流程骨架

    questions: [{"q_text","options","q_type","q_type_code","raw"...}]
    submit_fn(question, answers, is_final) -> 平台提交回调
    qtype_map: 平台题型码->标准题型(single_choice/...)
    transform: 平台答案转换(answer_text, question)->answers列表
    auto_submit_final: 是否最后一题交卷
    返回: (results, 缓存条数)
    """
    from logic.core.answer_bridge import bridge_answer_one, bridge_cache_results
    results: List[Dict[str, Any]] = []
    total = len(questions or [])
    for i, qn in enumerate(questions or []):
        qt = qn.get("q_type") or (qtype_map or {}).get(
            str(qn.get("q_type_code") or ""), "")
        try:
            ans, src = bridge_answer_one(
                qn.get("q_text", ""), options=qn.get("options"), q_type=qt)
        except Exception:
            ans, src = "", ""
        if callable(transform):
            try:
                answers = transform(ans, qn)
            except Exception:
                answers = [ans] if ans else []
        else:
            answers = [ans] if ans else []
        is_final = bool(auto_submit_final) and (i == total - 1)
        try:
            submit_fn(qn, answers, is_final)
        except Exception as e:
            if log:
                try:
                    log("  第%d题提交异常: %s" % (i + 1, str(e)[:70]))
                except Exception:
                    pass
        results.append({"q_text": qn.get("q_text", ""), "answer": ans,
                        "src": src, "q_type": qt})
        if log and (i + 1) % 5 == 0:
            try:
                log("  答题进度: %d/%d" % (i + 1, total))
            except Exception:
                pass
        time.sleep(max(0.0, float(pace)))
    try:
        n = bridge_cache_results(results)
    except Exception:
        n = 0
    return results, n
