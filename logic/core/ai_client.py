# -*- coding: utf-8 -*-
"""
AI client module - supports OpenAI-compatible APIs and custom middleware.
对齐 Go 的 AIProblemMessage + BuildAiQuestionMessage 实现。
"""
import json as _json
from typing import List, Optional, Dict, Any

import httpx

from utils.log import log_print, INFO, Red, Green, Yellow, BoldRed, Default

_OPENAI_COMPATIBLE_TYPES = {"DEEPSEEK", "OPENAI",
                            "OPENROUTER", "SILICONFLOW", "ZHIPU"}


# ============ AI System Prompts - 完全对齐 Go BuildAiQuestionMessage ============

_SYSTEM_PROMPT_SINGLE = (
    '接下来无论出现任何题目，你都必须只回答题目中某个选项对应的内容，并严格按照以下要求作答：\n\n'
    '【回答规则】\n'
    '1. 最终输出必须严格遵循 JSON 数组格式，例如：["选项内容"]\n'
    '2. 数组中只能有一个字符串元素。\n'
    '3. 字符串中不能包含选项前缀，如 A. B. C. D. 等，只能输出选项的纯内容。\n'
    '4. 不能输出解析、解释步骤、理由、提示语或任何多余文本。\n'
    '5. 不能输出题目本身、不能输出其他格式，只能输出 JSON 数组。\n'
    '6. 如果你无法判断正确答案，也必须随机选择一个选项的内容进行输出，不允许回答"我不知道""无法判断"之类内容。\n\n'
    '【格式要求】\n'
    '- 只能输出 JSON\n'
    '- 不允许换行，若内容中需要换行必须使用\\n\n'
    '- 不能出现额外的空格、标点或第二层数组'
)

_SYSTEM_PROMPT_MULTI = (
    '接下来无论出现任何题目，你都必须只回答选项对应的内容，且必须严格按照以下格式输出：\n\n'
    '【最终输出格式】\n'
    '["选项内容1","选项内容2", ...]\n'
    '- JSON 数组只能包含字符串元素。\n'
    '- 每个元素对应一个被选中的选项内容。\n'
    '- 严禁携带 A. B. C. D. 等前缀，只能输出纯内容。\n'
    '- 不得输出解析、解释、思考过程、题目内容或任何无关文本。\n'
    '- 如果你无法判断正确选项，也必须随机选择多个选项内容填入数组。'
)

_SYSTEM_PROMPT_JUDGE = (
    '接下来你只需要回答"正确"或者"错误"即可...格式：["正确"]\n'
    '就算你不知道选什么也随机选...无需回答任何解释！！！'
)

_SYSTEM_PROMPT_FILL = (
    '其中，"（answer_数字）"相关字样的地方是你需要填写答案的地方，回答时请严格遵循json格式：["答案1","答案2"]\n'
    '就算你不知道选什么也随机选...无需回答任何解释！！！'
)

_SYSTEM_PROMPT_SHORT = (
    '这是一个简答题，回答时请严格遵循json格式，包括换行等特殊符号也要遵循json语法：["答案"]，注意不要拆分答案！！！'
)

_SYSTEM_PROMPT_ESSAY = (
    '最终输出必须是一个合法 JSON 数组格式：["答案内容"]\n'
    '数组中只能包含一个字符串元素，答案必须完整写在同一个字符串里，不能拆分成多个元素。\n'
    '字符串内如需换行必须写为 \\n，不能出现真正的换行符。\n'
    '答案内容必须是连贯的完整论述，不得包含解析、题目、注释或生成说明。\n'
    '答案字数不少于 500 字。\n'
    '除 JSON 数组外严禁输出任何其他内容。'
)

_SYSTEM_PROMPT_DEFAULT = (
    'You are a professional quiz assistant. '
    'For choice questions, reply with ONLY the letter (A/B/C/D). '
    'For true/false questions, reply with True or False. '
    'For short answer questions, give the answer directly. '
    'No extra explanation needed.'
)

