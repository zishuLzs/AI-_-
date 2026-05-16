from __future__ import annotations

import logging
from typing import Any

from llm.schemas import (
    DOMAIN_ENUM,
    SCOPE_ENUM,
    TASK_ENUM,
    VALID_ACTION_TYPES,
    VALID_METRICS,
    VALID_PRODUCTS,
    CustomerScope,
    FilterCondition,
    MemoryUpdate,
    QuerySemantics,
    SemanticPlan,
)

logger = logging.getLogger(__name__)


class PlanValidationError(Exception):
    def __init__(self, failure_type: str, detail: str) -> None:
        self.failure_type = failure_type
        self.detail = detail
        super().__init__(f"[{failure_type}] {detail}")


class PlanValidator:
    @staticmethod
    def validate(data: dict[str, Any]) -> SemanticPlan:
        errors: list[str] = []

        task = str(data.get("task", data.get("intent", "fallback")))
        if task not in TASK_ENUM:
            task = "fallback"

        domain = str(data.get("domain", data.get("intent", "fallback")))
        if domain not in DOMAIN_ENUM:
            domain = "fallback"

        response_style = str(data.get("response_style", data.get("answer_mode", "short")))
        if response_style not in {"short", "normal", "proposal"}:
            response_style = "short"

        scope_data = data.get("customer_scope", {})
        if not isinstance(scope_data, dict):
            scope_data = {}
        scope_type = str(scope_data.get("type", "single"))
        if scope_type not in SCOPE_ENUM:
            scope_type = "single"
        customer_id = scope_data.get("customer_id")
        if customer_id is not None and not isinstance(customer_id, str):
            errors.append("customer_scope.customer_id must be string or null")

        mu_payload = data.get("memory_update", {})
        if not isinstance(mu_payload, dict):
            mu_payload = {}
        if "preferences" not in mu_payload and isinstance(data.get("preferences"), dict):
            mu_payload["preferences"] = data.get("preferences", {})
        if "scenario" not in mu_payload and isinstance(data.get("scenario"), dict):
            mu_payload["scenario"] = data.get("scenario", {})
        mu = PlanValidator._validate_memory_update(mu_payload)
        semantics = PlanValidator._validate_query_semantics(data.get("query_semantics", {}))

        if errors:
            raise PlanValidationError("planner_schema_error", "; ".join(errors))

        return SemanticPlan(
            task=task,
            domain=domain,
            customer_scope=CustomerScope(type=scope_type, customer_id=customer_id),
            query_semantics=semantics,
            memory_update=mu,
            response_style=response_style,
            raw_notes=str(data.get("notes", "")),
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
                "allocation_objective",
            }
        )
        allowed_scenario_keys = frozenset(
            {
                "inflation_annual",
                "inflation_after_years",
                "inflation_after_years_annual",
                "extra_monthly_saving",
                "retirement_goal_monthly_expend",
                "allocation_objective",
            }
        )
        preferences = {k: v for k, v in prefs.items() if k in allowed_pref_keys}
        scenario_clean = {k: v for k, v in scenario.items() if k in allowed_scenario_keys}

        dropped_prefs = set(prefs) - allowed_pref_keys
        dropped_scenario = set(scenario) - allowed_scenario_keys
        if dropped_prefs:
            logger.warning("Dropping unknown preference keys: %s", dropped_prefs)
        if dropped_scenario:
            logger.warning("Dropping unknown scenario keys: %s", dropped_scenario)

        if "focus_points" in preferences:
            fps = preferences["focus_points"]
            if isinstance(fps, list):
                preferences["focus_points"] = [str(fp) for fp in fps]
            else:
                preferences["focus_points"] = [str(fps)]

        return MemoryUpdate(preferences=preferences, scenario=scenario_clean)

    @staticmethod
    def _validate_query_semantics(qs_data: Any) -> QuerySemantics:
        if not isinstance(qs_data, dict):
            return QuerySemantics()

        metric = str(qs_data.get("metric", ""))
        aggregation = str(qs_data.get("aggregation", "value"))
        if aggregation not in {"value", "count", "avg", "sum", "median", "argmax_customer", "list_customer_ids"}:
            aggregation = "value"

        if metric and metric not in VALID_METRICS and metric not in {
            "top_product",
            "action_count",
            "customer_count",
            "max_customer_id",
            "no_gap",
            "allocation_plan",
            "portfolio_return",
            "portfolio_risk",
            "retirement_asset_projection",
            "required_asset",
            "accumulated_asset",
            "gap",
            "duration",
            "monthly_spend",
            "feasibility",
            "shortfall",
            "adjustment",
            "longevity_adjust",
        }:
            logger.warning("Unrecognized semantic metric: %s", metric)

        filters_raw = qs_data.get("filters", [])
        filters: list[FilterCondition] = []
        if isinstance(filters_raw, list):
            for item in filters_raw:
                if not isinstance(item, dict):
                    continue
                field = str(item.get("field", ""))
                op = str(item.get("op", ""))
                value = item.get("value")
                filters.append(FilterCondition(field=field, op=op, value=value))
                if field == "product" and value and str(value) not in VALID_PRODUCTS:
                    logger.warning("Unrecognized product filter: %s", value)
                if field == "action_type" and value and str(value) not in VALID_ACTION_TYPES:
                    logger.warning("Unrecognized action filter: %s", value)

        comparison = qs_data.get("comparison")
        if comparison is not None and not isinstance(comparison, dict):
            comparison = None

        return QuerySemantics(
            metric=metric,
            aggregation=aggregation,
            filters=filters,
            comparison=comparison,
        )
