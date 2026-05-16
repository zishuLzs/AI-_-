from __future__ import annotations

import json
import logging
from typing import Any

from llm.client import LLMClient
from llm.prompts import PLANNER_SYSTEM_PROMPT
from llm.schemas import PlannerOutput
from llm.validator import PlanValidator, PlanValidationError
from orchestrator.plan_compiler import PlanCompiler
from orchestrator.local_planner import LocalPlanner
from tools.memory_manager import MemoryManager
from tools.router import IntentRouter

logger = logging.getLogger(__name__)


class LLMPlanner:
    def __init__(
        self,
        llm_client: LLMClient,
        memory_manager: MemoryManager,
    ) -> None:
        self.llm = llm_client
        self.memory = memory_manager
        self.local_planner = LocalPlanner(IntentRouter(memory_manager))
        self.compiler = PlanCompiler()

    def plan(self, question: str, session_id: str) -> PlannerOutput:
        session_summary = self._build_session_summary(session_id)
        user_prompt = self._build_user_prompt(question, session_summary)
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        raw_output: str = ""
        try:
            raw_output = self.llm.chat(messages, temperature=0.0, max_tokens=1024)
            data = self.llm._extract_json(raw_output)
            plan = PlanValidator.validate(data)
        except (ValueError, json.JSONDecodeError, PlanValidationError) as e:
            logger.warning("Planner semantic parsing failed, attempting repair: %s", e)
            try:
                repaired_output = self._repair(raw_output, str(e))
                repaired_data = self.llm._extract_json(repaired_output)
                plan = PlanValidator.validate(repaired_data)
            except Exception as repair_error:
                logger.warning(
                    "Planner repair failed, using local semantic fallback: %s",
                    repair_error,
                )
                return self._compile_local_fallback(question, session_id)
        except Exception as e:
            logger.warning("Planner LLM call failed, using local semantic fallback: %s", e)
            return self._compile_local_fallback(question, session_id)

        if plan.customer_scope.type in {"single", "followup"} and not plan.customer_scope.customer_id:
            state = self.memory.get_session(session_id)
            if state.customer_id:
                plan.customer_scope.customer_id = state.customer_id

        try:
            return self.compiler.compile(plan, question)
        except Exception as e:
            logger.warning("Planner compile failed, using local semantic fallback: %s", e)
            return self._compile_local_fallback(question, session_id)

    def _repair(self, previous_output: str, error_detail: str) -> str:
        repair_prompt = (
            f"你之前的 JSON 输出不合法。错误原因：{error_detail}\n"
            f"请修正后重新只输出合法 JSON，不要其他任何文字。\n"
            f"之前的输出：\n{previous_output[-1500:]}"
        )
        return self.llm.chat(
            [{"role": "user", "content": repair_prompt}],
            temperature=0.0,
            max_tokens=1024,
        )

    def _build_user_prompt(self, question: str, session_summary: dict[str, Any]) -> str:
        parts = [f"当前问题：{question}"]
        if session_summary:
            parts.append(f"会话上下文：{json.dumps(session_summary, ensure_ascii=False)}")
        return "\n".join(parts)

    def _build_session_summary(self, session_id: str) -> dict[str, Any]:
        state = self.memory.get_session(session_id)
        summary: dict[str, Any] = {}
        if state.customer_id:
            summary["current_customer_id"] = state.customer_id
        if state.preferences:
            summary["preferences"] = state.preferences
        if state.focus_points:
            summary["focus_points"] = state.focus_points
        if state.scenario:
            summary["pending_scenario"] = state.scenario
        if state.last_case_tag:
            summary["last_case_tag"] = state.last_case_tag
        return summary

    def _compile_local_fallback(self, question: str, session_id: str) -> PlannerOutput:
        semantic = self.local_planner.build_semantic(question, session_id)
        return self.compiler.compile(semantic, question)
