from __future__ import annotations

import json
import logging
from typing import Any

from llm.client import LLMClient
from llm.prompts import COMPOSER_SYSTEM_PROMPT, PROPOSAL_SYSTEM_PROMPT
from llm.schemas import PlannerOutput

logger = logging.getLogger(__name__)

_PROPOSAL_REQUIRED_SECTIONS = [
    "基本情况", "基本假设", "养老目标", "财富需求测算",
    "产品偏好", "资产配置", "建议",
]
_PROPOSAL_MIN_SECTIONS = 5  # Require at least 5 of 7 sections


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
            "case_tag": plan.case_tag,
            "answer_mode": plan.answer_mode,
            "tool_results": tool_results,
        }
        style_hint = self._build_case_style_hint(plan.case_tag)
        user_prompt = (
            f"根据以下结构化数据回答问题。\n"
            f"答题风格要求：{style_hint}\n"
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
            logger.error("Composer failed, falling back to programmatic short answer: %s", e)
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

    @staticmethod
    def _build_case_style_hint(case_tag: str) -> str:
        style_map = {
            "profile_single_value": "只输出最终值，例如“22 岁”“5000 元”“R3”。",
            "profile_count": "只输出计数结果，例如“2 个”。",
            "behavior_single_preference": "只输出产品名称，例如“现金理财”。",
            "behavior_aggregate_stat": "只输出最终统计值，例如“29 岁”。",
            "retirement_duration": "只输出时长，例如“12 年 7 个月”。",
            "retirement_monthly_spend": "只输出金额，例如“9076 元”。",
            "retirement_required_asset": "只输出金额，例如“985979 元”。",
            "retirement_accumulated_asset": "只输出金额，例如“772715 元”。",
            "allocation_prediction": "只输出最可能的产品名称。",
            "allocation_longevity_adjust": "只输出最应该增加配置的产品名称。",
            "allocation_goal_check": "先给出能否达成及调整结论，再用简短说明给出缺口和替代产品。",
            "allocation_max_return": "先给出最优配置结论，再用一句解释为什么。",
            "allocation_min_risk": "先给出比例方案，再用2到4句说明主力产品、最低比例和剩余比例用途。",
            "retirement_scenario_inflation": "第一行给最终金额，随后用极简步骤说明分段通胀和缺口测算。",
        }
        return style_map.get(case_tag, "只基于结构化数据给出简洁答案。")

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
                    try:
                        gap = int(float(result["gap"]))
                    except (ValueError, TypeError):
                        return "抱歉，暂时无法回答该问题。"
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
        return sum(1 for s in _PROPOSAL_REQUIRED_SECTIONS if s in text) >= _PROPOSAL_MIN_SECTIONS
