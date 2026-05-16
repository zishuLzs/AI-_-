from __future__ import annotations

import json
import logging
from typing import Any

from llm.client import LLMClient
from llm.prompts import PLANNER_REPAIR_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT
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
            compiled = self.compiler.compile(plan, question)
        except Exception as e:
            logger.warning("Planner compile failed, using local semantic fallback: %s", e)
            return self._compile_local_fallback(question, session_id)
        if self._needs_customer_but_missing(compiled):
            logger.warning("Compiled plan missing customer for single-customer tool path, using local fallback")
            return self._compile_local_fallback(question, session_id)
        if compiled.intent == "fallback":
            logger.warning("Compiled plan fell back to fallback intent, using local fallback")
            return self._compile_local_fallback(question, session_id)
        if self._violates_question_guardrail(question, compiled):
            logger.warning("Compiled plan violates question guardrail, using local fallback")
            return self._compile_local_fallback(question, session_id)
        return compiled

    def _repair(self, previous_output: str, error_detail: str) -> str:
        repair_prompt = (
            f"你之前的 planner JSON 需要修复。\n"
            f"错误原因：{error_detail}\n"
            f"请在尽量保留原语义的前提下，只输出修复后的合法 JSON。\n"
            f"若原输出明显把 cohort 题写成 single，或把 customer_count 写成 action_count，可以顺手修正。\n"
            f"之前的输出：\n{previous_output[-1500:]}"
        )
        return self.llm.chat(
            [
                {"role": "system", "content": PLANNER_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ],
            temperature=0.0,
            max_tokens=1024,
        )

    def _build_user_prompt(self, question: str, session_summary: dict[str, Any]) -> str:
        parts = [
            "请把下面问题转成语义 JSON。",
            "只输出 JSON。",
            f"当前问题：{question}",
            (
                "额外提醒：如果问题是显式群体题，不要因为上下文里有当前客户就改写成单客户题；"
                "如果问题是'发生过X行为的客户有多少个'，重点是客户数；"
                "如果问题是'谁的X行为次数最多'，重点是排序返回客户编号。"
            ),
        ]
        if session_summary:
            parts.append(
                "会话上下文仅可用于 follow-up 指代消解与长期偏好延续，"
                "不能覆盖当前问题的显式语义。"
            )
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

    @staticmethod
    def _needs_customer_but_missing(plan: PlannerOutput) -> bool:
        single_customer_tools = {
            "get_profile",
            "analyze_behavior_single",
            "calculate_retirement",
            "build_allocation",
            "product_query",
            "generate_proposal_payload",
        }
        if plan.customer_id:
            return False
        return any(tc.name in single_customer_tools for tc in plan.tool_calls)

    @staticmethod
    def _violates_question_guardrail(question: str, plan: PlannerOutput) -> bool:
        if (
            any(token in question for token in ("全投", "全买", "只投", "全部投资"))
            and any(token in question for token in ("够不够", "能否达成", "目标够不够", "还差多少钱"))
            and plan.case_tag not in {"allocation_goal_check", "product_query"}
        ):
            return True
        if any(token in question for token in ("寿命", "长寿")) and any(
            token in question for token in ("补哪类产品", "增加什么产品", "增加什么配置")
        ):
            return plan.case_tag != "allocation_longevity_adjust"
        if "未来一个星期" in question and "购买" in question:
            return plan.case_tag != "allocation_prediction"
        if "谁的" in question and any(token in question for token in ("购买", "收藏", "浏览")) and "次数最多" in question:
            return plan.case_tag != "behavior_ranking"
        if any(token in question for token in ("发生过购买行为的客户有多少个", "发生过收藏行为的客户有多少个")):
            return plan.case_tag != "behavior_stat"
        if "总共" in question and any(token in question for token in ("最低需要积攒", "预计总共可以积攒", "至少要准备")):
            return plan.case_tag != "retirement_aggregate"
        if any(token in question for token in ("不存在养老金缺口的客户有哪些", "没有养老资金缺口的客户有哪些", "哪几位客户依然没有养老资金缺口")):
            return plan.case_tag != "retirement_aggregate"
        return False
