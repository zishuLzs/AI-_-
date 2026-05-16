from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TASK_ENUM = (
    "query",
    "analyze",
    "recommend",
    "proposal",
    "record_context",
    "fallback",
)

DOMAIN_ENUM = (
    "profile",
    "behavior",
    "retirement",
    "allocation",
    "proposal",
    "context",
    "fallback",
)

SCOPE_ENUM = ("single", "cohort", "followup")

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

VALID_METRICS = frozenset(
    {
        "age",
        "avg_age",
        "monthly_income",
        "monthly_expend",
        "monthly_saving",
        "net_asset",
        "pension",
        "enterprise_ann",
        "risk_level",
    }
)
VALID_PRODUCTS = frozenset(
    {"现金理财", "定期存款", "短债类产品", "固收+产品", "权益类产品", "年金险"}
)
VALID_ACTION_TYPES = frozenset({"浏览", "购买", "浏览详情", "浏览持仓", "收藏", "赎回"})


@dataclass
class FilterCondition:
    field: str
    op: str
    value: Any = None


@dataclass
class CustomerScope:
    type: str = "single"
    customer_id: str | None = None


@dataclass
class QuerySemantics:
    metric: str = ""
    aggregation: str = "value"
    filters: list[FilterCondition] = field(default_factory=list)
    comparison: dict[str, Any] | None = None


@dataclass
class SemanticPlan:
    task: str = "query"
    domain: str = "fallback"
    customer_scope: CustomerScope = field(default_factory=CustomerScope)
    query_semantics: QuerySemantics = field(default_factory=QuerySemantics)
    memory_update: MemoryUpdate = field(default_factory=lambda: MemoryUpdate())
    response_style: str = "short"
    raw_notes: str = ""

    @property
    def case_tag(self) -> str:
        text = self.raw_notes or ""
        metric = self.query_semantics.metric
        aggregation = self.query_semantics.aggregation
        scope_type = self.customer_scope.type
        objective = (
            self.memory_update.preferences.get("allocation_objective")
            or self.memory_update.scenario.get("allocation_objective")
            or ""
        )

        if self.task == "proposal" or self.domain == "proposal":
            return "proposal_full"
        if self.task == "record_context" or self.domain == "context":
            return "context_preference"
        if self.domain == "profile":
            if aggregation == "argmax_customer":
                return "profile_ranking"
            if aggregation == "count":
                return "profile_count"
            if aggregation in {"avg", "median", "sum"} or scope_type == "cohort":
                return "profile_aggregate_value"
            return "profile_single_value"
        if self.domain == "behavior":
            if metric == "top_product":
                return "behavior_single_preference"
            if aggregation == "argmax_customer":
                return "behavior_ranking"
            if metric == "avg_age" or aggregation == "avg":
                return "behavior_aggregate_stat"
            return "behavior_stat"
        if self.domain == "retirement":
            if metric == "duration":
                return "retirement_duration"
            if metric == "monthly_spend":
                return "retirement_monthly_spend"
            if metric == "no_gap":
                return "retirement_aggregate"
            if metric == "required_asset":
                return "retirement_aggregate" if aggregation == "sum" else "retirement_required_asset"
            if metric == "accumulated_asset":
                return "retirement_aggregate" if aggregation == "sum" else "retirement_accumulated_asset"
            if metric == "gap":
                if aggregation == "argmax_customer":
                    return "retirement_ranking"
                if aggregation in {"sum", "list_customer_ids"}:
                    return "retirement_aggregate"
                return "retirement_gap"
            if "通胀" in text and any(token in text for token in ("年后", "分段", "提升到", "升到", "变为")):
                return "retirement_scenario_inflation"
            return "retirement_gap"
        if self.domain == "allocation":
            if metric == "prediction":
                return "allocation_prediction"
            if metric == "longevity_adjust":
                return "allocation_longevity_adjust"
            if metric in {"portfolio_return", "portfolio_risk", "retirement_asset_projection"}:
                return "allocation_metric"
            if metric in {"shortfall", "adjustment"}:
                return "allocation_goal_check"
            if metric in {"lowest_covering_product", "max_projection_product"}:
                return "product_query"
            if objective == "maximize_return" or "收益最大化" in text or "最大化投资收益" in text:
                return "allocation_max_return"
            if objective == "minimize_risk" or "最小化风险波动" in text or "最小风险" in text or "尽量稳一点" in text:
                return "allocation_min_risk"
            if metric == "feasibility":
                if "收益率最低但能够覆盖养老缺口" in text or "哪种单一产品攒得最多" in text:
                    return "product_query"
                return "allocation_goal_check"
            return "allocation_metric"
        return "fallback_unknown"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticPlan":
        scope_data = data.get("customer_scope", {})
        query_data = data.get("query_semantics", {})
        mu_data = data.get("memory_update", {})
        if not isinstance(mu_data, dict):
            mu_data = {}
        if "preferences" not in mu_data and isinstance(data.get("preferences"), dict):
            mu_data["preferences"] = data.get("preferences", {})
        if "scenario" not in mu_data and isinstance(data.get("scenario"), dict):
            mu_data["scenario"] = data.get("scenario", {})
        filters = []
        for item in query_data.get("filters", []) or []:
            if isinstance(item, dict):
                filters.append(
                    FilterCondition(
                        field=str(item.get("field", "")),
                        op=str(item.get("op", "")),
                        value=item.get("value"),
                    )
                )
        return cls(
            task=str(data.get("task", data.get("intent", "fallback"))),
            domain=str(data.get("domain", data.get("intent", "fallback"))),
            customer_scope=CustomerScope(
                type=str(scope_data.get("type", "single")),
                customer_id=scope_data.get("customer_id"),
            ),
            query_semantics=QuerySemantics(
                metric=str(query_data.get("metric", "")),
                aggregation=str(query_data.get("aggregation", "value")),
                filters=filters,
                comparison=query_data.get("comparison"),
            ),
            memory_update=MemoryUpdate(
                preferences=mu_data.get("preferences", {}) if isinstance(mu_data, dict) else {},
                scenario=mu_data.get("scenario", {}) if isinstance(mu_data, dict) else {},
            ),
            response_style=str(data.get("response_style", data.get("answer_mode", "short"))),
            raw_notes=str(data.get("notes", "")),
        )


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
    semantic_plan: SemanticPlan | None = None

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
            semantic_plan=None,
        )

    @classmethod
    def from_semantic_plan(
        cls,
        semantic_plan: SemanticPlan,
        *,
        intent: str,
        customer_id: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        answer_mode: str | None = None,
        case_tag: str | None = None,
    ) -> "PlannerOutput":
        return cls(
            intent=intent,
            customer_id=customer_id,
            memory_update=semantic_plan.memory_update,
            tool_calls=tool_calls or [],
            answer_mode=answer_mode or semantic_plan.response_style,
            case_tag=case_tag or semantic_plan.case_tag,
            semantic_plan=semantic_plan,
        )


@dataclass
class ComposerInput:
    question: str
    intent: str
    tool_results: dict[str, Any] = field(default_factory=dict)
    answer_mode: str = "short"
