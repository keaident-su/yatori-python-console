# -*- coding: utf-8 -*-
"""
AI client module - 完全对齐 Go que-core/aiq/AiQuestion.go
每种 AI 类型硬编码官方端点（url 参数仅 OTHER 类型使用），
temperature=0.2，7 次重试，JSON 格式校验失败追加纠正消息重试，
AI 并发信号量容量=2（对齐 Go AiSem）。
"""
import json as _json
import threading
import time
from typing import List, Optional

import httpx

from utils.log import log_print, INFO, BoldRed

# AI 并发限制（对齐 Go: var AiSem = make(chan struct{}, 2)）
_AI_SEM = threading.Semaphore(2)

# ============ 各 AI 类型官方端点（对齐 Go AggregationAIApi 各实现） ============
_AI_ENDPOINTS = {
    "DEEPSEEK": "https://api.deepseek.com/chat/completions",
    "TONGYI": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "CHATGLM": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "ZHIPU": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "XINGHUO": "https://spark-api-open.xf-yun.com/v1/chat/completions",
    "DOUBAO": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    "OPENAI": "https://api.openai.com/v1/responses",
    "SILICON": "https://api.siliconflow.cn/v1/chat/completions",
    "SILICONFLOW": "https://api.siliconflow.cn/v1/chat/completions",
    "METAAI": "https://metaso.cn/api/v1/chat/completions",
    "OPENROUTER": "https://openrouter.ai/api/v1/chat/completions",
}

# 默认模型（对齐 Go 各 API 中 model == "" 时的默认值）
_AI_DEFAULT_MODELS = {
    "DEEPSEEK": "deepseek-chat",
    "TONGYI": "qwen-plus-latest",
    "CHATGLM": "glm-4",
    "ZHIPU": "glm-4",
    "XINGHUO": "generalv3.5",
    "SILICON": "Qwen/Qwen2.5-7B-Instruct",
    "SILICONFLOW": "Qwen/Qwen2.5-7B-Instruct",
    "METAAI": "fast",
}

