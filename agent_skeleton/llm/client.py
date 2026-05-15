from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

ONE_API_URL = os.getenv(
    "ONE_API_URL", "https://one-api-other.nowcoder.com/v1/chat/completions"
)
ONE_API_KEY = os.getenv("ONE_API_KEY", "YOUR_ONE_API_KEY")
DEFAULT_MODEL = "qwen3.6-flash"
REQUEST_TIMEOUT = 60


class LLMClient:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or DEFAULT_MODEL

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        resp = requests.post(
            ONE_API_URL,
            headers={
                "Authorization": f"Bearer {ONE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return body["choices"][0]["message"]["content"]

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return self._extract_json(raw)

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            end = next((i for i, ln in enumerate(lines) if ln.startswith("```")), 0)
            text = "\n".join(lines[1:end])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re

            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError(f"Failed to parse JSON from LLM output: {raw[:500]}")
