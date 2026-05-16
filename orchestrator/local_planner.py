from __future__ import annotations

import re

from llm.schemas import MemoryUpdate, PlannerOutput, ToolCall
from tools.router import IntentRouter


class LocalPlanner:
    def __init__(self, router: IntentRouter) -> None:
        self.router = router

    def build(self, question: str, session_id: str) -> PlannerOutput:
        route = self.router.route(question, session_id)
        customer_id = route.customer_id
        intent = route.intent
        case_tag = "fallback_unknown"
        answer_mode = "short"
        tool_calls: list[ToolCall] = []

        if "建议书" in question:
            intent = "proposal"
            case_tag = "proposal_full"
            answer_mode = "proposal"
        elif "10年后" in question and "通胀" in question:
            intent = "retirement"
            case_tag = "retirement_scenario_inflation"
            answer_mode = "normal"
        elif "最小化风险波动" in question or "风险最小" in question or "最小风险方案" in question:
            intent = "allocation"
            case_tag = "allocation_min_risk"
            answer_mode = "normal"
        elif "最大化投资收益" in question or "收益最大化" in question:
            intent = "allocation"
            case_tag = "allocation_max_return"
            answer_mode = "normal"
        elif "寿命" in question and "90岁" in question:
            intent = "allocation"
            case_tag = "allocation_longevity_adjust"
            answer_mode = "short"
        elif "未来一个星期" in question and "购买" in question:
            intent = "allocation"
            case_tag = "allocation_prediction"
            answer_mode = "short"
        elif self._is_product_query(question):
            intent = "allocation"
            case_tag = "product_query"
            answer_mode = "normal"
            tool_calls.append(
                ToolCall(
                    name="product_query",
                    params=self._build_product_query_params(question, customer_id),
                )
            )
        elif self._is_behavior_query(question):
            intent = "behavior"
            case_tag = (
                "behavior_single_preference"
                if ("行为最多" in question or "对什么类型的产品行为最多" in question)
                else "behavior_stat"
            )
            answer_mode = "short"
            if case_tag == "behavior_stat":
                tool_calls.append(
                    ToolCall(
                        name="behavior_query",
                        params=self._build_behavior_query_params(question, customer_id),
                    )
                )
        elif self._is_retirement_query(question):
            intent = "retirement"
            case_tag = self._build_retirement_case_tag(question)
            answer_mode = "short"
            if case_tag in {"retirement_gap", "retirement_aggregate", "retirement_ranking"}:
                tool_calls.append(
                    ToolCall(
                        name="retirement_query",
                        params=self._build_retirement_query_params(question, customer_id),
                    )
                )
                answer_mode = "normal" if "如果" in question else "short"
        elif self._is_profile_query(question):
            intent = "profile"
            case_tag = "profile_single_value"
            answer_mode = "short"
            if self._needs_profile_query(question):
                case_tag = (
                    "profile_ranking"
                    if "最高" in question
                    else "profile_aggregate_value"
                )
                tool_calls.append(
                    ToolCall(
                        name="profile_query",
                        params=self._build_profile_query_params(question),
                    )
                )

        if case_tag == "allocation_min_risk" and self._is_allocation_metric_question(question):
            case_tag = "allocation_metric"
            answer_mode = "short"

        return PlannerOutput(
            intent=intent,
            customer_id=customer_id,
            memory_update=MemoryUpdate(
                preferences=route.preferences,
                scenario=route.scenario,
            ),
            tool_calls=tool_calls,
            answer_mode=answer_mode,
            case_tag=case_tag,
        )

    def merge_with_llm_plan(
        self,
        llm_plan: PlannerOutput,
        question: str,
        session_id: str,
    ) -> PlannerOutput:
        local_plan = self.build(question, session_id)

        if llm_plan.intent == "fallback":
            llm_plan.intent = local_plan.intent
        if llm_plan.case_tag == "fallback_unknown":
            llm_plan.case_tag = local_plan.case_tag
        if not llm_plan.customer_id:
            llm_plan.customer_id = local_plan.customer_id
        if not llm_plan.tool_calls:
            llm_plan.tool_calls = local_plan.tool_calls
        elif local_plan.tool_calls and local_plan.case_tag in {
            "profile_aggregate_value",
            "profile_ranking",
            "behavior_stat",
            "retirement_gap",
            "retirement_aggregate",
            "retirement_ranking",
            "product_query",
        }:
            llm_plan.tool_calls = local_plan.tool_calls
            llm_plan.case_tag = local_plan.case_tag
            llm_plan.intent = local_plan.intent
        if llm_plan.answer_mode == "short" and local_plan.answer_mode != "short":
            llm_plan.answer_mode = local_plan.answer_mode

        if not llm_plan.memory_update.preferences and local_plan.memory_update.preferences:
            llm_plan.memory_update.preferences = local_plan.memory_update.preferences
        if not llm_plan.memory_update.scenario and local_plan.memory_update.scenario:
            llm_plan.memory_update.scenario = local_plan.memory_update.scenario

        return llm_plan

    @staticmethod
    def _extract_money_amount(question: str) -> int | None:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\s*元", question)
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

    @staticmethod
    def _is_product_query(question: str) -> bool:
        return (
            ("全投" in question or "全买" in question or "只投" in question or "全部投资" in question)
            and any(token in question for token in ("够不够", "能否达成", "目标够不够", "还差多少钱"))
        ) or "收益率最低但能够覆盖养老缺口" in question or "哪种单一产品攒得最多" in question

    @staticmethod
    def _is_behavior_query(question: str) -> bool:
        return any(
            token in question
            for token in (
                "浏览",
                "购买",
                "买过",
                "收藏",
                "行为",
                "看权益",
                "浏览详情",
            )
        )

    @staticmethod
    def _is_profile_query(question: str) -> bool:
        return any(
            token in question
            for token in (
                "年龄",
                "月收入",
                "收入",
                "净资产",
                "风险",
                "养老金",
                "企业年金",
                "结余",
                "月支出",
                "中位数",
                "最高",
            )
        )

    @staticmethod
    def _needs_profile_query(question: str) -> bool:
        return any(
            token in question
            for token in ("多少客户", "客户数", "平均", "中位数", "最高", "不超过", "大于", "及以上", "以下", "有几个", "至少")
        )

    @staticmethod
    def _is_retirement_query(question: str) -> bool:
        return any(
            token in question
            for token in (
                "退休",
                "缺口",
                "积攒",
                "攒",
                "养老金",
                "距离",
                "离退休",
                "默认情景",
            )
        )

    @staticmethod
    def _is_allocation_metric_question(question: str) -> bool:
        return any(
            token in question
            for token in ("预期年化收益率", "风险分数", "预计可积攒多少钱")
        )

    def _build_profile_query_params(self, question: str) -> dict[str, object]:
        if "中位数" in question and "年龄" in question:
            return {"field": "age", "agg": "median"}
        if "最高" in question and ("月收入" in question or "收入" in question):
            return {"field": "monthly_income", "agg": "argmax_customer"}
        if "平均" in question:
            if "净资产" in question:
                return {"field": "net_asset", "agg": "avg"}
            if "结余" in question or "能攒" in question:
                return {"field": "monthly_saving", "agg": "avg"}
            if "月支出" in question or "支出" in question:
                return {"field": "monthly_expend", "agg": "avg"}
            if "收入" in question:
                return {"field": "monthly_income", "agg": "avg"}
            return {"field": "age", "agg": "avg"}

        amount = self._extract_money_amount(question)
        if "净资产" in question and amount is not None:
            return {"field": "net_asset", "agg": "count", "operator": ">=", "value": amount}
        if "企业年金" in question and "大于0" in question:
            return {"field": "enterprise_ann", "agg": "count", "operator": ">", "value": 0}
        if "结余" in question and amount is not None:
            return {"field": "monthly_saving", "agg": "count", "operator": ">=", "value": amount}
        if "风险" in question:
            risk_match = re.search(r"R\s*([1-5])", question, re.IGNORECASE)
            if risk_match:
                return {
                    "field": "risk_level",
                    "agg": "count",
                    "operator": ">=",
                    "value": f"R{risk_match.group(1)}",
                }
        if "养老金高于当前月支出" in question:
            return {
                "field": "pension",
                "agg": "count",
                "operator": ">",
                "compare_field": "monthly_expend",
            }
        if "月支出" in question and "不超过" in question and amount is not None:
            return {"field": "monthly_expend", "agg": "count", "operator": "<=", "value": amount}
        if "年龄" in question:
            age_ge = re.search(r"年龄[^0-9]*(\d+)\s*岁及以上", question)
            if age_ge:
                return {"field": "age", "agg": "count", "operator": ">=", "value": int(age_ge.group(1))}
            age_lt = re.search(r"年龄[^0-9]*(\d+)\s*岁以下", question)
            if age_lt:
                return {"field": "age", "agg": "count", "operator": "<", "value": int(age_lt.group(1))}
        return {"field": "age", "agg": "count"}

    def _build_behavior_query_params(
        self, question: str, customer_id: str | None
    ) -> dict[str, object]:
        product = self._resolve_product(question)
        if "收藏" in question:
            action_type = "收藏"
        elif "购买" in question or "买过" in question or "买" in question:
            action_type = "购买"
        elif "浏览详情" in question:
            action_type = "浏览详情"
        elif "浏览持仓" in question:
            action_type = "浏览持仓"
        else:
            action_type = "浏览"

        min_count_match = re.search(r"(\d+)\s*次及以上", question)
        min_count = int(min_count_match.group(1)) if min_count_match else 1

        if "谁的" in question:
            agg = "max_customer_id"
        elif customer_id and ("多少次" in question or "几次" in question or "发生过" in question):
            agg = "customer_action_count"
        elif "平均年龄" in question or "平均年龄是多大" in question or "平均年龄多大" in question:
            agg = "avg_age"
        elif "多少客户" in question or "有多少个" in question:
            agg = "customer_count"
        else:
            agg = "total_count"

        return {
            "agg": agg,
            "action_type": action_type,
            "product": product,
            "customer_id": customer_id,
            "min_count": min_count,
        }

    @staticmethod
    def _build_retirement_case_tag(question: str) -> str:
        if "谁的" in question or "哪些客户" in question or "哪几位客户" in question or "总共" in question:
            if "缺口最大" in question:
                return "retirement_ranking"
            return "retirement_aggregate"
        if "缺口" in question:
            return "retirement_gap"
        if "距离退休" in question or "离退休" in question or "退休还有多久" in question:
            return "retirement_duration"
        if "每月需要支出" in question or "退休时支出" in question or "第一个月大概要花" in question or "刚退休时每月预计要花" in question:
            return "retirement_monthly_spend"
        if "最低需要积攒" in question or "最低需要攒" in question:
            return "retirement_required_asset"
        return "retirement_accumulated_asset"

    def _build_retirement_query_params(
        self, question: str, customer_id: str | None
    ) -> dict[str, object]:
        if "哪些客户" in question or "哪几位客户" in question:
            return {"metric": "no_gap", "agg": "list_customer_ids"}
        if "缺口最大" in question:
            return {"metric": "gap", "agg": "max_customer_id"}
        if "总共" in question and ("最低需要积攒" in question or "至少要准备" in question):
            return {"metric": "required_asset", "agg": "sum"}
        if "总共" in question and ("预计总共可以积攒" in question or "总共能积攒" in question):
            return {"metric": "accumulated_asset", "agg": "sum"}
        if "缺口" in question:
            return {"metric": "gap", "agg": "value", "customer_id": customer_id}
        if "第一个月大概要花" in question or "刚退休时每月预计要花" in question:
            return {"metric": "monthly_spend", "agg": "value", "customer_id": customer_id}
        if "距离退休" in question or "离退休" in question or "退休还有多久" in question:
            return {"metric": "duration", "agg": "value", "customer_id": customer_id}
        if "最低需要积攒" in question or "最低需要攒" in question:
            return {"metric": "required_asset", "agg": "value", "customer_id": customer_id}
        return {"metric": "accumulated_asset", "agg": "value", "customer_id": customer_id}

    def _build_product_query_params(
        self, question: str, customer_id: str | None
    ) -> dict[str, object]:
        product = self._resolve_product(question)
        if "如不能" in question or "如何调整" in question:
            mode = "adjustment"
        elif "收益率最低但能够覆盖养老缺口" in question:
            mode = "lowest_covering_product"
        elif "哪种单一产品攒得最多" in question:
            mode = "max_projection_product"
        elif "还差多少钱" in question:
            mode = "shortfall"
        else:
            mode = "feasibility"
        return {"customer_id": customer_id, "product": product, "mode": mode}
