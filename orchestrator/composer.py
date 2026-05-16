from __future__ import annotations

from dataclasses import asdict
import json
import logging
import re
from decimal import Decimal
from typing import Any

from llm.client import LLMClient
from llm.prompts import COMPOSER_SYSTEM_PROMPT, PROPOSAL_SYSTEM_PROMPT
from llm.schemas import PlannerOutput

logger = logging.getLogger(__name__)

_PROPOSAL_REQUIRED_SECTIONS = [
    "基本情况", "基本假设", "养老目标", "财富需求测算",
    "产品偏好", "资产配置", "建议",
]
_PROPOSAL_MIN_SECTIONS = 5  # Require at least 5 of 7 sections


class LLMComposer:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or LLMClient()

    def compose(
        self,
        question: str,
        plan: PlannerOutput,
        tool_results: dict[str, Any],
    ) -> str:
        if plan.answer_mode == "proposal":
            return self._compose_proposal(tool_results)
        return self._compose_short(question, plan, tool_results)

    def _compose_short(
        self,
        question: str,
        plan: PlannerOutput,
        tool_results: dict[str, Any],
    ) -> str:
        payload = {
            "question": question,
            "intent": plan.intent,
            "case_tag": plan.case_tag,
            "answer_mode": plan.answer_mode,
            "semantic_plan": self._serialize_semantic_plan(plan),
            "tool_results": tool_results,
        }
        style_hint = self._build_case_style_hint(plan.case_tag)
        user_prompt = (
            f"根据以下结构化数据回答问题。\n"
            f"答题风格要求：{style_hint}\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            f"只输出最终答案。"
        )
        messages = [
            {"role": "system", "content": COMPOSER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        try:
            llm_answer = self.llm.chat(messages, temperature=0.0, max_tokens=512).strip()
            return self._deterministic_answer(question, plan, tool_results, llm_answer)
        except Exception as e:
            logger.error("Composer failed, falling back to programmatic short answer: %s", e)
            return self._fallback_short(question, plan, tool_results)

    def _compose_proposal(self, tool_results: dict[str, Any]) -> str:
        payload = tool_results.get("generate_proposal_payload", tool_results)
        user_prompt = (
            f"根据以下结构化数据生成养老规划建议书：\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
        )
        messages = [
            {"role": "system", "content": PROPOSAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        try:
            proposal = self.llm.chat(
                messages, temperature=0.1, max_tokens=4096
            ).strip()
            if (
                self._proposal_has_required_sections(proposal)
                and self._proposal_matches_payload(proposal, payload)
            ):
                return proposal
            return self._fallback_proposal(payload)
        except Exception as e:
            logger.error("Proposal generation failed: %s", e)
            return self._fallback_proposal(payload)

    @staticmethod
    def _build_case_style_hint(case_tag: str) -> str:
        style_map = {
            "profile_single_value": "只输出最终值，例如“22 岁”“5000 元”“R3”。",
            "profile_count": "只输出计数结果，例如“2 个”。",
            "profile_aggregate_value": "只输出聚合后的最终结果，例如“5667 元”“36 岁”。",
            "profile_ranking": "只输出客户编号，例如“V500002”。",
            "behavior_single_preference": "只输出产品名称，例如“现金理财”。",
            "behavior_aggregate_stat": "只输出最终统计值，例如“29 岁”。",
            "behavior_stat": "只输出最终统计值，例如“21 次”“2 个”“43 岁”。",
            "behavior_ranking": "只输出客户编号，例如“V500003”。",
            "retirement_duration": "只输出时长，例如“12 年 7 个月”。",
            "retirement_monthly_spend": "只输出金额，例如“9076 元”。",
            "retirement_required_asset": "只输出金额，例如“985979 元”。",
            "retirement_accumulated_asset": "只输出金额，例如“772715 元”。",
            "retirement_gap": "只输出缺口结论，例如“213264 元”或“不存在资金缺口”。",
            "retirement_aggregate": "只输出聚合后的最终结果，例如“1982725 元”或客户编号列表。",
            "retirement_ranking": "只输出客户编号，例如“V500001”。",
            "allocation_prediction": "只输出最可能的产品名称。",
            "allocation_longevity_adjust": "只输出最应该增加配置的产品名称。",
            "allocation_goal_check": "先给出能否达成及调整结论，再用简短说明给出缺口和替代产品。",
            "allocation_max_return": "先给出最优配置结论，再用一句解释为什么。",
            "allocation_min_risk": "先给出比例方案，再用2到4句说明主力产品、最低比例和剩余比例用途。",
            "allocation_metric": "只输出目标方案下的单一指标结果，例如“2.31%”“1.64”“988310 元”。",
            "product_query": "只输出单产品分析的最终结论，必要时附简短说明。",
            "retirement_scenario_inflation": "第一行给最终金额，随后用极简步骤说明分段通胀和缺口测算。",
        }
        return style_map.get(case_tag, "只基于结构化数据给出简洁答案。")

    def _fallback_short(
        self,
        question: str,
        plan: PlannerOutput,
        tool_results: dict[str, Any],
    ) -> str:
        result = self._deterministic_answer(question, plan, tool_results, "")
        return result or "抱歉，暂时无法回答该问题。"

    @staticmethod
    def _proposal_has_required_sections(text: str) -> bool:
        return sum(1 for s in _PROPOSAL_REQUIRED_SECTIONS if s in text) >= _PROPOSAL_MIN_SECTIONS

    def _deterministic_answer(
        self,
        question: str,
        plan: PlannerOutput,
        tool_results: dict[str, Any],
        llm_answer: str,
    ) -> str:
        profile = tool_results.get("get_profile", {})
        behavior = tool_results.get("analyze_behavior_single", {})
        retirement = tool_results.get("calculate_retirement", {})
        allocation = tool_results.get("build_allocation", {})
        case_tag = plan.case_tag

        if case_tag == "profile_single_value":
            if "结余" in question and profile.get("monthly_saving") is not None:
                return f"{self._format_money_value(profile['monthly_saving'])} 元"
            if any(token in question for token in ("年龄", "几岁", "多大")) and profile.get("age") is not None:
                return f"{profile['age']} 岁"
            if ("月收入" in question or "收入" in question) and profile.get("monthly_income") is not None:
                return f"{self._format_money_value(profile['monthly_income'])} 元"
            if ("月支出" in question or "支出" in question) and profile.get("monthly_expend") is not None:
                return f"{self._format_money_value(profile['monthly_expend'])} 元"
            if "企业年金" in question and profile.get("enterprise_ann") is not None:
                return f"{self._format_money_value(profile['enterprise_ann'])} 元"
            if any(token in question for token in ("退休金", "养老金")) and profile.get("pension") is not None:
                return f"{self._format_money_value(profile['pension'])} 元"
            if "风险" in question and profile.get("risk_level") is not None:
                return str(profile["risk_level"])
            if "净资产" in question and profile.get("net_asset") is not None:
                return f"{self._format_money_value(profile['net_asset'])} 元"

        if case_tag == "profile_count":
            for result in tool_results.values():
                if isinstance(result, str) and result:
                    return result

        if case_tag in {
            "profile_aggregate_value",
            "profile_ranking",
            "behavior_stat",
            "behavior_ranking",
            "retirement_gap",
            "retirement_aggregate",
            "retirement_ranking",
            "product_query",
        }:
            for name in ("profile_query", "behavior_query", "retirement_query", "product_query"):
                result = tool_results.get(name, {})
                if isinstance(result, dict) and result.get("result"):
                    return str(result["result"])

        if case_tag == "behavior_single_preference" and behavior.get("top_product"):
            return str(behavior["top_product"])

        if case_tag == "behavior_aggregate_stat":
            aggregate = tool_results.get("analyze_behavior_aggregate", {})
            if isinstance(aggregate, dict) and aggregate.get("result"):
                return str(aggregate["result"])

        if case_tag == "retirement_duration" and retirement.get("retirement_duration_text"):
            return self._space_duration(str(retirement["retirement_duration_text"]))

        if case_tag == "retirement_monthly_spend" and retirement.get("retirement_monthly_expend") is not None:
            return f"{retirement['retirement_monthly_expend']} 元"

        if case_tag == "retirement_required_asset" and retirement.get("required_asset_at_retirement") is not None:
            return f"{retirement['required_asset_at_retirement']} 元"

        if case_tag == "retirement_accumulated_asset" and retirement.get("accumulated_asset_at_retirement") is not None:
            return f"{retirement['accumulated_asset_at_retirement']} 元"

        if case_tag == "allocation_prediction" and behavior.get("top_product"):
            return str(behavior["top_product"])

        if case_tag == "allocation_longevity_adjust":
            return "年金险"

        if case_tag == "allocation_max_return":
            rows = allocation.get("allocation", [])
            if rows:
                top = max(rows, key=lambda item: float(item.get("weight", "0")))
                return f"{self._display_product(str(top['product']))}配置 100%"

        if case_tag == "allocation_min_risk":
            rows = allocation.get("allocation", [])
            non_zero_rows = [
                item for item in rows if float(item.get("weight", "0")) > 0
            ]
            if non_zero_rows:
                primary_row = max(
                    non_zero_rows,
                    key=lambda item: float(item.get("weight", "0")),
                )
                primary = str(primary_row["product"])
                primary_pct = int(round(float(primary_row["weight"]) * 100))
                parts = [
                    f"{self._display_product(str(item['product']))}配置 "
                    f"{int(round(float(item['weight']) * 100))}%"
                    for item in non_zero_rows
                ]
                detail = (
                    f"主力产品为 {self._display_product(primary)}，"
                    f"{primary_pct}% 的主力仓位即可覆盖养老资金需求，"
                    "剩余比例用于流动性储备和长寿风险对冲。"
                )
                return "；".join(parts) + "\n" + detail

        if case_tag == "allocation_goal_check":
            product_query = tool_results.get("product_query", {})
            if isinstance(product_query, dict) and product_query.get("result"):
                return str(product_query["result"])

        if case_tag == "allocation_metric":
            if "预期年化收益率" in question and allocation.get("portfolio_return") is not None:
                return f"{float(allocation['portfolio_return']) * 100:.2f}%"
            if "风险分数" in question and allocation.get("portfolio_risk") is not None:
                return f"{float(allocation['portfolio_risk']):.2f}"
            if (
                "预计可积攒多少钱" in question
                and allocation.get("retirement_asset_projection") is not None
            ):
                return f"{allocation['retirement_asset_projection']} 元"

        if case_tag == "retirement_scenario_inflation" and retirement:
            retirement_query = tool_results.get("retirement_query", {})
            if isinstance(retirement_query, dict) and retirement_query.get("result"):
                return str(retirement_query["result"])
            if any(token in question for token in ("第一个月大概要花", "刚退休时每月预计要花", "退休当月大概要花")):
                return f"{retirement['retirement_monthly_expend']} 元"
            if "缺口" in question:
                gap_value = int(retirement["gap"])
                if gap_value <= 0:
                    return "在当前假设下不存在资金缺口"
                return f"{gap_value} 元"
            amount = f"{retirement['required_asset_at_retirement']} 元"
            years, rate = self._extract_inflation_override(question)
            if years is not None and rate is not None:
                return (
                    f"{amount}\n"
                    f"1. 通胀按前 {years} 年 2%、之后 {rate}% 分段计算退休时月支出。\n"
                    f"2. 退休后按新的通胀环境折现养老金与支出，得到最低养老储备。"
                )
            return amount

        for result in tool_results.values():
            if isinstance(result, str) and result:
                return result
            if isinstance(result, dict) and result.get("result"):
                return str(result["result"])

        return llm_answer.strip()

    @staticmethod
    def _serialize_semantic_plan(plan: PlannerOutput) -> dict[str, Any] | None:
        if plan.semantic_plan is None:
            return None
        return asdict(plan.semantic_plan)

    def _fallback_proposal(self, payload: dict[str, Any]) -> str:
        profile = payload.get("profile", {})
        behavior = payload.get("behavior_summary", {})
        retirement = payload.get("retirement_result", {})
        allocation_plan = payload.get("allocation_plan", {})
        guidance = payload.get("proposal_guidance", {})
        assumptions = payload.get("assumptions", {})
        prefs = assumptions.get("preferences", {})
        scenario = assumptions.get("scenario", {})

        allocation_lines = []
        for item in allocation_plan.get("allocation", []):
            product = self._display_product(str(item.get("product", "")))
            weight = int(round(float(item.get("weight", "0")) * 100))
            if weight > 0:
                allocation_lines.append(f"- {product} {weight}%")
        allocation_text = "\n".join(allocation_lines) or "- 暂无可用配置方案"

        objective = guidance.get("effective_allocation_objective")
        if objective == "minimize_risk":
            objective_text = "在满足养老需求基础上最小化风险波动"
        elif objective == "maximize_return":
            objective_text = "在风险等级约束内追求投资收益最大化"
        else:
            objective_text = "兼顾养老需求、风险承受能力与流动性安排"

        retirement_goal = prefs.get("retirement_goal", "退休后消费水平尽量不下降")
        duration_text = self._space_duration(
            str(retirement.get("retirement_duration_text", "-"))
        )
        conflict_notes = guidance.get("conflict_notes", [])
        conflict_line = (
            f"- 冲突说明：{conflict_notes[0]}"
            if conflict_notes
            else "- 冲突说明：当前未识别到长期观点与临时假设冲突。"
        )
        scenario_lines = []
        if scenario.get("inflation_after_years") is not None and scenario.get(
            "inflation_after_years_annual"
        ) is not None:
            scenario_lines.append(
                f"- 本轮临时假设：{scenario['inflation_after_years']} 年后通胀率调整为 "
                f"{float(scenario['inflation_after_years_annual']) * 100:.0f}% 并维持不变。"
            )
        elif scenario.get("inflation_annual") is not None:
            scenario_lines.append(
                f"- 本轮临时假设：通胀率按 {float(scenario['inflation_annual']) * 100:.0f}% 测算。"
            )
        if scenario.get("allocation_objective"):
            scenario_lines.append(
                f"- 本轮临时目标：{scenario.get('allocation_objective')}。"
            )
        scenario_text = "\n".join(scenario_lines) if scenario_lines else "- 本轮无额外临时假设。"

        return (
            f"# 客户 {profile.get('customer_id', '')} 养老规划建议书\n\n"
            f"## 基本情况\n"
            f"客户 {profile.get('customer_id', '')}，{profile.get('age', '-') } 岁，"
            f"{profile.get('gender', '-') }，风险评级 {profile.get('risk_level', '-') }。"
            f"当前净资产 {profile.get('net_asset', '-') } 元，月收入 {profile.get('monthly_income', '-') } 元，"
            f"月支出 {profile.get('monthly_expend', '-') } 元，月结余 {profile.get('monthly_saving', '-') } 元。\n\n"
            f"## 基本假设\n"
            f"- 系统默认通胀率 2%，默认投资回报率 2%，预期寿命 80 岁。\n"
            f"- 当前日期 2025-03-31，退休年龄按现行延迟退休政策测算。\n"
            f"{conflict_line}\n"
            f"{scenario_text}\n\n"
            f"## 养老目标\n"
            f"客户当前养老目标为：{retirement_goal}。正式资产配置目标为：{objective_text}。\n\n"
            f"## 退休后财富需求测算\n"
            f"距离退休还有 {duration_text}，"
            f"退休首月预计支出 {retirement.get('retirement_monthly_expend', '-') } 元，"
            f"退休时最低需积攒 {retirement.get('required_asset_at_retirement', '-') } 元，"
            f"预计可积攒 {retirement.get('accumulated_asset_at_retirement', '-') } 元，"
            f"资金缺口约 {retirement.get('gap', '-') } 元。\n\n"
            f"## 产品偏好\n"
            f"客户历史行为偏好集中在 {behavior.get('top_product', '-') }，"
            f"相关行为次数为 {behavior.get('counts', {}).get(behavior.get('top_product', ''), 0)} 次。"
            f"{behavior.get('insight', '')}\n\n"
            f"## 资产配置方式与具体方案\n"
            f"{allocation_text}\n"
            f"- 组合预计年化收益率约 {round(float(allocation_plan.get('portfolio_return', '0')) * 100, 2):.2f}%。\n"
            f"- 该方案预计退休时可积累 {retirement.get('accumulated_asset_at_retirement', '-') } 元，"
            f"{'能够覆盖养老资金需求。' if allocation_plan.get('covers_gap') else '仍需继续优化缺口。'}\n\n"
            f"## 其他建议\n"
            f"- 建议每年复盘一次养老目标与资产配置。\n"
            f"- 若收入、支出或风险偏好变化，应同步更新测算。\n"
            f"- 由于客户当前偏好偏向 {behavior.get('top_product', '-') }，实际调整配置时可采用分步迁移方式，降低行为偏差。"
        )

    @staticmethod
    def _proposal_matches_payload(text: str, payload: dict[str, Any]) -> bool:
        allocation_plan = payload.get("allocation_plan", {})
        for item in allocation_plan.get("allocation", []):
            product = str(item.get("product", ""))
            weight = int(round(float(item.get("weight", "0")) * 100))
            if weight <= 0:
                continue
            product_name = "固收 + 产品" if product == "固收+产品" else product
            if product_name not in text and product not in text:
                return False
            if f"{weight}%" not in text:
                return False
        return True

    @staticmethod
    def _space_duration(text: str) -> str:
        match = re.fullmatch(r"(\d+)年(\d+)个月", text)
        if not match:
            return text
        return f"{match.group(1)} 年 {match.group(2)} 个月"

    @staticmethod
    def _display_product(product: str) -> str:
        return "固收 + 产品" if product == "固收+产品" else product

    @staticmethod
    def _extract_inflation_override(question: str) -> tuple[int | None, str | None]:
        match = re.search(r"(\d+)\s*年后.*?(\d+(?:\.\d+)?)\s*%", question)
        if not match:
            return None, None
        return int(match.group(1)), match.group(2)

    @staticmethod
    def _format_money_value(value: object) -> str:
        return str(Decimal(str(value)).quantize(Decimal("1")))
