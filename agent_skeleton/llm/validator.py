from __future__ import annotations

import logging
from typing import Any

from llm.schemas import (
    ANSWER_MODE_ENUM,
    INTENT_ENUM,
    TOOL_WHITELIST,
    VALID_ACTION_TYPES,
    VALID_METRICS,
    VALID_PRODUCTS,
    PlannerOutput,
    MemoryUpdate,
    ToolCall,
)

logger = logging.getLogger(__name__)


class PlanValidationError(Exception):
    def __init__(self, failure_type: str, detail: str) -> None:
        self.failure_type = failure_type
        self.detail = detail
        super().__init__(f"[{failure_type}] {detail}")


class PlanValidator:
    @staticmethod
    def validate(data: dict[str, Any]) -> PlannerOutput:
        errors: list[str] = []

        intent = data.get("intent", "")
        if intent not in INTENT_ENUM:
            errors.append(f"invalid intent: {intent}")

        answer_mode = data.get("answer_mode", "short")
        if answer_mode not in ANSWER_MODE_ENUM:
            answer_mode = "short"

        customer_id = data.get("customer_id")
        if customer_id is not None and not isinstance(customer_id, str):
            errors.append("customer_id must be string or null")

        memory_update = PlanValidator._validate_memory_update(data.get("memory_update", {}))
        tool_calls = PlanValidator._validate_tool_calls(data.get("tool_calls", []))

        if errors:
            raise PlanValidationError("planner_schema_error", "; ".join(errors))

        return PlannerOutput(
            intent=intent,
            customer_id=customer_id,
            memory_update=memory_update,
            tool_calls=tool_calls,
            answer_mode=answer_mode,
        )

    @staticmethod
    def _validate_memory_update(mu_data: Any) -> MemoryUpdate:
        if not isinstance(mu_data, dict):
            return MemoryUpdate()
        prefs = mu_data.get("preferences", {})
        scenario = mu_data.get("scenario", {})
        if not isinstance(prefs, dict):
            prefs = {}
        if not isinstance(scenario, dict):
            scenario = {}

        allowed_pref_keys = frozenset(
            {
                "retirement_goal",
                "retirement_goal_monthly_expend",
                "risk_preference_text",
                "focus_points",
            }
        )
        allowed_scenario_keys = frozenset(
            {"inflation_annual", "extra_monthly_saving", "retirement_goal_monthly_expend"}
        )
        preferences = {k: v for k, v in prefs.items() if k in allowed_pref_keys}
        scenario_clean = {k: v for k, v in scenario.items() if k in allowed_scenario_keys}

        if "focus_points" in preferences:
            fps = preferences["focus_points"]
            if isinstance(fps, list):
                preferences["focus_points"] = [str(fp) for fp in fps]
            else:
                preferences["focus_points"] = [str(fps)]

        return MemoryUpdate(preferences=preferences, scenario=scenario_clean)

    @staticmethod
    def _validate_tool_calls(tc_data: Any) -> list[ToolCall]:
        if not isinstance(tc_data, list):
            return []
        result: list[ToolCall] = []
        for tc in tc_data:
            if not isinstance(tc, dict):
                continue
            name = tc.get("name", "")
            if name not in TOOL_WHITELIST:
                continue
            params = tc.get("params", {})
            if not isinstance(params, dict):
                params = {}
            PlanValidator._validate_tool_params(name, params)
            result.append(ToolCall(name=name, params=params))
        return result

    @staticmethod
    def _validate_tool_params(name: str, params: dict[str, Any]) -> None:
        if name in ("get_profile", "analyze_behavior_single", "calculate_retirement",
                     "build_allocation", "generate_proposal_payload"):
            if "customer_id" in params and not isinstance(params["customer_id"], str):
                raise PlanValidationError(
                    "planner_invalid_tool",
                    f"{name}: customer_id must be string",
                )

        if name == "analyze_behavior_aggregate":
            metric = params.get("metric", "")
            if metric and metric not in VALID_METRICS:
                raise PlanValidationError(
                    "planner_invalid_tool",
                    f"analyze_behavior_aggregate: invalid metric '{metric}'",
                )
            product = params.get("product", "")
            if product and product not in VALID_PRODUCTS:
                raise PlanValidationError(
                    "planner_invalid_tool",
                    f"analyze_behavior_aggregate: invalid product '{product}'",
                )
            action_type = params.get("action_type", "")
            if action_type and action_type not in VALID_ACTION_TYPES:
                raise PlanValidationError(
                    "planner_invalid_tool",
                    f"analyze_behavior_aggregate: invalid action_type '{action_type}'",
                )
