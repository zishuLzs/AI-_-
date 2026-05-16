from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INTENT_ENUM = (
    "profile",
    "behavior",
    "retirement",
    "allocation",
    "proposal",
    "context",
    "fallback",
)

ANSWER_MODE_ENUM = ("short", "normal", "proposal")

CASE_TAG_ENUM = (
    "profile_single_value",
    "profile_count",
    "profile_aggregate_value",
    "profile_ranking",
    "behavior_single_preference",
    "behavior_aggregate_stat",
    "behavior_stat",
    "behavior_ranking",
    "retirement_duration",
    "retirement_monthly_spend",
    "retirement_required_asset",
    "retirement_accumulated_asset",
    "retirement_gap",
    "retirement_aggregate",
    "retirement_ranking",
    "allocation_goal_check",
    "allocation_prediction",
    "allocation_longevity_adjust",
    "allocation_max_return",
    "allocation_min_risk",
    "allocation_metric",
    "product_query",
    "retirement_scenario_inflation",
    "proposal_full",
    "context_preference",
    "fallback_unknown",
)

TOOL_WHITELIST = frozenset(
    {
        "get_profile",
        "profile_query",
        "count_customers",
        "avg_customers",
        "analyze_behavior_single",
        "behavior_query",
        "analyze_behavior_aggregate",
        "calculate_retirement",
        "retirement_query",
        "build_allocation",
        "product_query",
        "generate_proposal_payload",
        "update_memory",
    }
)

VALID_METRICS = frozenset({"age", "avg_age", "monthly_income", "monthly_expend", "net_asset"})
VALID_PRODUCTS = frozenset(
    {"现金理财", "定期存款", "短债类产品", "固收+产品", "权益类产品", "年金险"}
)
VALID_ACTION_TYPES = frozenset({"浏览", "购买", "浏览详情", "浏览持仓", "收藏", "赎回"})


@dataclass
class ToolCall:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryUpdate:
    preferences: dict[str, Any] = field(default_factory=dict)
    scenario: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlannerOutput:
    intent: str
    customer_id: str | None = None
    memory_update: MemoryUpdate = field(default_factory=MemoryUpdate)
    tool_calls: list[ToolCall] = field(default_factory=list)
    answer_mode: str = "short"
    case_tag: str = "fallback_unknown"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlannerOutput":
        mu_data = data.get("memory_update", {})
        memory_update = MemoryUpdate(
            preferences=mu_data.get("preferences", {}),
            scenario=mu_data.get("scenario", {}),
        )
        tool_calls = [
            ToolCall(name=tc["name"], params=tc.get("params", {}))
            for tc in data.get("tool_calls", [])
        ]
        return cls(
            intent=data.get("intent", "fallback"),
            customer_id=data.get("customer_id"),
            memory_update=memory_update,
            tool_calls=tool_calls,
            answer_mode=data.get("answer_mode", "short"),
            case_tag=data.get("case_tag", "fallback_unknown"),
        )


@dataclass
class ComposerInput:
    question: str
    intent: str
    tool_results: dict[str, Any] = field(default_factory=dict)
    answer_mode: str = "short"
