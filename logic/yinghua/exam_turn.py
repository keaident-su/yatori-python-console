# -*- coding: utf-8 -*-
"""英华学堂 考试/作业 HTML解析 + 答案转换 (2026-10-15)

移植自 yatori-go-core:
  - apex/api/yinghua/YingHuaExamTurn.go :: TurnExamTopic
  - aggregation/yinghua/YingHuaCourseAction.go :: aiTurnYingHuaAnswer
  - utils/qutils.go :: SimilarityArraySelect

HTML格式(Go版正则确认):
  题目导航: <li><a data-id="answerId" ...>N</a></li>
  每题: <form method="post" action="/api/xx/submit">...</form>
  题号: <span class="num">...N   类型: <span class="tag">单选/多选/判断/填空/简答
  题干: <div class="content" style="...">...</div>
  选项: <li><label><input ...><span class="num">A</span><span class="txt">文本</span></label></li>
  填空: <input ... name="answer_N" .../>
"""
import difflib
import json
import re
from typing import Any, Dict, List, Optional

_TOPIC_NAV_RE = re.compile(
    r'<li>[ \f\n\r\t\v]*<a data-id="([^"]*)"[ \f\n\r\t\v]*href="[^"]*"'
    r'[ \f\n\r\t\v]*class="[^"]*"[ \f\n\r\t\v]*id="[^"]*"'
    r'[ \f\n\r\t\v]*data-index="[^"]*"[ \f\n\r\t\v]*onclick="[^"]*">'
    r'([^<]*)</a>[ \f\n\r\t\v]*</li>')
_FORM_RE = re.compile(
    r'<form method="post" action="/api/[^/]*\/submit">([\w\W]*?)</form>')
_NUM_RE = re.compile(r'<span class="num">[\D]*?([\d]+)')
_TAG_RE = re.compile(r'<span class="tag">([\s\S]*?)</span>')
_SOURCE_RE = re.compile(
    r'<span[ \f\n\r\t\v]*class="txt">[^\d]*([\d]*)[^分]*分[^<]*</span>')
_CONTENT_RE = re.compile(
    r'<div[ \f\n\r\t\v]*class="content"[ \f\n\r\t\v]*style="[^"]*">([\s\S]*?)</div>')
_SELECT_RE = re.compile(
    r'<li>[^<]*<label>[^<]*<input type="([^"]*)"[^v]*value="([^"]*)"'
    r'[ \f\n\r\t\v]*[checked="checked"]*[ \f\n\r\t\v]*class="[^"]*"'
    r'[ \f\n\r\t\v]*name="[^"]*">[ \f\n\r\t\v]*<span class="num">([^<]*)</span>'
    r'[ \f\n\r\t\v]*<span[ \f\n\r\t\v]*class="txt">([^<]*)</span>'
    r'[ \f\n\r\t\v]*</label>[ \f\n\r\t\v]*</li>')
_FILL_RE = re.compile(
    r'<input class="[^"]*" autocomplete="[^"]*" autocomplete="[^"]*"'
    r' type="[^"]*" style="[^"]*" name="answer_([^"]*)" value="[^"]*"/>')

_TAG_TYPE_MAP = {"单选": "单选", "多选": "多选", "判断": "判断",
                 "填空": "填空", "简答": "简答"}

_SLIST = list("ABCDEFGHIJKRMNOPQ")


def turn_exam_topic(exam_html: str) -> List[Dict[str, Any]]:
    """英华考试/作业HTML -> 题目列表

    返回: [{"answer_id","index","type","content","options","source"}]
    """
    nav: Dict[str, str] = {}
    for m in _TOPIC_NAV_RE.finditer(exam_html or ""):
        nav[m.group(2).strip()] = m.group(1)
    topics: List[Dict[str, Any]] = []
    for fm in _FORM_RE.finditer(exam_html or ""):
        th = fm.group(1)
        num = ""
        m = _NUM_RE.search(th)
        if m:
            num = m.group(1)
        tag = ""
        m = _TAG_RE.search(th)
        if m:
            tag = m.group(1).strip()
        source = ""
        m = _SOURCE_RE.search(th)
        if m:
            source = m.group(1)
        content = ""
        selects: List[str] = []
        if tag in ("单选", "多选", "判断", "填空", "简答"):
            m = _CONTENT_RE.search(th)
            if m:
                content = m.group(1)
            content = (content.replace("<p>", "")
                       .replace("</p>", "\n").replace("&nbsp;", ""))
            for sm in _SELECT_RE.finditer(th):
                selects.append(sm.group(4))  # 选项文本
            if tag == "填空":
                for fm2 in _FILL_RE.finditer(th):
                    selects.append(fm2.group(1))  # answer_N 的 N
        selects = [s.replace("&quot;", '"') for s in selects]
        topics.append({"answer_id": nav.get(num, ""), "index": num,
                       "type": _TAG_TYPE_MAP.get(tag, tag), "content": content,
                       "options": selects, "source": source})
    return topics


def similarity(a: str, b: str) -> float:
    """字符串相似度(移植 Go qutils.Similarity)"""
    return difflib.SequenceMatcher(None, str(a or ""), str(b or "")).ratio()


def pick_option_letter(target: str, options: List[str]) -> str:
    """AI答案文本 -> 匹配选项文本 -> 选项字母(移植 SimilarityArraySelect)"""
    best_idx = 0
    best_score = 0.0
    for i, opt in enumerate(options or []):
        sc = similarity(opt, target)
        if sc > best_score:
            best_score = sc
            best_idx = i
    if best_idx >= len(_SLIST):
        return "A"
    return _SLIST[best_idx]


def turn_ai_answer(ai_answer: str, topic: Dict[str, Any]) -> List[str]:
    """AI答案(JSON数组文本) -> 英华answers列表(移植 aiTurnYingHuaAnswer)

    - 单选/多选/判断: JSON数组元素逐个做选项文本相似度匹配 -> 字母
    - 填空/简答: 直接使用JSON数组元素
    - 兜底: 单选/判断->["A"], 多选->["B","C"], 填空/简答->空
    """
    t = topic.get("type", "")
    options = topic.get("options") or []
    answer: List[str] = []
    texts: List[str] = []
    try:
        arr = json.loads(ai_answer) if isinstance(
            ai_answer, str) else ai_answer
        if isinstance(arr, list):
            texts = [str(x) for x in arr]
        elif arr:
            texts = [str(arr)]
    except Exception:
        if ai_answer:
            texts = [str(ai_answer)]
    if t in ("单选", "多选", "判断"):
        for item in texts:
            if not options or t == "判断":
                # 判断题或无选项: 直接字母
                s = str(item).strip().upper()
                answer.append(s[0] if s and s[0] in "ABCDEFGH" else "A")
            else:
                answer.append(pick_option_letter(item, options))
    elif t in ("填空", "简答"):
        answer = list(texts)
    if not answer:
        if t in ("单选", "判断"):
            answer = ["A"]
        elif t == "多选":
            answer = ["B", "C"]
        # 填空/简答: 留空
    return answer
