from __future__ import annotations

import json
import logging
from typing import Any

from llm.client import LLMClient
from llm.prompts import COMPOSER_SYSTEM_PROMPT, PROPOSAL_SYSTEM_PROMPT
from llm.schemas import PlannerOutput

logger = logging.getLogger(__name__)


class LLMComposer:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or LLMClient()

    def compose(
        self,
        question: str,
        plan: PlannerOutput,
        tool_results: dict[str, Any],
    ) -> str:
        if plan.answer_mode == "proposal":
            return self._compose_proposal(tool_results)
        return self._compose_short(question, plan, tool_results)

    def _compose_short(
        self,
        question: str,
        plan: PlannerOutput,
        tool_results: dict[str, Any],
    ) -> str:
        payload = {
            "question": question,
            "intent": plan.intent,
            "tool_results": tool_results,
        }
        user_prompt = (
            f"根据以下结构化数据回答问题。\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            f"只输出最终答案。"
        )
        messages = [
            {"role": "system", "content": COMPOSER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        try:
            return self.llm.chat(messages, temperature=0.0, max_tokens=512).strip()
        except Exception as e:
            logger.warning("Composer failed, falling back to programmatic short answer: %s", e)
            return self._fallback_short(question, plan, tool_results)

    def _compose_proposal(self, tool_results: dict[str, Any]) -> str:
        payload = tool_results.get("generate_proposal_payload", tool_results)
        user_prompt = (
            f"根据以下结构化数据生成养老规划建议书：\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
        )
        messages = [
            {"role": "system", "content": PROPOSAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        try:
            proposal = self.llm.chat(
                messages, temperature=0.1, max_tokens=4096
            ).strip()
            if not self._proposal_has_required_sections(proposal):
                raise ValueError("Proposal missing required sections")
            return proposal
        except Exception as e:
            logger.error("Proposal generation failed: %s", e)
            return "抱歉，当前建议书生成失败。"

    def _fallback_short(
        self,
        question: str,
        plan: PlannerOutput,
        tool_results: dict[str, Any],
    ) -> str:
        """Minimal text extraction from structured results — not rule-based NLU."""
        for result in tool_results.values():
            if isinstance(result, str):
                return result
            if isinstance(result, dict):
                if "retirement_duration_text" in result:
                    return result["retirement_duration_text"]
                if "gap" in result:
                    gap = int(float(result["gap"]))
                    if gap <= 0:
                        return "在当前假设下不存在资金缺口"
                    return f"{gap} 元"
                if "result" in result:
                    return str(result["result"])
                if "avg_age" in result:
                    return f"{round(float(result['avg_age']))} 岁"
        return "抱歉，暂时无法回答该问题。"

    @staticmethod
    def _proposal_has_required_sections(text: str) -> bool:
        required = ["基本情况", "基本假设", "养老目标", "财富需求测算", "产品偏好", "资产配置", "建议"]
        return sum(1 for section in required if section in text) >= 5