_Q_TYPE_MAP = {
    'single_choice': ('单选题', _SYSTEM_PROMPT_SINGLE),
    'multiple_choice': ('多选题', _SYSTEM_PROMPT_MULTI),
    'judge': ('判断题', _SYSTEM_PROMPT_JUDGE),
    'fill': ('填空题', _SYSTEM_PROMPT_FILL),
    'short': ('简答题', _SYSTEM_PROMPT_SHORT),
    'essay': ('论述题', _SYSTEM_PROMPT_ESSAY),
    'term_explanation': ('名词解释', _SYSTEM_PROMPT_ESSAY),
    'matching': ('连线题', _SYSTEM_PROMPT_DEFAULT),
}

_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def _build_question_prompt(q_type: str, question: str,
                           options: Optional[List[str]] = None) -> tuple:
    """构建结构化的 AI 提问 - 完全对齐 Go buildProblemHeader + system prompts
    Returns: (system_prompt, user_content)
    """
    info = _Q_TYPE_MAP.get(q_type)
    if info:
        type_cn, system_prompt = info
    else:
        type_cn, system_prompt = '简答题', _SYSTEM_PROMPT_DEFAULT

    user_content = f'题目类型：{type_cn}\n题目内容：\n{question}\n'

    if options and q_type in ('single_choice', 'multiple_choice', 'judge', 'fill'):
        for i, opt in enumerate(options):
            if i < len(_LETTERS):
                user_content += f'{_LETTERS[i]}.{opt}\n'

    return system_prompt, user_content


def _parse_json_array_answer(raw: str) -> str:
    """解析 AI 返回的 JSON 数组格式答案 - 对齐 Go ResponseTurnQuestion
    Go: json.Unmarshal([]byte(response), &answers) -> question.Answers = answers
    返回: 逗号分隔的答案内容字符串 (与 Go 的 answers += item 对齐)
    """
    if not raw:
        return ""
    text = raw.strip()
    # 尝试解析 JSON 数组
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, list) and len(parsed) > 0:
            # 将所有答案元素用逗号连接 (多选题会有多个元素)
            parts = [str(p).strip() for p in parsed if str(p).strip()]
            if parts:
                return ','.join(parts)
    except (ValueError, _json.JSONDecodeError):
        pass
    # 尝试从文本中提取 JSON 数组
    import re
    m = re.search(r'\[.*?\]', text, re.DOTALL)
    if m:
        try:
            parsed = _json.loads(m.group())
            if isinstance(parsed, list) and len(parsed) > 0:
                parts = [str(p).strip() for p in parsed if str(p).strip()]
                if parts:
                    return ','.join(parts)
        except (ValueError, _json.JSONDecodeError):
            pass
    # fallback: 返回原始文本
    return text


