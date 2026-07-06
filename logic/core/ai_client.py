# -*- coding: utf-8 -*-
"""
AI client module - supports OpenAI-compatible APIs and custom middleware.
"""
import json
from typing import List, Optional, Dict, Any

import httpx

from utils.log import log_print, INFO, Red, Green, Yellow, BoldRed, Default

_OPENAI_COMPATIBLE_TYPES = {"DEEPSEEK", "OPENAI", "OPENROUTER", "SILICONFLOW", "ZHIPU"}


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

    def ask(self, question: str, options: Optional[List[str]] = None) -> str:
        """Ask AI for an answer."""
        if self._is_openai_compatible():
            return self._ask_openai_compatible(question, options)
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
                               options: Optional[List[str]] = None) -> str:
        """Ask via OpenAI-compatible API."""
        try:
            user_content = question
            if options:
                lines = []
                for i, opt in enumerate(options):
                    lines.append("%s. %s" % (chr(65 + i), opt))
                opts_text = "\n".join(lines)
                user_content = question + "\n\nOptions:\n" + opts_text + "\n\nPlease give the answer directly."

            system_prompt = (
                "You are a professional quiz assistant. "
                "For choice questions, reply with ONLY the letter (A/B/C/D). "
                "For true/false questions, reply with True or False. "
                "For short answer questions, give the answer directly. "
                "No extra explanation needed."
            )

            resp = httpx.post(
                self.ai_url + "/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 2048,
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
                    return content.strip()
                return ""
            else:
                try:
                    err_data = resp.json()
                except Exception:
                    err_data = {}
                err_msg = err_data.get("error", {}).get("message", resp.text[:200])
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
                       question: str, options: Optional[List[str]] = None) -> str:
    """AI question answering (shortcut)."""
    client = AIClient(ai_url, model, api_key, ai_type)
    return client.ask(question, options)
