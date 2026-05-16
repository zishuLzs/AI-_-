from __future__ import annotations

import logging
from typing import Any

from llm.schemas import PlannerOutput, ToolCall
from models import SessionState
from orchestrator.failures import FailureCategory, FailureRecord
from skills.allocation_planning import AllocationPlanningSkill
from skills.behavior_analysis import BehaviorAnalysisSkill
from skills.customer_profile import CustomerProfileSkill
from skills.retirement_calc import RetirementCalculationSkill
from tools.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        profile_skill: CustomerProfileSkill,
        behavior_skill: BehaviorAnalysisSkill,
        retirement_skill: RetirementCalculationSkill,
        allocation_skill: AllocationPlanningSkill,
        memory_manager: MemoryManager,
    ) -> None:
        self.profile_skill = profile_skill
        self.behavior_skill = behavior_skill
        self.retirement_skill = retirement_skill
        self.allocation_skill = allocation_skill
        self.memory = memory_manager

    def execute(self, plan: PlannerOutput, session_id: str, question: str) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for tc in plan.tool_calls:
            try:
                results[tc.name] = self._dispatch(tc, session_id, question)
            except Exception as e:
                logger.error("Tool execution failed: %s | %s", tc.name, e)
                record = FailureRecord(
                    category=FailureCategory.TOOL_EXECUTION_ERROR,
                    question=question,
                    detail=f"Tool '{tc.name}' failed: {e}",
                )
                raise ToolExecutionFailure(record) from e

        self._apply_memory_update(session_id, plan)
        return results

    def _apply_memory_update(self, session_id: str, plan: PlannerOutput) -> None:
        mu = plan.memory_update
        if plan.customer_id:
            self.memory.set_customer_id(session_id, plan.customer_id)
        if mu.preferences:
            self.memory.remember_preferences(session_id, mu.preferences)
        if mu.scenario:
            self.memory.remember_scenario(session_id, mu.scenario)
        self.memory.set_last_case_tag(session_id, plan.case_tag)

    def _dispatch(self, tc: ToolCall, session_id: str, question: str) -> Any:
        name = tc.name
        params = tc.params

        if name == "get_profile":
            cid = params.get("customer_id", "") or self.memory.get_session(session_id).customer_id
            if not cid:
                raise ValueError("get_profile requires customer_id")
            profile = self.profile_skill.get_profile(session_id, cid)
            return {
                "age": profile.age,
                "gender": profile.gender,
                "risk_level": profile.risk_level,
                "net_asset": str(profile.net_asset),
                "monthly_income": str(profile.monthly_income),
                "monthly_expend": str(profile.monthly_expend),
                "monthly_saving": str(profile.monthly_saving),
                "pension": str(profile.pension),
                "enterprise_ann": str(profile.enterprise_ann),
            }

        if name == "count_customers":
            synthetic_q = self._build_count_question(params)
            return self.profile_skill._answer_count_question(synthetic_q)

        if name == "avg_customers":
            synthetic_q = self._build_avg_question(params)
            return self.profile_skill._answer_avg_question(synthetic_q)

        if name == "analyze_behavior_single":
            cid = params.get("customer_id", "") or self.memory.get_session(session_id).customer_id
            if not cid:
                raise ValueError("analyze_behavior_single requires customer_id")
            return self.behavior_skill.analyze(cid)

        if name == "analyze_behavior_aggregate":
            return self._execute_behavior_aggregate(params)

        if name == "calculate_retirement":
            cid = params.get("customer_id", "") or self.memory.get_session(session_id).customer_id
            if not cid:
                raise ValueError("calculate_retirement requires customer_id")
            result = self.retirement_skill.calculate(session_id, cid)
            return {
                "retirement_age_years": result.retirement_age_years,
                "retirement_age_months": result.retirement_age_months,
                "months_to_retirement": result.months_to_retirement,
                "retirement_duration_text": result.retirement_duration_text,
                "retirement_monthly_expend": str(result.retirement_monthly_expend),
                "required_asset_at_retirement": str(result.required_asset_at_retirement),
                "accumulated_asset_at_retirement": str(result.accumulated_asset_at_retirement),
                "gap": str(result.gap),
            }

        if name == "build_allocation":
            cid = params.get("customer_id", "") or self.memory.get_session(session_id).customer_id
            if not cid:
                raise ValueError("build_allocation requires customer_id")
            plan_obj = self.allocation_skill.plan(session_id, cid)
            return {
                "allocation": [
                    {
                        "product": item.product,
                        "weight": str(item.weight),
                        "expected_return": str(item.expected_return),
                    }
                    for item in plan_obj.allocation
                    if item.weight > 0
                ],
                "portfolio_return": str(plan_obj.portfolio_return),
                "portfolio_risk": str(plan_obj.portfolio_risk),
                "retirement_asset_projection": str(plan_obj.retirement_asset_projection),
                "covers_gap": plan_obj.covers_gap,
                "reasoning_tags": plan_obj.reasoning_tags,
            }

        if name == "generate_proposal_payload":
            cid = params.get("customer_id", "") or self.memory.get_session(session_id).customer_id
            if not cid:
                raise ValueError("generate_proposal_payload requires customer_id")
            return self._build_proposal_payload(session_id, cid)

        if name == "update_memory":
            return {}

        raise ValueError(f"Unknown tool: {name}")

    @staticmethod
    def _build_count_question(params: dict[str, Any]) -> str:
        field = params.get("field", "")
        operator = params.get("operator", "")
        value = params.get("value")
        if field == "age" and operator == ">=" and value is not None:
            return f"多少客户年龄在{value}岁及以上"
        if field == "age" and operator == "<" and value is not None:
            return f"多少客户年龄在{value}岁以下"
        return "总共有多少客户"

    @staticmethod
    def _build_avg_question(params: dict[str, Any]) -> str:
        field = params.get("field", "")
        if field == "age":
            return "客户的平均年龄"
        if field == "monthly_income":
            return "客户的平均收入"
        return f"客户的平均{field}"

    def _execute_behavior_aggregate(self, params: dict[str, Any]) -> dict[str, Any]:
        metric = params.get("metric", "avg_age")
        product = params.get("product", "")
        action_type = params.get("action_type", "浏览")
        min_count = params.get("min_count", 1)

        product_to_keywords = {
            "权益类产品": ("权益", "浏览"),
            "短债类产品": ("短债", "浏览"),
            "固收+产品": ("固收", "浏览"),
            "现金理财": ("现金理财", "浏览"),
            "定期存款": ("定期存款", "浏览"),
            "年金险": ("年金险", "浏览"),
        }
        keywords = product_to_keywords.get(product, (product, action_type))
        synthetic_q = (
            f"{action_type}{keywords[0]}类产品{min_count}次及以上的客户的平均年龄是多少"
        )
        result = self.behavior_skill._answer_avg_age_by_behavior(synthetic_q)
        return {"query": synthetic_q, "result": result}

    def _build_proposal_payload(self, session_id: str, customer_id: str) -> dict[str, Any]:
        state = self.memory.get_session(session_id)
        profile = self.profile_skill.get_profile(session_id, customer_id)
        behavior = self.behavior_skill.analyze(customer_id)
        retirement = self.retirement_skill.calculate(session_id, customer_id)
        allocation = self.allocation_skill.plan(session_id, customer_id)

        return {
            "profile": {
                "customer_id": customer_id,
                "age": profile.age,
                "gender": profile.gender,
                "risk_level": profile.risk_level,
                "net_asset": str(profile.net_asset),
                "monthly_income": str(profile.monthly_income),
                "monthly_expend": str(profile.monthly_expend),
                "monthly_saving": str(profile.monthly_saving),
                "pension": str(profile.pension),
                "enterprise_ann": str(profile.enterprise_ann),
            },
            "assumptions": {
                "system": {
                    "inflation_annual": "0.02",
                    "default_return_annual": "0.02",
                    "life_expectancy": 80,
                    "current_date": "2025-03-31",
                },
                "preferences": state.preferences,
                "scenario": state.scenario,
            },
            "behavior_summary": {
                "top_product": behavior.get("top_product"),
                "counts": behavior.get("counts"),
                "insight": behavior.get("insight"),
            },
            "retirement_result": {
                "retirement_duration_text": retirement.retirement_duration_text,
                "retirement_monthly_expend": str(retirement.retirement_monthly_expend),
                "required_asset_at_retirement": str(retirement.required_asset_at_retirement),
                "accumulated_asset_at_retirement": str(retirement.accumulated_asset_at_retirement),
                "gap": str(retirement.gap),
            },
            "allocation_plan": {
                "allocation": [
                    {"product": item.product, "weight": str(item.weight)}
                    for item in allocation.allocation
                    if item.weight > 0
                ],
                "portfolio_return": str(allocation.portfolio_return),
                "covers_gap": allocation.covers_gap,
                "reasoning_tags": allocation.reasoning_tags,
            },
            "focus_points": state.focus_points,
            "preferences": state.preferences,
            "proposal_guidance": self._build_proposal_guidance(state),
        }

    @staticmethod
    def _build_proposal_guidance(state: SessionState) -> dict[str, Any]:
        pref_goal = state.preferences.get("retirement_goal")
        scenario_goal = state.scenario.get("retirement_goal")
        pref_goal_expend = state.preferences.get("retirement_goal_monthly_expend")
        scenario_goal_expend = state.scenario.get("retirement_goal_monthly_expend")
        pref_objective = state.preferences.get("allocation_objective")
        scenario_objective = state.scenario.get("allocation_objective")

        guidance: dict[str, Any] = {
            "effective_retirement_goal": pref_goal or scenario_goal,
            "retirement_goal_source": (
                "preference" if pref_goal else "scenario" if scenario_goal else "none"
            ),
            "effective_retirement_goal_monthly_expend": (
                pref_goal_expend if pref_goal_expend is not None else scenario_goal_expend
            ),
            "retirement_goal_monthly_expend_source": (
                "preference"
                if pref_goal_expend is not None
                else "scenario"
                if scenario_goal_expend is not None
                else "none"
            ),
            "effective_allocation_objective": (
                pref_objective if pref_objective is not None else scenario_objective
            ),
            "allocation_objective_source": (
                "preference"
                if pref_objective is not None
                else "scenario"
                if scenario_objective is not None
                else "none"
            ),
            "conflict_notes": [],
        }

        conflict_notes: list[str] = []
        if (
            pref_objective is not None
            and scenario_objective is not None
            and pref_objective != scenario_objective
        ):
            conflict_notes.append(
                "客户长期观点与本轮临时假设在资产配置目标上冲突，最终建议书必须以长期观点为准。"
            )
        if (
            pref_goal_expend is not None
            and scenario_goal_expend is not None
            and pref_goal_expend != scenario_goal_expend
        ):
            conflict_notes.append(
                "客户长期养老目标金额与本轮临时假设金额不同，建议书中的正式养老目标必须优先采用长期目标。"
            )
        guidance["conflict_notes"] = conflict_notes
        return guidance


class ToolExecutionFailure(Exception):
    def __init__(self, record: FailureRecord) -> None:
        self.record = record
        super().__init__(f"[{record.category.value}] {record.detail}")
