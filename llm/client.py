from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

ONE_API_URL = os.getenv(
    "ONE_API_URL", "https://one-api-other.nowcoder.com/v1/chat/completions"
)
ONE_API_KEY = os.getenv("ONE_API_KEY", "YOUR_ONE_API_KEY")
DEFAULT_MODEL = os.getenv("ONE_API_MODEL", "qwen3.6-flash")
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0


class LLMClient:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or DEFAULT_MODEL

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
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
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                logger.warning("LLM API request failed (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_BASE * (2 ** attempt))
                continue

            try:
                resp.raise_for_status()
            except requests.HTTPError as e:
                if resp.status_code in (429, 502, 503) and attempt < MAX_RETRIES - 1:
                    logger.warning("LLM API HTTP %d (attempt %d/%d), retrying", resp.status_code, attempt + 1, MAX_RETRIES)
                    time.sleep(RETRY_DELAY_BASE * (2 ** attempt))
                    last_exc = e
                    continue
                raise

            body: dict[str, Any] = resp.json()
            if "choices" not in body:
                error_msg = body.get("error", {}).get("message", str(body))
                raise ValueError(f"LLM API returned error: {error_msg}")
            return body["choices"][0]["message"]["content"]

        raise RuntimeError(f"All {MAX_RETRIES} LLM API retries exhausted") from last_exc

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
            # Find closing fence starting from index 1 to skip the opening fence
            end = next(
                (i for i, ln in enumerate(lines[1:], start=1) if ln.strip().startswith("```")),
                len(lines),
            )
            text = "\n".join(lines[1:end]).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re

            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"Failed to parse JSON from LLM output: {raw[:500]}")