class AIClient:
    """AI client - auto-detects API type."""

    def __init__(self, ai_url: str, model: str, api_key: str, ai_type: str):
        self.ai_url = ai_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.ai_type = ai_type.upper()

    def _is_openai_compatible(self) -> bool:
        return self.ai_type in _OPENAI_COMPATIBLE_TYPES

    def check(self) -> Optional[Exception]:
        """Check AI availability."""
        if self._is_openai_compatible():
            return self._check_via_completion()
        return self._check_custom()

    def ask(self, question: str, options: Optional[List[str]] = None,
            q_type: str = '') -> str:
        """Ask AI for an answer.
        :param q_type: question type key (single_choice/multiple_choice/judge/fill/short/essay)
        """
        if self._is_openai_compatible():
            return self._ask_openai_compatible(question, options, q_type)
        return self._ask_custom(question, options)

    # ============ OpenAI Compatible API (DeepSeek, OpenAI, etc.) ============

    def _check_via_completion(self) -> Optional[Exception]:
        """Verify API by sending a simple completion request."""
        try:
            resp = httpx.post(
                self.ai_url + "/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return None
            if resp.status_code in (401, 403):
                return Exception("API Key invalid (status=%d)" % resp.status_code)
            try:
                data = resp.json()
            except Exception:
                data = {}
            err_msg = data.get("error", {}).get("message", resp.text[:200])
            return Exception("API check failed (status=%d): %s" % (resp.status_code, err_msg))
        except Exception as e:
            return e

    def _ask_openai_compatible(self, question: str,
                               options: Optional[List[str]] = None,
                               q_type: str = '') -> str:
        """Ask via OpenAI-compatible API - 对齐 Go BuildAiQuestionMessage"""
        try:
            if q_type:
                # 使用结构化 prompt (对齐 Go)
                system_prompt, user_content = _build_question_prompt(
                    q_type, question, options)
            else:
                # 兼容旧调用方式
                user_content = question
                if options:
                    lines = []
                    for i, opt in enumerate(options):
                        lines.append("%s. %s" % (chr(65 + i), opt))
                    opts_text = "\n".join(lines)
                    user_content = question + "\n\nOptions:\n" + \
                        opts_text + "\n\nPlease give the answer directly."
                system_prompt = _SYSTEM_PROMPT_DEFAULT

            resp = httpx.post(
                self.ai_url + "/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.1,
                },
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    content = message.get("content", "")
                    result = content.strip()
                    # 检测已知错误响应（API可能返回200但内容无效）
                    _error_markers = [
                        "insufficient", "balance", "quota",
                        "rate limit", "余额", "额度",
                    ]
                    if result and any(m in result.lower() for m in _error_markers):
                        log_print(INFO, BoldRed,
                                  "AI request returned error in 200 response: %s" % result[:100])
                        return ""
                    # 当使用结构化 prompt 时，解析 JSON 数组答案
                    if q_type:
                        return _parse_json_array_answer(result)
                    return result
                return ""
            else:
                try:
                    err_data = resp.json()
                except Exception:
                    err_data = {}
                err_msg = err_data.get("error", {}).get(
                    "message", resp.text[:200])
                log_print(INFO, BoldRed,
                          "AI request failed (status=%d): %s" % (resp.status_code, err_msg))
                return ""
        except httpx.TimeoutException:
            log_print(INFO, BoldRed, "AI request timeout")
            return ""
        except Exception as e:
            log_print(INFO, BoldRed, "AI request error: %s" % str(e))
            return ""

    # ============ Custom Middleware API (TONGYI, etc.) ============

    def _check_custom(self) -> Optional[Exception]:
        """Check via custom /check endpoint."""
        try:
            resp = httpx.get(
                self.ai_url + "/check",
                params={"aiType": self.ai_type, "model": self.model},
                headers={"Authorization": "Bearer " + self.api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                return None
            return Exception("AI check failed, status=%d" % resp.status_code)
        except Exception as e:
            return e

    def _ask_custom(self, question: str,
                    options: Optional[List[str]] = None) -> str:
        """Ask via custom /ask endpoint."""
        try:
            payload = {
                "aiType": self.ai_type,
                "model": self.model,
                "question": question,
            }
            if options:
                payload["options"] = options

            resp = httpx.post(
                self.ai_url + "/ask",
                json=payload,
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("answer", data.get("data", ""))
            return ""
        except Exception as e:
            log_print(INFO, BoldRed, "AI request error: %s" % str(e))
            return ""


# ============ Shortcut Functions ============

def ai_check(ai_url: str, model: str, api_key: str, ai_type: str) -> Optional[Exception]:
    """Check AI availability (shortcut)."""
    client = AIClient(ai_url, model, api_key, ai_type)
    return client.check()


def ai_problem_message(ai_url: str, model: str, api_key: str, ai_type: str,
                       question: str, options: Optional[List[str]] = None,
                       q_type: str = '') -> str:
    """AI question answering - 对齐 Go AIProblemMessage
    :param q_type: 题型键 (single_choice/multiple_choice/judge/fill/short/essay/...)
    """
    client = AIClient(ai_url, model, api_key, ai_type)
    return client.ask(question, options, q_type)
