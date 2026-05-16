from __future__ import annotations

import unittest
from decimal import Decimal

from orchestrator.executor import ToolExecutor
from skills.behavior_analysis import BehaviorAnalysisSkill
from skills.customer_profile import CustomerProfileSkill
from tools.memory_manager import MemoryManager


class _FakeSQLExecutor:
    base_table = "train_base_table"
    action_table = "train_action_table"

    def __init__(self) -> None:
        self.profile_rows = [
            {
                "User_ID": "V500001",
                "Age": "22",
                "Gender": "男",
                "Rsk_Cd": "R3",
                "Net_Asset": "5000",
                "Monthly_Income": "5000",
                "Monthly_Expend": "4000",
                "Pension": "5000",
                "Enterprise_Ann": "0",
            },
            {
                "User_ID": "V500002",
                "Age": "36",
                "Gender": "女",
                "Rsk_Cd": "R5",
                "Net_Asset": "600000",
                "Monthly_Income": "12000",
                "Monthly_Expend": "7000",
                "Pension": "9000",
                "Enterprise_Ann": "500000",
            },
            {
                "User_ID": "V500003",
                "Age": "50",
                "Gender": "男",
                "Rsk_Cd": "R1",
                "Net_Asset": "1000000",
                "Monthly_Income": "8000",
                "Monthly_Expend": "6000",
                "Pension": "6000",
                "Enterprise_Ann": "0",
            },
        ]
        self.action_rows = self._build_actions()

    def _build_actions(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        def add(user_id: str, action_typ: str, prod_typ: str, prod_sub_typ: str, rsk_lvl: str, n: int) -> None:
            for _ in range(n):
                rows.append(
                    {
                        "user_id": user_id,
                        "action_typ": action_typ,
                        "prod_typ": prod_typ,
                        "prod_sub_typ": prod_sub_typ,
                        "rsk_lvl": rsk_lvl,
                    }
                )

        add("V500002", "浏览详情", "基金", "普通基金", "R4", 21)
        add("V500002", "购买", "理财", "普通理财", "R3", 2)
        add("V500002", "收藏", "理财", "现金", "R1", 1)
        add("V500003", "购买", "存款", "一般性", "R1", 3)
        add("V500001", "收藏", "理财", "现金", "R1", 1)
        return rows

    def fetch_one(self, sql: str, params: tuple | None = None) -> dict | None:
        if "WHERE User_ID = %s" in sql and params:
            user_id = params[0]
            for row in self.profile_rows:
                if row["User_ID"] == user_id:
                    return row
        return None

    def fetch_all(self, sql: str, params: tuple | None = None) -> list[dict]:
        if self.action_table in sql:
            return self.action_rows
        return self.profile_rows


class _StubRetirementSkill:
    def __init__(self) -> None:
        class _Engine:
            def calculate(self, profile, preferences, scenario):  # type: ignore[no-untyped-def]
                from models import RetirementResult

                values = {
                    "V500001": RetirementResult(63, 0, 492, "41年0个月", Decimal("9076"), Decimal("985979"), Decimal("772715"), Decimal("213264")),
                    "V500002": RetirementResult(58, 0, 264, "22年0个月", Decimal("10816"), Decimal("444229"), Decimal("2587699"), Decimal("-2143470")),
                    "V500003": RetirementResult(62, 7, 151, "12年7个月", Decimal("7724"), Decimal("552517"), Decimal("1628975"), Decimal("-1076458")),
                }
                return values[profile.user_id]

        self.formula_engine = _Engine()

    def calculate(self, session_id: str, customer_id: str):  # type: ignore[no-untyped-def]
        values = self.formula_engine.calculate(type("P", (), {"user_id": customer_id})(), {}, {})
        return values


class _StubAllocationSkill:
    def product_projections(self, session_id: str, customer_id: str):  # type: ignore[no-untyped-def]
        projections = {
            "V500001": [
                {"product": "现金理财", "annual_return": "0.015", "retirement_asset_projection": "688402", "covers_gap": False, "risk_score": 1},
                {"product": "定期存款", "annual_return": "0.02", "retirement_asset_projection": "772715", "covers_gap": False, "risk_score": 1},
                {"product": "短债类产品", "annual_return": "0.024", "retirement_asset_projection": "849616", "covers_gap": False, "risk_score": 2},
                {"product": "固收+产品", "annual_return": "0.0425", "retirement_asset_projection": "1353849", "covers_gap": True, "risk_score": 4},
                {"product": "年金险", "annual_return": "0.025", "retirement_asset_projection": "870301", "covers_gap": False, "risk_score": 2},
            ]
        }
        return projections[customer_id]


class _UnusedSkill:
    pass


class TestProfileAndBehaviorQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = _FakeSQLExecutor()
        self.memory = MemoryManager()
        self.profile_skill = CustomerProfileSkill(self.sql, self.memory)
        self.behavior_skill = BehaviorAnalysisSkill(self.sql, self.profile_skill)

    def test_profile_query_avg_net_asset(self) -> None:
        result = self.profile_skill.query({"field": "net_asset", "agg": "avg"})
        self.assertEqual(result["result"], "535000 元")

    def test_profile_query_count_risk_ge_r3(self) -> None:
        result = self.profile_skill.query(
            {"field": "risk_level", "agg": "count", "operator": ">=", "value": "R3"}
        )
        self.assertEqual(result["result"], "2 个")

    def test_profile_query_argmax_income(self) -> None:
        result = self.profile_skill.query({"field": "monthly_income", "agg": "argmax_customer"})
        self.assertEqual(result["result"], "V500002")

    def test_behavior_query_total_purchase(self) -> None:
        result = self.behavior_skill.query({"agg": "total_count", "action_type": "购买"})
        self.assertEqual(result["result"], "5 次")

    def test_behavior_query_single_customer_browse_equity(self) -> None:
        result = self.behavior_skill.query(
            {
                "agg": "customer_action_count",
                "action_type": "浏览",
                "product": "权益类产品",
                "customer_id": "V500002",
            }
        )
        self.assertEqual(result["result"], "21 次")

    def test_behavior_query_purchase_ranking(self) -> None:
        result = self.behavior_skill.query({"agg": "max_customer_id", "action_type": "购买"})
        self.assertEqual(result["result"], "V500003")


class TestExecutorStructuredQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = _FakeSQLExecutor()
        self.memory = MemoryManager()
        self.profile_skill = CustomerProfileSkill(self.sql, self.memory)
        self.behavior_skill = BehaviorAnalysisSkill(self.sql, self.profile_skill)
        self.retirement_skill = _StubRetirementSkill()
        self.allocation_skill = _StubAllocationSkill()
        self.executor = ToolExecutor(
            self.profile_skill,
            self.behavior_skill,
            self.retirement_skill,  # type: ignore[arg-type]
            self.allocation_skill,  # type: ignore[arg-type]
            self.memory,
        )

    def test_retirement_query_total_required_asset(self) -> None:
        result = self.executor._execute_retirement_query("s1", {"metric": "required_asset", "agg": "sum"})
        self.assertEqual(result["result"], "1982725 元")

    def test_product_query_shortfall(self) -> None:
        result = self.executor._execute_product_query(
            "s1",
            "V500001",
            {"product": "短债类产品", "mode": "shortfall"},
        )
        self.assertEqual(result["result"], "136363 元")


if __name__ == "__main__":
    unittest.main()
