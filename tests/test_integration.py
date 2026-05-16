"""Integration tests: verify routing + formula + allocation + proposal end-to-end.

These tests validate the full pipeline from intent routing through execution.
They do NOT require a database — they mock SQLExecutor responses.

Usage: python3 -m unittest tests.test_integration -v
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from config.settings import DEFAULT_CONFIG
from models import CustomerProfile
from tools.allocation_engine import AllocationEngine
from tools.formula_engine import RetirementFormulaEngine, round_money
from tools.memory_manager import MemoryManager
from tools.router import IntentRouter
from tools.sql_templates import SQLTemplates


class TestRoutingFormulaEndToEnd(unittest.TestCase):
    """Test that routing correctly dispatches to formula-based answers."""

    def setUp(self) -> None:
        self.memory = MemoryManager()
        self.router = IntentRouter(self.memory)
        self.engine = RetirementFormulaEngine(DEFAULT_CONFIG)
        self.profile = CustomerProfile(
            user_id="V500001",
            age=22,
            gender="男",
            risk_level="R3",
            net_asset=Decimal("5000"),
            monthly_income=Decimal("5000"),
            monthly_expend=Decimal("4000"),
            pension=Decimal("5000"),
            enterprise_ann=Decimal("0"),
        )

    def test_q1_age_route(self) -> None:
        route = self.router.route("客户 V500001 现在年龄多大？", "s1")
        self.assertEqual(route.intent, "profile")
        self.assertEqual(route.customer_id, "V500001")

    def test_q2_count_route(self) -> None:
        route = self.router.route("我有多少客户年龄在 30 岁及以上？", "s1")
        self.assertEqual(route.intent, "profile")
        self.assertIsNone(route.customer_id)

    def test_q3_behavior_route(self) -> None:
        route = self.router.route("客户 V500001 对什么类型的产品行为最多？", "s1")
        self.assertEqual(route.intent, "behavior")
        self.assertEqual(route.customer_id, "V500001")

    def test_q4_behavior_avg_age_route(self) -> None:
        route = self.router.route(
            "浏览权益类产品在 2 次及以上的客户，他们的平均年龄是多大？", "s1"
        )
        self.assertEqual(route.intent, "behavior")
        self.assertIsNone(route.customer_id)

    def test_q5_retirement_duration_route(self) -> None:
        route = self.router.route("客户 V500003 距离退休还有多久？", "s1")
        self.assertEqual(route.intent, "retirement")

    def test_q6_retirement_expend_route(self) -> None:
        route = self.router.route(
            "客户 V500001 想要退休后消费水平不下降，在他刚退休时，每月需要支出多少钱？",
            "s1",
        )
        self.assertEqual(route.intent, "retirement")
        self.assertIn("retirement_goal", route.preferences)

    def test_q7_required_asset_route(self) -> None:
        route = self.router.route(
            "客户 V500001 在退休时最低需要积攒多少钱，才能维持其消费水平不下降？",
            "s1",
        )
        self.assertEqual(route.intent, "retirement")

    def test_q8_accumulated_asset_route(self) -> None:
        route = self.router.route("客户 V500001 在退休时可以积攒下多少钱？", "s1")
        self.assertEqual(route.intent, "retirement")

    def test_v500001_q5_formula_duration(self) -> None:
        """V500001: retirement duration matches expected."""
        result = self.engine.calculate(self.profile, {}, {})
        self.assertEqual(result.retirement_duration_text, "41年0个月")

    def test_v500001_q6_formula_expend(self) -> None:
        """V500001: Q6 retirement monthly expend = 9076."""
        result = self.engine.calculate(
            self.profile, {"retirement_goal": "消费水平不下降"}, {}
        )
        self.assertEqual(int(result.retirement_monthly_expend), 9076)

    def test_v500001_q7_required_asset(self) -> None:
        """V500001: Q7 required asset ≈ 985979 (within 0.1%)."""
        result = self.engine.calculate(
            self.profile, {"retirement_goal": "消费水平不下降"}, {}
        )
        self.assertAlmostEqual(
            int(result.required_asset_at_retirement),
            985979,
            delta=986,
        )

    def test_v500001_q8_accumulated_asset(self) -> None:
        """V500001: Q8 accumulated asset = 772715."""
        result = self.engine.calculate(
            self.profile, {"retirement_goal": "消费水平不下降"}, {}
        )
        self.assertEqual(int(result.accumulated_asset_at_retirement), 772715)

    def test_v500003_retirement_duration(self) -> None:
        """V500003: 50-year-old male, retirement in 12y7m."""
        profile = CustomerProfile(
            user_id="V500003",
            age=50,
            gender="男",
            risk_level="R1",
            net_asset=Decimal("1000000"),
            monthly_income=Decimal("8000"),
            monthly_expend=Decimal("6000"),
            pension=Decimal("6000"),
            enterprise_ann=Decimal("0"),
        )
        result = self.engine.calculate(profile, {}, {})
        self.assertEqual(result.retirement_duration_text, "12年7个月")

    def test_v500002_female_retirement(self) -> None:
        """V500002: 36-year-old female, retirement at 58y0m."""
        profile = CustomerProfile(
            user_id="V500002",
            age=36,
            gender="女",
            risk_level="R5",
            net_asset=Decimal("600000"),
            monthly_income=Decimal("12000"),
            monthly_expend=Decimal("7000"),
            pension=Decimal("9000"),
            enterprise_ann=Decimal("500000"),
        )
        result = self.engine.calculate(profile, {}, {})
        self.assertEqual(result.retirement_age_years, 58)
        self.assertEqual(result.retirement_age_months, 0)

    def test_scenario_inflation_only(self) -> None:
        """Scenario inflation affects retirement monthly expenditure."""
        result_default = self.engine.calculate(self.profile, {}, {})
        result_inflation = self.engine.calculate(
            self.profile,
            {},
            {"inflation_annual": Decimal("0.03")},
        )
        self.assertGreater(
            int(result_inflation.retirement_monthly_expend),
            int(result_default.retirement_monthly_expend),
        )

    def test_negative_gap_returns_zero_required(self) -> None:
        """When pension covers all expenses, required_asset should be 0, gap negative."""
        profile = CustomerProfile(
            user_id="HIGH_PENSION",
            age=60,
            gender="男",
            risk_level="R1",
            net_asset=Decimal("0"),
            monthly_income=Decimal("50000"),
            monthly_expend=Decimal("3000"),
            pension=Decimal("50000"),
            enterprise_ann=Decimal("0"),
        )
        result = self.engine.calculate(profile, {}, {})
        # required_asset bounded to >= 0 by max(..., 0)
        self.assertGreaterEqual(int(result.required_asset_at_retirement), 0)
        # gap = required_asset - accumulated_asset, can be negative (surplus)
        # The formula engine correctly reports raw gap (caller checks <= 0)
        self.assertLessEqual(int(result.gap), 0)

    def test_enterprise_annuity_reduces_required_asset(self) -> None:
        """Enterprise annuity should reduce the required asset."""
        profile_no_ann = CustomerProfile(
            user_id="V500001",
            age=22,
            gender="男",
            risk_level="R3",
            net_asset=Decimal("5000"),
            monthly_income=Decimal("5000"),
            monthly_expend=Decimal("4000"),
            pension=Decimal("5000"),
            enterprise_ann=Decimal("0"),
        )
        profile_with_ann = CustomerProfile(
            user_id="V500001",
            age=22,
            gender="男",
            risk_level="R3",
            net_asset=Decimal("5000"),
            monthly_income=Decimal("5000"),
            monthly_expend=Decimal("4000"),
            pension=Decimal("5000"),
            enterprise_ann=Decimal("500000"),
        )
        result_no = self.engine.calculate(profile_no_ann, {}, {})
        result_with = self.engine.calculate(profile_with_ann, {}, {})
        self.assertLess(
            int(result_with.required_asset_at_retirement),
            int(result_no.required_asset_at_retirement),
        )

    def test_saving_increases_accumulated(self) -> None:
        """Extra monthly saving should increase accumulated asset."""
        result_base = self.engine.calculate(self.profile, {}, {})
        result_extra = self.engine.calculate(
            self.profile,
            {},
            {"extra_monthly_saving": Decimal("2000")},
        )
        self.assertGreater(
            int(result_extra.accumulated_asset_at_retirement),
            int(result_base.accumulated_asset_at_retirement),
        )


class TestSQLTemplateStructure(unittest.TestCase):
    """Validate SQL template structure without executing."""

    def test_product_map_covers_all_products(self) -> None:
        case_sql = SQLTemplates._product_case_expr()
        expected_products = [
            "现金理财",
            "定期存款",
            "短债类产品",
            "固收+产品",
            "权益类产品",
            "年金险",
        ]
        for prod in expected_products:
            self.assertIn(
                prod, case_sql, f"Product {prod} missing from CASE expression"
            )

    def test_single_field_valid_keys(self) -> None:
        for key in (
            "age",
            "gender",
            "risk_level",
            "net_asset",
            "monthly_income",
            "monthly_expend",
            "pension",
            "enterprise_ann",
        ):
            sql, params = SQLTemplates.select_single_field("V500001", key, "test_table")
            self.assertIn("SELECT", sql)
            self.assertEqual(params, ("V500001",))

    def test_single_field_invalid_key(self) -> None:
        with self.assertRaises(ValueError):
            SQLTemplates.select_single_field("V500001", "invalid_key", "test_table")


class TestAllocationEngine(unittest.TestCase):
    def test_build_plan_runs(self) -> None:
        engine = AllocationEngine(DEFAULT_CONFIG)
        profile = CustomerProfile(
            user_id="V500001",
            age=22,
            gender="男",
            risk_level="R3",
            net_asset=Decimal("5000"),
            monthly_income=Decimal("5000"),
            monthly_expend=Decimal("4000"),
            pension=Decimal("5000"),
            enterprise_ann=Decimal("0"),
        )
        formula = RetirementFormulaEngine(DEFAULT_CONFIG)
        retirement = formula.calculate(profile, {"retirement_goal": "消费水平不下降"}, {})
        plan = engine.build_plan(
            profile,
            retirement,
            {"top_product": "现金理财", "counts": {"现金理财": 9}},
            {"focus_points": ["流动性", "长寿风险"]},
        )
        self.assertTrue(plan.allocation)
        self.assertIsNotNone(plan.retirement_asset_projection)

    def test_maximize_return_prefers_highest_return_product(self) -> None:
        engine = AllocationEngine(DEFAULT_CONFIG)
        profile = CustomerProfile(
            user_id="V500001",
            age=22,
            gender="男",
            risk_level="R3",
            net_asset=Decimal("5000"),
            monthly_income=Decimal("5000"),
            monthly_expend=Decimal("4000"),
            pension=Decimal("5000"),
            enterprise_ann=Decimal("0"),
        )
        formula = RetirementFormulaEngine(DEFAULT_CONFIG)
        retirement = formula.calculate(profile, {"retirement_goal": "消费水平不下降"}, {})
        plan = engine.build_plan(
            profile,
            retirement,
            {"top_product": "现金理财", "counts": {"现金理财": 9}},
            {"allocation_objective": "maximize_return"},
        )
        top_item = max(plan.allocation, key=lambda item: item.weight)
        self.assertEqual(top_item.product, "固收+产品")
        self.assertEqual(int(top_item.weight * 100), 100)

    def test_minimize_risk_keeps_diversified_solution(self) -> None:
        engine = AllocationEngine(DEFAULT_CONFIG)
        profile = CustomerProfile(
            user_id="V500001",
            age=22,
            gender="男",
            risk_level="R3",
            net_asset=Decimal("5000"),
            monthly_income=Decimal("5000"),
            monthly_expend=Decimal("4000"),
            pension=Decimal("5000"),
            enterprise_ann=Decimal("0"),
        )
        formula = RetirementFormulaEngine(DEFAULT_CONFIG)
        retirement = formula.calculate(profile, {"retirement_goal": "消费水平不下降"}, {})
        plan = engine.build_plan(
            profile,
            retirement,
            {"top_product": "现金理财", "counts": {"现金理财": 9}},
            {"focus_points": ["流动性", "长寿风险"], "allocation_objective": "minimize_risk"},
        )
        non_zero = {item.product: int(item.weight * 100) for item in plan.allocation if item.weight > 0}
        self.assertIn("固收+产品", non_zero)
        self.assertGreaterEqual(len(non_zero), 2)

    def test_minimize_risk_matches_example_ratio(self) -> None:
        engine = AllocationEngine(DEFAULT_CONFIG)
        profile = CustomerProfile(
            user_id="V500001",
            age=22,
            gender="男",
            risk_level="R3",
            net_asset=Decimal("5000"),
            monthly_income=Decimal("5000"),
            monthly_expend=Decimal("4000"),
            pension=Decimal("5000"),
            enterprise_ann=Decimal("0"),
        )
        formula = RetirementFormulaEngine(DEFAULT_CONFIG)
        retirement = formula.calculate(profile, {"retirement_goal": "消费水平不下降"}, {})
        plan = engine.build_plan(
            profile,
            retirement,
            {"top_product": "现金理财", "counts": {"现金理财": 9}},
            {"allocation_objective": "minimize_risk"},
            {},
        )
        non_zero = [(item.product, int(item.weight * 100)) for item in plan.allocation if item.weight > 0]
        self.assertEqual(non_zero, [("固收+产品", 73), ("现金理财", 10), ("年金险", 17)])


if __name__ == "__main__":
    unittest.main()
