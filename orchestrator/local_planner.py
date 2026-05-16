from __future__ import annotations

import re

from llm.schemas import (
    CustomerScope,
    FilterCondition,
    MemoryUpdate,
    PlannerOutput,
    QuerySemantics,
    SemanticPlan,
)
from orchestrator.plan_compiler import PlanCompiler
from tools.router import IntentRouter


class LocalPlanner:
    """Minimal semantic fallback when the LLM planner fails."""

    def __init__(self, router: IntentRouter) -> None:
        self.router = router
        self.compiler = PlanCompiler()

    def build_semantic(self, question: str, session_id: str) -> SemanticPlan:
        route = self.router.route(question, session_id)
        task, domain, query_semantics, response_style = self._infer_semantic_shape(question, route.customer_id)

        return SemanticPlan(
            task=task,
            domain=domain,
            customer_scope=CustomerScope(
                type=self._infer_scope(question, route.customer_id),
                customer_id=route.customer_id,
            ),
            query_semantics=query_semantics,
            memory_update=MemoryUpdate(
                preferences=route.preferences,
                scenario=route.scenario,
            ),
            response_style=response_style,
            raw_notes=question,
        )

    # Backward-compatible alias used by older call sites.
    def build(self, question: str, session_id: str) -> PlannerOutput:
        semantic = self.build_semantic(question, session_id)
        return self.compiler.compile(semantic, question)

    def merge_with_llm_plan(
        self,
        llm_plan: PlannerOutput,
        question: str,
        session_id: str,
    ) -> PlannerOutput:
        # Compatibility shim: keep the old method name, but let the local
        # semantic fallback win without merging rule-derived fields back in.
        semantic = self.build_semantic(question, session_id)
        return self.compiler.compile(semantic, question)

    @staticmethod
    def _infer_scope(question: str, customer_id: str | None) -> str:
        if customer_id and any(token in question for token in ("他", "她", "该客户", "这位客户", "那他", "那她")):
            return "followup"
        if any(token in question for token in ("这3位客户", "所有客户", "样本里", "样本客户里", "我有多少客户", "哪几位客户")):
            return "cohort"
        return "single" if customer_id else "cohort"

    def _infer_semantic_shape(
        self,
        question: str,
        customer_id: str | None,
    ) -> tuple[str, str, QuerySemantics, str]:
        if "建议书" in question:
            return "proposal", "proposal", QuerySemantics(metric="proposal", aggregation="value"), "proposal"

        if "10年后" in question and "通胀" in question:
            return "query", "retirement", self._retirement_semantics(question, customer_id), "normal"

        if any(token in question for token in ("最小化风险波动", "最小风险方案", "尽量稳一点")):
            if "预期年化收益率" in question:
                return "query", "allocation", QuerySemantics(metric="portfolio_return", aggregation="value"), "short"
            if "风险分数" in question:
                return "query", "allocation", QuerySemantics(metric="portfolio_risk", aggregation="value"), "short"
            if "预计可积攒多少钱" in question or "退休时预计可积攒" in question:
                return "query", "allocation", QuerySemantics(metric="retirement_asset_projection", aggregation="value"), "short"
            return "recommend", "allocation", QuerySemantics(metric="allocation_plan", aggregation="value"), "normal"

        if "最大化投资收益" in question or "收益最大化" in question:
            if "预期年化收益率" in question:
                return "query", "allocation", QuerySemantics(metric="portfolio_return", aggregation="value"), "short"
            if "风险分数" in question:
                return "query", "allocation", QuerySemantics(metric="portfolio_risk", aggregation="value"), "short"
            if "预计可积攒多少钱" in question or "退休时预计可积攒" in question:
                return "query", "allocation", QuerySemantics(metric="retirement_asset_projection", aggregation="value"), "short"
            return "recommend", "allocation", QuerySemantics(metric="allocation_plan", aggregation="value"), "normal"

        if "寿命" in question or "长寿" in question:
            return "recommend", "allocation", QuerySemantics(metric="longevity_adjust", aggregation="value"), "short"

        if "未来一个星期" in question and "购买" in question:
            return "recommend", "allocation", QuerySemantics(metric="prediction", aggregation="value"), "short"

        if self._is_product_query(question):
            return "query", "allocation", QuerySemantics(
                metric=self._product_metric(question),
                aggregation="value",
                filters=self._product_filters(question, customer_id),
            ), "normal"

        if self._is_behavior_query(question):
            return "query", "behavior", self._behavior_semantics(question, customer_id), "short"

        if self._is_retirement_query(question):
            return "query", "retirement", self._retirement_semantics(question, customer_id), "short"

        if self._is_profile_query(question):
            return "query", "profile", self._profile_semantics(question, customer_id), "short"

        return "fallback", "fallback", QuerySemantics(metric="", aggregation="value"), "short"

    @staticmethod
    def _extract_money_amount(question: str) -> int | None:
        match = re.search(r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+)?)\s*(万)?\s*元", question)
        if not match:
            return None
        value = float(match.group(1))
        if match.group(2):
            value *= 10000
        return int(round(value))

    @staticmethod
    def _resolve_product(question: str) -> str | None:
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

    def _profile_semantics(self, question: str, customer_id: str | None) -> QuerySemantics:
        if "中位数" in question and "年龄" in question:
            return QuerySemantics(metric="age", aggregation="median")
        if "最高" in question and ("月收入" in question or "收入" in question):
            return QuerySemantics(metric="monthly_income", aggregation="argmax_customer")
        if "平均" in question:
            if "净资产" in question:
                return QuerySemantics(metric="net_asset", aggregation="avg")
            if "结余" in question or "能攒" in question or "攒钱" in question:
                return QuerySemantics(metric="monthly_saving", aggregation="avg")
            if "月支出" in question or "支出" in question:
                return QuerySemantics(metric="monthly_expend", aggregation="avg")
            if "收入" in question:
                return QuerySemantics(metric="monthly_income", aggregation="avg")
            if "收藏" in question:
                return QuerySemantics(metric="age", aggregation="avg")
            return QuerySemantics(metric="age", aggregation="avg")

        amount = self._extract_money_amount(question)
        if "净资产" in question and amount is not None:
            return QuerySemantics(
                metric="net_asset",
                aggregation="count",
                filters=[FilterCondition("net_asset", ">=", amount)],
            )
        if "企业年金" in question and "大于0" in question:
            return QuerySemantics(
                metric="enterprise_ann",
                aggregation="count",
                filters=[FilterCondition("enterprise_ann", ">", 0)],
            )
        if "结余" in question and amount is not None:
            return QuerySemantics(
                metric="monthly_saving",
                aggregation="count",
                filters=[FilterCondition("monthly_saving", ">=", amount)],
            )
        if "养老金高于当前月支出" in question:
            return QuerySemantics(
                metric="pension",
                aggregation="count",
                comparison={"field": "monthly_expend", "op": ">"},
            )
        if "月支出" in question and "不超过" in question and amount is not None:
            return QuerySemantics(
                metric="monthly_expend",
                aggregation="count",
                filters=[FilterCondition("monthly_expend", "<=", amount)],
            )
        if "年龄" in question:
            age_ge = re.search(r"年龄[^0-9]*(\d+)\s*岁及以上", question)
            if age_ge:
                return QuerySemantics(
                    metric="age",
                    aggregation="count",
                    filters=[FilterCondition("age", ">=", int(age_ge.group(1)))],
                )
            age_lt = re.search(r"年龄[^0-9]*(\d+)\s*岁以下", question)
            if age_lt:
                return QuerySemantics(
                    metric="age",
                    aggregation="count",
                    filters=[FilterCondition("age", "<", int(age_lt.group(1)))],
                )
        if customer_id:
            if any(token in question for token in ("退休金", "养老金")):
                return QuerySemantics(metric="pension", aggregation="value")
            if "企业年金" in question:
                return QuerySemantics(metric="enterprise_ann", aggregation="value")
            if "净资产" in question:
                return QuerySemantics(metric="net_asset", aggregation="value")
            if "结余" in question or "能攒" in question or "攒钱" in question:
                return QuerySemantics(metric="monthly_saving", aggregation="value")
            if "月支出" in question or ("支出" in question and "退休" not in question):
                return QuerySemantics(metric="monthly_expend", aggregation="value")
            if "月收入" in question or ("收入" in question and "收益" not in question):
                return QuerySemantics(metric="monthly_income", aggregation="value")
            if "风险" in question:
                return QuerySemantics(metric="risk_level", aggregation="value")
            if any(token in question for token in ("年龄", "几岁", "多大")):
                return QuerySemantics(metric="age", aggregation="value")
        return QuerySemantics(metric="age", aggregation="count")

    def _behavior_semantics(self, question: str, customer_id: str | None) -> QuerySemantics:
        if "行为最多" in question or "对什么类型的产品行为最多" in question:
            return QuerySemantics(metric="top_product", aggregation="value")

        action_type = self._behavior_action_type(question)
        product = self._resolve_product(question)
        min_count = self._behavior_min_count(question)

        if customer_id and ("多少次" in question or "几次" in question):
            return QuerySemantics(
                metric="action_count",
                aggregation="value",
                filters=[
                    FilterCondition("action_type", "=", action_type),
                    FilterCondition("product", "=", product) if product else FilterCondition("product", "=", None),
                    FilterCondition("min_count", ">=", min_count),
                ],
            )

        if "平均年龄" in question:
            return QuerySemantics(
                metric="avg_age",
                aggregation="avg",
                filters=[
                    FilterCondition("action_type", "=", action_type),
                    FilterCondition("product", "=", product) if product else FilterCondition("product", "=", None),
                    FilterCondition("min_count", ">=", min_count),
                ],
            )

        if "多少客户" in question or "有多少个" in question:
            return QuerySemantics(
                metric="customer_count",
                aggregation="count",
                filters=[
                    FilterCondition("action_type", "=", action_type),
                    FilterCondition("product", "=", product) if product else FilterCondition("product", "=", None),
                    FilterCondition("min_count", ">=", min_count),
                ],
            )

        if "谁的" in question:
            return QuerySemantics(
                metric="max_customer_id",
                aggregation="argmax_customer",
                filters=[FilterCondition("action_type", "=", action_type)],
            )

        return QuerySemantics(
            metric="action_count",
            aggregation="value",
            filters=[FilterCondition("action_type", "=", action_type)],
        )

    def _retirement_semantics(self, question: str, customer_id: str | None) -> QuerySemantics:
        if any(token in question for token in ("不存在养老金缺口", "没有养老金缺口", "没有养老资金缺口", "无缺口")):
            return QuerySemantics(metric="no_gap", aggregation="list_customer_ids")
        if "哪些客户" in question or "哪几位客户" in question or "有哪些" in question:
            return QuerySemantics(metric="gap", aggregation="list_customer_ids")
        if "缺口最大" in question:
            return QuerySemantics(metric="gap", aggregation="argmax_customer")
        if "总共" in question and ("最低需要积攒" in question or "最低总共需要积攒" in question or "至少要准备" in question):
            return QuerySemantics(metric="required_asset", aggregation="sum")
        if "总共" in question and ("预计总共可以积攒" in question or "总共能积攒" in question):
            return QuerySemantics(metric="accumulated_asset", aggregation="sum")
        if "缺口" in question:
            return QuerySemantics(metric="gap", aggregation="value")
        if "第一个月大概要花" in question or "刚退休时每月预计要花" in question or "退休当月大概要花" in question:
            return QuerySemantics(metric="monthly_spend", aggregation="value")
        if "距离退休" in question or "离退休" in question or "退休还有多久" in question:
            return QuerySemantics(metric="duration", aggregation="value")
        if "最低需要积攒" in question or "最低需要攒" in question:
            return QuerySemantics(metric="required_asset", aggregation="value")
        if "可以积攒下多少钱" in question or "能攒多少" in question or "可以积攒" in question:
            return QuerySemantics(metric="accumulated_asset", aggregation="value")
        return QuerySemantics(metric="accumulated_asset", aggregation="value")

    def _product_metric(self, question: str) -> str:
        if "如不能" in question or "如何调整" in question:
            return "adjustment"
        if "收益率最低但能够覆盖养老缺口" in question:
            return "lowest_covering_product"
        if "哪种单一产品攒得最多" in question:
            return "max_projection_product"
        if "还差多少钱" in question:
            return "shortfall"
        return "feasibility"

    def _product_filters(self, question: str, customer_id: str | None) -> list[FilterCondition]:
        product = self._resolve_product(question)
        filters = [FilterCondition("product", "=", product)] if product else []
        if customer_id:
            filters.append(FilterCondition("customer_id", "=", customer_id))
        return filters

    def _behavior_action_type(self, question: str) -> str:
        if "收藏" in question:
            return "收藏"
        if "购买" in question or "买过" in question or "买" in question:
            return "购买"
        if "浏览详情" in question:
            return "浏览详情"
        if "浏览持仓" in question:
            return "浏览持仓"
        return "浏览"

    @staticmethod
    def _behavior_min_count(question: str) -> int:
        match = re.search(r"(\d+)\s*次及以上", question)
        return int(match.group(1)) if match else 1

    @staticmethod
    def _is_product_query(question: str) -> bool:
        return (
            ("全投" in question or "全买" in question or "只投" in question or "全部投资" in question)
            and any(token in question for token in ("够不够", "能否达成", "目标够不够", "还差多少钱", "呢"))
        ) or "收益率最低但能够覆盖养老缺口" in question or "哪种单一产品攒得最多" in question

    @staticmethod
    def _is_behavior_query(question: str) -> bool:
        return any(token in question for token in ("浏览", "购买", "买过", "收藏", "行为", "看权益", "浏览详情"))

    @staticmethod
    def _is_profile_query(question: str) -> bool:
        return any(
            token in question
            for token in (
                "年龄",
                "几岁",
                "多大",
                "月收入",
                "收入",
                "净资产",
                "风险",
                "养老金",
                "企业年金",
                "退休金",
                "结余",
                "能攒",
                "攒钱",
                "月支出",
                "中位数",
                "最高",
            )
        )

    @staticmethod
    def _is_retirement_query(question: str) -> bool:
        if any(token in question for token in ("能攒", "攒钱")) and "退休" not in question:
            return False
        if any(token in question for token in ("退休金", "养老金", "企业年金")) and not any(
            token in question
            for token in ("缺口", "积攒", "攒", "距离退休", "离退休", "退休还有多久", "退休后", "退休时", "退休当月")
        ):
            return False
        return any(
            token in question
            for token in (
                "退休",
                "缺口",
                "积攒",
                "攒",
                "距离",
                "离退休",
                "默认情景",
            )
        )
