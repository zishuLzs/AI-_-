"""Intent router with clause-level scenario/preference separation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from tools.memory_manager import MemoryManager


CUSTOMER_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[VT]\d{6}(?![A-Za-z0-9])", re.IGNORECASE
)

# Hypothetical keywords — these mean the clause is a "what-if" scenario
_HYPOTHETICAL_TOKENS = ("如果", "假如", "假设", "设想", "要是")
# Preference keywords — these mean the customer has a real preference/opinion
_PREFERENCE_TOKENS = ("希望", "想要", "预期", "打算", "偏好", "认为")
_FOCUS_TOKENS = ("流动性", "长寿风险", "税务", "稳健", "消费水平不下降", "生活水平不下降")
_QUERY_TOKENS = (
    "多少",
    "多大",
    "多久",
    "什么",
    "如何",
    "哪种",
    "哪类",
    "建议书",
    "方案",
    "配置",
    "缺口",
    "积攒",
    "支出",
    "退休金",
    "养老金",
    "平均",
)
# Clause delimiter pattern — split on Chinese/English punctuation
_CLAUSE_SPLIT = re.compile(r"[，。,。？?!！;；]")


@dataclass
class RouteResult:
    intent: str
    customer_id: str | None
    preferences: dict[str, object] = field(default_factory=dict)
    scenario: dict[str, object] = field(default_factory=dict)


class IntentRouter:
    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    def route(self, question: str, session_id: str) -> RouteResult:
        customer_id = (
            self._extract_customer_id(question)
            or self.memory_manager.get_session(session_id).customer_id
        )
        preferences, scenario = self._extract_params(question)
        intent = self._classify(question)
        return RouteResult(
            intent=intent,
            customer_id=customer_id,
            preferences=preferences,
            scenario=scenario,
        )

    @staticmethod
    def _extract_customer_id(question: str) -> str | None:
        match = CUSTOMER_ID_PATTERN.search(question)
        return match.group(0).upper() if match else None

    @staticmethod
    def _extract_money_value(text: str) -> Decimal | None:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万)?\s*元", text)
        if not match:
            return None
        value = Decimal(match.group(1))
        if match.group(2):
            value *= Decimal("10000")
        return value

    def _extract_params(
        self,
        question: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Extract preferences and scenario with clause-level context detection.

        Each clause is independently classified as hypothetical or preference-bearing.
        This handles mixed questions like:
            "客户V500002想要每月生活费1.5万元，如果通胀率变成3%，她的缺口是多少？"
        → "每月生活费1.5万元" → preferences (non-hypothetical clause)
        → "通胀率变成3%"     → scenario (hypothetical clause)
        """
        preferences: dict[str, object] = {}
        scenario: dict[str, object] = {}
        all_focus_points: list[str] = []

        clauses = _CLAUSE_SPLIT.split(question)

        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue

            clause_is_hyp = any(t in clause for t in _HYPOTHETICAL_TOKENS)
            target = scenario if clause_is_hyp else preferences

            # Retirement goal: 消费水平不下降/生活水平不下降
            if any(token in clause for token in ("消费水平不下降", "生活水平不下降")):
                target["retirement_goal"] = "消费水平不下降"

            # Monthly expenditure target
            if any(
                k in clause
                for k in ("每月生活费", "每月需要支出", "每月想要", "每月希望", "每月花")
            ):
                amount = self._extract_money_value(clause)
                if amount is not None:
                    target["retirement_goal_monthly_expend"] = amount

            # Inflation override (always scenario — inherently hypothetical)
            inflation_match = re.search(
                r"通胀(?:率)?[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*%",
                clause,
            )
            if inflation_match:
                scenario["inflation_annual"] = Decimal(
                    inflation_match.group(1)
                ) / Decimal("100")

            # Extra monthly saving (always scenario — inherently hypothetical)
            saving_match = re.search(
                r"每月(?:(?:再)?(?:多存|多攒|多储蓄)|额外(?:储蓄|多存|多攒))\s*([0-9]+(?:\.[0-9]+)?)\s*(万)?\s*元?",
                clause,
            )
            if saving_match:
                amount = Decimal(saving_match.group(1))
                if saving_match.group(2):
                    amount *= Decimal("10000")
                scenario["extra_monthly_saving"] = amount

            if "最大化投资收益" in clause or (
                "收益最大化" in clause and "风险" not in clause
            ):
                target["allocation_objective"] = "maximize_return"
            if "最小化风险波动" in clause or "风险最小" in clause:
                target["allocation_objective"] = "minimize_risk"

            # Focus points: only from non-hypothetical clauses
            if not clause_is_hyp:
                if "稳健" in clause:
                    preferences["risk_preference_text"] = "稳健"
                    all_focus_points.append("稳健")
                if "流动性" in clause:
                    all_focus_points.append("流动性")
                if "长寿风险" in clause:
                    all_focus_points.append("长寿风险")
                if "税务" in clause:
                    all_focus_points.append("税务规划")

        if all_focus_points:
            preferences["focus_points"] = all_focus_points

        return preferences, scenario

    @staticmethod
    def _classify(question: str) -> str:
        if (
            any(token in question for token in (_PREFERENCE_TOKENS + _FOCUS_TOKENS))
            and not any(token in question for token in _QUERY_TOKENS)
        ):
            return "context"
        if any(token in question for token in ("建议书", "投资建议书", "规划报告")):
            return "proposal"
        if any(token in question for token in ("配置", "方案", "组合", "适合什么产品")):
            return "allocation"
        if any(
            token in question
            for token in (
                "退休",
                "缺口",
                "积攒",
                "攒",
                "养老金",
                "距离",
                "离退休",
                "需要支出",
            )
        ):
            return "retirement"
        if any(
            token in question for token in ("偏好", "浏览", "购买", "行为", "产品行为")
        ):
            return "behavior"
        if "平均" in question and ("浏览" in question or "购买" in question):
            return "behavior"
        if any(
            token in question
            for token in (
                "年龄",
                "收入",
                "净资产",
                "风险",
                "多少客户",
                "客户数",
                "结余",
                "月支出",
                "月收入",
                "退休金",
                "企业年金",
                "平均",
            )
        ):
            return "profile"
        return "fallback"
