from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm.schemas import (
    CustomerScope,
    FilterCondition,
    PlannerOutput,
    QuerySemantics,
    SemanticPlan,
    ToolCall,
)


@dataclass
class PlanCompiler:
    """Translate semantic plans into executable tool plans."""

    def compile(self, semantic_plan: SemanticPlan, question: str = "") -> PlannerOutput:
        intent = self._resolve_intent(semantic_plan)
        case_tag = self._resolve_case_tag(semantic_plan, question)
        tool_calls = self._build_tool_calls(semantic_plan, question)
        answer_mode = self._resolve_answer_mode(semantic_plan, case_tag)

        return PlannerOutput.from_semantic_plan(
            semantic_plan,
            intent=intent,
            customer_id=semantic_plan.customer_scope.customer_id,
            tool_calls=tool_calls,
            answer_mode=answer_mode,
            case_tag=case_tag,
        )

    @staticmethod
    def _resolve_intent(plan: SemanticPlan) -> str:
        if plan.task == "proposal" or plan.domain == "proposal":
            return "proposal"
        if plan.task == "record_context" or plan.domain == "context":
            return "context"
        if plan.task == "fallback" or plan.domain == "fallback":
            return "fallback"
        if plan.domain in {"profile", "behavior", "retirement", "allocation"}:
            return plan.domain
        if plan.task == "recommend":
            return "allocation"
        if plan.task in {"query", "analyze"}:
            return plan.domain if plan.domain in {"profile", "behavior", "retirement", "allocation"} else "fallback"
        return "fallback"

    @staticmethod
    def _resolve_answer_mode(plan: SemanticPlan, case_tag: str) -> str:
        if case_tag == "proposal_full":
            return "proposal"
        if case_tag in {
            "allocation_goal_check",
            "allocation_max_return",
            "allocation_min_risk",
            "retirement_scenario_inflation",
            "product_query",
        }:
            return "normal"
        if plan.response_style in {"short", "normal", "proposal"}:
            return plan.response_style
        return "short"

    def _resolve_case_tag(self, plan: SemanticPlan, question: str) -> str:
        semantic_tag = plan.case_tag

        if plan.domain == "allocation":
            metric = plan.query_semantics.metric
            if metric == "feasibility":
                if "收益率最低但能够覆盖养老缺口" in question or "哪种单一产品攒得最多" in question:
                    return "product_query"
                if "如不能" in question or "如何调整" in question:
                    return "allocation_goal_check"
            if metric in {"shortfall", "lowest_covering_product", "max_projection_product"}:
                return "product_query"
            if metric == "prediction":
                return "allocation_prediction"
            if metric == "longevity_adjust":
                return "allocation_longevity_adjust"
            if metric in {"portfolio_return", "portfolio_risk", "retirement_asset_projection"}:
                return "allocation_metric"
            if metric in {"adjustment"}:
                return "allocation_goal_check"

        if plan.domain == "retirement":
            if "通胀" in question and any(token in question for token in ("年后", "分段", "提升到", "升到", "变为")):
                return "retirement_scenario_inflation"
            if plan.query_semantics.aggregation == "sum" and plan.query_semantics.metric in {"required_asset", "accumulated_asset"}:
                return "retirement_aggregate"
            if plan.query_semantics.aggregation == "list_customer_ids":
                return "retirement_aggregate"

        return semantic_tag

    def _build_tool_calls(self, plan: SemanticPlan, question: str) -> list[ToolCall]:
        intent = self._resolve_intent(plan)

        if intent == "profile":
            return self._build_profile_tools(plan, question)
        if intent == "behavior":
            return self._build_behavior_tools(plan, question)
        if intent == "retirement":
            return self._build_retirement_tools(plan, question)
        if intent == "allocation":
            return self._build_allocation_tools(plan, question)
        if intent == "proposal":
            return [ToolCall(name="generate_proposal_payload", params=self._customer_param(plan.customer_scope))]
        return []

    def _build_profile_tools(self, plan: SemanticPlan, question: str) -> list[ToolCall]:
        q = plan.query_semantics
        if self._is_profile_count_question(question):
            params = {"field": q.metric or "age", "agg": "count"}
            params.update(self._profile_filter_params(q))
            return [ToolCall(name="profile_query", params=params)]
        if plan.customer_scope.type in {"single", "followup"} and q.aggregation == "value":
            return [ToolCall(name="get_profile", params=self._customer_param(plan.customer_scope))]

        params = {"field": q.metric or "age", "agg": q.aggregation or "count"}
        params.update(self._profile_filter_params(q))
        return [ToolCall(name="profile_query", params=params)]

    def _build_behavior_tools(self, plan: SemanticPlan, question: str) -> list[ToolCall]:
        q = plan.query_semantics
        if q.metric == "top_product" and plan.customer_scope.type in {"single", "followup"}:
            return [ToolCall(name="analyze_behavior_single", params=self._customer_param(plan.customer_scope))]

        normalized_metric = q.metric
        if "平均年龄" in question:
            normalized_metric = "avg_age"
        elif "谁的" in question:
            normalized_metric = "max_customer_id"
        elif "多少客户" in question or "有多少个" in question:
            normalized_metric = "customer_count"
        elif "多少次" in question or "几次" in question:
            normalized_metric = "action_count"

        normalized_query = QuerySemantics(
            metric=normalized_metric,
            aggregation=q.aggregation,
            filters=q.filters,
            comparison=q.comparison,
        )
        params: dict[str, Any] = {
            "agg": self._behavior_agg(normalized_query, plan.customer_scope),
            "action_type": self._behavior_action_type(normalized_query),
            "product": self._behavior_product(normalized_query),
            "min_count": self._behavior_min_count(normalized_query),
        }
        if plan.customer_scope.customer_id and params["agg"] == "customer_action_count":
            params["customer_id"] = plan.customer_scope.customer_id
        return [ToolCall(name="behavior_query", params=params)]

    def _build_retirement_tools(self, plan: SemanticPlan, question: str) -> list[ToolCall]:
        q = plan.query_semantics
        if any(token in question for token in ("不存在养老金缺口", "没有养老金缺口", "没有养老资金缺口", "无缺口")):
            return [ToolCall(name="retirement_query", params={"metric": "no_gap", "agg": "list_customer_ids"})]
        if "缺口最大" in question:
            return [ToolCall(name="retirement_query", params={"metric": "gap", "agg": "max_customer_id"})]
        if "总共" in question and ("最低需要积攒" in question or "最低总共需要积攒" in question or "至少要准备" in question):
            return [ToolCall(name="retirement_query", params={"metric": "required_asset", "agg": "sum"})]
        if "总共" in question and ("预计总共可以积攒" in question or "总共能积攒" in question):
            return [ToolCall(name="retirement_query", params={"metric": "accumulated_asset", "agg": "sum"})]

        if q.aggregation in {"sum", "list_customer_ids", "argmax_customer"}:
            params: dict[str, Any] = {
                "metric": q.metric,
                "agg": "max_customer_id" if q.aggregation == "argmax_customer" else q.aggregation,
            }
            return [ToolCall(name="retirement_query", params=params)]

        if plan.customer_scope.type in {"single", "followup"}:
            return [ToolCall(name="calculate_retirement", params=self._customer_param(plan.customer_scope))]

        if q.metric in {"duration", "monthly_spend", "required_asset", "accumulated_asset", "gap"}:
            params = {"metric": q.metric, "agg": q.aggregation}
            params.update(self._customer_param(plan.customer_scope))
            return [ToolCall(name="retirement_query", params=params)]

        return [ToolCall(name="calculate_retirement", params=self._customer_param(plan.customer_scope))]

    def _build_allocation_tools(self, plan: SemanticPlan, question: str) -> list[ToolCall]:
        metric = plan.query_semantics.metric
        if self._is_explicit_product_query(question):
            return [self._build_product_query_tool(plan, question)]
        if metric in {"prediction", "longevity_adjust"}:
            return [ToolCall(name="analyze_behavior_single", params=self._customer_param(plan.customer_scope))]
        if any(token in question for token in ("寿命", "长寿")) and any(token in question for token in ("补哪类产品", "增加什么产品", "增加什么配置")):
            return [ToolCall(name="analyze_behavior_single", params=self._customer_param(plan.customer_scope))]

        if metric in {"shortfall", "lowest_covering_product", "max_projection_product"}:
            return [self._build_product_query_tool(plan, question)]

        if metric in {"feasibility", "adjustment"}:
            if "收益率最低但能够覆盖养老缺口" in question:
                return [self._build_product_query_tool(plan, question, default_mode="lowest_covering_product")]
            if "哪种单一产品攒得最多" in question:
                return [self._build_product_query_tool(plan, question, default_mode="max_projection_product")]
            return [self._build_product_query_tool(plan, question)]

        if metric in {"portfolio_return", "portfolio_risk", "retirement_asset_projection"} or plan.query_semantics.aggregation == "value":
            return [ToolCall(name="build_allocation", params=self._customer_param(plan.customer_scope))]

        if plan.task == "recommend":
            return [ToolCall(name="build_allocation", params=self._customer_param(plan.customer_scope))]

        return [ToolCall(name="build_allocation", params=self._customer_param(plan.customer_scope))]

    def _build_product_query_tool(
        self,
        plan: SemanticPlan,
        question: str,
        default_mode: str | None = None,
    ) -> ToolCall:
        product = self._behavior_product(plan.query_semantics) or self._resolve_product_from_text(question)
        mode = self._resolve_product_mode(plan, question, default_mode)
        params: dict[str, Any] = {"mode": mode}
        params.update(self._customer_param(plan.customer_scope))
        if product and mode not in {"lowest_covering_product", "max_projection_product"}:
            params["product"] = product
        return ToolCall(name="product_query", params=params)

    @staticmethod
    def _resolve_product_mode(plan: SemanticPlan, question: str, default_mode: str | None = None) -> str:
        metric = plan.query_semantics.metric
        if default_mode:
            return default_mode
        if metric == "shortfall" or "还差多少钱" in question:
            return "shortfall"
        if metric == "adjustment" or "如不能" in question or "如何调整" in question:
            return "adjustment"
        if "收益率最低但能够覆盖养老缺口" in question:
            return "lowest_covering_product"
        if "哪种单一产品攒得最多" in question:
            return "max_projection_product"
        return "feasibility"

    @staticmethod
    def _resolve_product_from_text(question: str) -> str | None:
        if "现金理财" in question:
            return "现金理财"
        if "定期存款" in question:
            return "定期存款"
        if "短债" in question:
            return "短债类产品"
        if "固收" in question:
            return "固收+产品"
        if "权益" in question:
            return "权益类产品"
        if "年金" in question:
            return "年金险"
        return None

    @staticmethod
    def _profile_filter_params(q: QuerySemantics) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if q.comparison and isinstance(q.comparison, dict):
            field = q.metric or ""
            compare_field = q.comparison.get("field")
            operator = q.comparison.get("op")
            if field:
                params["field"] = field
            if compare_field:
                params["compare_field"] = compare_field
            if operator:
                params["operator"] = operator
            return params

        if q.filters:
            first = q.filters[0]
            if isinstance(first, FilterCondition) and first.field:
                params["operator"] = first.op
                params["value"] = first.value
        return params

    @staticmethod
    def _behavior_agg(q: QuerySemantics, scope: CustomerScope) -> str:
        if q.metric == "avg_age":
            return "avg_age"
        if q.metric == "customer_count":
            return "customer_count"
        if q.metric == "max_customer_id":
            return "max_customer_id"
        if q.metric == "action_count":
            return "customer_action_count" if scope.customer_id else "total_count"
        return "total_count" if q.aggregation == "value" else q.aggregation

    @staticmethod
    def _behavior_action_type(q: QuerySemantics) -> str:
        for item in q.filters:
            if item.field == "action_type" and item.value is not None:
                return str(item.value)
        return "浏览"

    @staticmethod
    def _behavior_product(q: QuerySemantics) -> str | None:
        for item in q.filters:
            if item.field == "product" and item.value is not None:
                return str(item.value)
        return None

    @staticmethod
    def _behavior_min_count(q: QuerySemantics) -> int:
        for item in q.filters:
            if item.field == "min_count" and item.value is not None:
                try:
                    return int(item.value)
                except (TypeError, ValueError):
                    return 1
        return 1

    @staticmethod
    def _customer_param(scope: CustomerScope) -> dict[str, Any]:
        if scope.customer_id:
            return {"customer_id": scope.customer_id}
        return {}

    @staticmethod
    def _is_profile_count_question(question: str) -> bool:
        return any(token in question for token in ("多少客户", "有几个", "一共有几个", "有多少个"))

    @staticmethod
    def _is_explicit_product_query(question: str) -> bool:
        return (
            any(token in question for token in ("全投", "全买", "只投", "全部投资"))
            and any(token in question for token in ("够不够", "能否达成", "目标够不够", "还差多少钱"))
        ) or "收益率最低但能够覆盖养老缺口" in question or "哪种单一产品攒得最多" in question