_RETRY_NUM = 7
_JSON_FIX_PROMPT = "你刚才生成的回复未严格遵循json格式，我无法正常解析，请你重新生成。"

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
    返回: 逗号分隔的答案内容字符串
    """
    if not raw:
        return ""
    text = raw.strip()
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, list) and len(parsed) > 0:
            parts = [str(p).strip() for p in parsed if str(p).strip()]
            if parts:
                return ','.join(parts)
    except (ValueError, _json.JSONDecodeError):
        pass
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
    return text


def _is_valid_json_array(content: str) -> bool:
    try:
        return isinstance(_json.loads(content), list)
    except (ValueError, _json.JSONDecodeError):
        return False


class AIClient:
    """AI client - 对齐 Go AggregationAIApi：按 aiType 分发到硬编码官方端点。
    url 参数仅 OTHER 类型使用。
    """

    def __init__(self, ai_url: str, model: str, api_key: str, ai_type: str):
        self.config_url = (ai_url or "").strip().rstrip("/")
        self.api_key = api_key or ""
        self.ai_type = (ai_type or "").strip().upper()
        # 端点解析：内置类型用硬编码端点，OTHER 用配置 url
        if self.ai_type in _AI_ENDPOINTS:
            self.endpoint = _AI_ENDPOINTS[self.ai_type]
        else:
            # OTHER 或未知类型：使用配置的 url（补全 chat/completions 路径）
            u = self.config_url
            if u and "/chat/completions" not in u and "/v1" not in u and "/v3" not in u and "/v4" not in u:
                u = u + "/v1/chat/completions"
            self.endpoint = u
        # 模型解析：为空则使用该类型的默认模型（对齐 Go）
        self.model = (model or "").strip(
        ) or _AI_DEFAULT_MODELS.get(self.ai_type, "")

    def check(self) -> Optional[Exception]:
        """Check AI availability - 对齐 Go AICheck。"""
        if not self.ai_type:
            return Exception("请先填写AIType参数，详细参考官方文档：https://yatori-dev.github.io/yatori-docs/yatori-go-console/docs.html")
        if not self.api_key:
            return Exception("无效apiKey，请检查apiKey是否正确填写")
        if not self.endpoint:
            return Exception("AI请求地址为空，OTHER类型需要在aiUrl中填写对应地址")
        # 对齐 Go AICheck：发送测试消息
        content, err = self._request_chat(
            [{"role": "user", "content": '请你原模原样输出：["测试成功"]'}],
            expect_json=False)
        if err:
            return err
        return None

    def ask(self, question: str, options: Optional[List[str]] = None,
            q_type: str = '') -> str:
        """Ask AI for an answer.
        :param q_type: question type key (single_choice/multiple_choice/judge/fill/short/essay)
        """
        if q_type:
            system_prompt, user_content = _build_question_prompt(
                q_type, question, options)
        else:
            user_content = question
            if options:
                lines = []
                for i, opt in enumerate(options):
                    lines.append("%s. %s" % (chr(65 + i), opt))
                user_content = question + "\n\nOptions:\n" + \
                    "\n".join(lines) + "\n\nPlease give the answer directly."
            system_prompt = _SYSTEM_PROMPT_DEFAULT

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        content, err = self._request_chat(messages, expect_json=True)
        if err or not content:
            if err:
                log_print(INFO, BoldRed, "AI request error: %s" % str(err))
            return ""
        if q_type:
            return _parse_json_array_answer(content)
        return content.strip()

    # ============ 核心请求逻辑（对齐 Go 各 ChatReplyApi） ============

    def _request_chat(self, messages: List[dict], expect_json: bool = True,
                      retry: int = _RETRY_NUM) -> tuple:
        """发送聊天请求，返回 (content, error)。
        - 并发信号量限制（对齐 Go AiSem）
        - 7次重试
        - expect_json 时校验返回是否为 JSON 数组，失败追加纠正消息重试（对齐 Go）
        """
        if not self.endpoint:
            return "", Exception("AI请求地址为空")

        _AI_SEM.acquire()
        try:
            return self._request_chat_inner(list(messages), expect_json, retry)
        finally:
            _AI_SEM.release()

    def _request_chat_inner(self, messages: List[dict], expect_json: bool,
                            retry: int) -> tuple:
        if retry < 0:
            return "", Exception("AI重试次数已用完")

        try:
            if self.ai_type == "OPENAI":
                # OpenAI Responses API：用 input 字段（对齐 Go OpenAiReplyApi）
                payload = {
                    "model": self.model,
                    "temperature": 0.2,
                    "input": messages,
                }
            elif self.ai_type == "METAAI":
                # 秘塔AI特殊格式（对齐 Go MetaAIReplyApi）
                last_user = ""
                for m in reversed(messages):
                    if m.get("role") == "user":
                        last_user = m.get("content", "")
                        break
                payload = {
                    "q": last_user,
                    "model": self.model or "fast",
                    "format": "text",
                    "scope": "online",
                }
            else:
                payload = {
                    "model": self.model,
                    "temperature": 0.2,
                    "messages": messages,
                }

            resp = httpx.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=60,
                verify=False,
            )
            body = resp.text

            if self.ai_type == "METAAI":
                try:
                    data = resp.json()
                except Exception:
                    time.sleep(0.1)
                    return self._request_chat_inner(messages, expect_json, retry - 1)
                content = ""
                if isinstance(data, dict):
                    content = data.get("answer", "") or data.get(
                        "content", "") or ""
                if not content:
                    return "", Exception("AI回复内容未找到，AI返回信息：" + body[:300])
                if expect_json and not _is_valid_json_array(content):
                    messages.append({"role": "system", "content": content})
                    messages.append(
                        {"role": "user", "content": _JSON_FIX_PROMPT})
                    return self._request_chat_inner(messages, expect_json, retry - 1)
                return content, None

            # 通用 OpenAI 兼容解析
            try:
                data = resp.json()
            except Exception:
                time.sleep(0.1)
                return self._request_chat_inner(messages, expect_json, retry - 1)

            # 处理业务异常（对齐 Go: message contains "Request processing has failed"）
            result_msg = data.get("message", "")
            if isinstance(result_msg, str) and "Request processing has failed" in result_msg:
                time.sleep(0.1)
                return self._request_chat_inner(messages, expect_json, retry - 1)

            # 401/403 鉴权失败直接返回，不重试
            if resp.status_code in (401, 403):
                return "", Exception("API Key invalid (status=%d): %s" % (
                    resp.status_code, body[:200]))

            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                return "", Exception("AI回复内容未找到，AI返回信息：" + body[:300])

            message = choices[0].get("message", {}) if isinstance(
                choices[0], dict) else {}
            content = message.get("content", "")
            if not isinstance(content, str):
                return "", Exception("content field missing or not a string in response")

            # JSON 格式检查（对齐 Go：失败追加纠正消息重试）
            if expect_json and not _is_valid_json_array(content):
                messages.append({"role": "system", "content": content})
                messages.append({"role": "user", "content": _JSON_FIX_PROMPT})
                return self._request_chat_inner(messages, expect_json, retry - 1)

            return content, None
        except httpx.TimeoutException:
            time.sleep(0.1)
            return self._request_chat_inner(messages, expect_json, retry - 1)
        except httpx.HTTPError:
            time.sleep(0.1)
            return self._request_chat_inner(messages, expect_json, retry - 1)


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
