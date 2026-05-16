from __future__ import annotations

import unittest
from decimal import Decimal

from config.settings import DEFAULT_CONFIG
from models import CustomerProfile
from tools.formula_engine import RetirementFormulaEngine, round_money


class TestFormulaEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RetirementFormulaEngine(DEFAULT_CONFIG)

    def test_retirement_age_male_50(self) -> None:
        """V500003: 50-year-old male, retirement at 62y7m."""
        years, months = self.engine.calculate_retirement_age("男", 50)
        self.assertEqual(years, 62)
        self.assertEqual(months, 7)

    def test_retirement_age_male_22(self) -> None:
        """V500001: 22-year-old male, retirement at 63y0m (capped at 36 months delay)."""
        years, months = self.engine.calculate_retirement_age("男", 22)
        self.assertEqual(years, 63)
        self.assertEqual(months, 0)

    def test_retirement_age_female_36(self) -> None:
        """V500002: 36-year-old female, base 55, delay calculation."""
        years, months = self.engine.calculate_retirement_age("女", 36)
        self.assertEqual(years, 58)
        self.assertEqual(months, 0)

    def test_v500001_full_calculation(self) -> None:
        """V500001: Q6/Q7/Q8 full calculation verification."""
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
        result = self.engine.calculate(profile, {"retirement_goal": "消费水平不下降"}, {})

        # Q6: retirement monthly expend = 9076
        self.assertEqual(int(result.retirement_monthly_expend), 9076)
        # Retirement duration: 41 years 0 months
        self.assertEqual(result.retirement_duration_text, "41年0个月")
        # Q7: required asset ~985979 (within 0.1%)
        self.assertAlmostEqual(
            int(result.required_asset_at_retirement), 985979, delta=986,
        )
        # Q8: accumulated asset = 772715
        self.assertEqual(int(result.accumulated_asset_at_retirement), 772715)

    def test_v500003_calculation(self) -> None:
        """V500003: 50-year-old male, R1, near retirement."""
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

    def test_custom_monthly_expend(self) -> None:
        """When retirement_goal_monthly_expend is set, use it directly."""
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
        result = self.engine.calculate(
            profile, {"retirement_goal_monthly_expend": Decimal("15000")}, {},
        )
        self.assertEqual(int(result.retirement_monthly_expend), 15000)

    def test_scenario_inflation_override(self) -> None:
        """Scenario inflation override should affect calculation."""
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
        result_default = self.engine.calculate(profile, {}, {})
        result_high_inflation = self.engine.calculate(
            profile, {}, {"inflation_annual": Decimal("0.03")},
        )
        self.assertGreater(
            int(result_high_inflation.retirement_monthly_expend),
            int(result_default.retirement_monthly_expend),
        )

    def test_scenario_monthly_expend_override(self) -> None:
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
        result = self.engine.calculate(
            profile,
            {"retirement_goal_monthly_expend": Decimal("12000")},
            {"retirement_goal_monthly_expend": Decimal("15000")},
        )
        self.assertEqual(int(result.retirement_monthly_expend), 15000)

    def test_split_inflation_required_asset(self) -> None:
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
        result = self.engine.calculate(
            profile,
            {"retirement_goal": "消费水平不下降"},
            {
                "inflation_annual": Decimal("0.02"),
                "inflation_after_years": 10,
                "inflation_after_years_annual": Decimal("0.03"),
            },
        )
        self.assertEqual(int(result.required_asset_at_retirement), 1947939)

    def test_round_money(self) -> None:
        self.assertEqual(round_money(Decimal("9075.5")), Decimal("9076"))
        self.assertEqual(round_money(Decimal("9075.4")), Decimal("9075"))
        self.assertEqual(round_money(Decimal("985979.3")), Decimal("985979"))


if __name__ == "__main__":
    unittest.main()
