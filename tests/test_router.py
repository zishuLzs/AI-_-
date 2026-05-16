from __future__ import annotations

import unittest
from decimal import Decimal

from tools.memory_manager import MemoryManager
from tools.router import IntentRouter


class TestIntentRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter(MemoryManager())

    def test_extract_customer_and_intent(self) -> None:
        route = self.router.route("客户 V500001 现在年龄多大？", "s1")
        self.assertEqual(route.customer_id, "V500001")
        self.assertEqual(route.intent, "profile")

    def test_extract_preference(self) -> None:
        """'希望' should go to preferences (long-term)."""
        route = self.router.route(
            "客户 V500002 希望退休后每月生活费达到 1.5 万元。", "s1"
        )
        self.assertEqual(
            route.preferences.get("retirement_goal_monthly_expend"), Decimal("15000")
        )
        self.assertNotIn("retirement_goal_monthly_expend", route.scenario)

    def test_extract_scenario_hypothetical(self) -> None:
        """'如果' should go to scenario (temporary)."""
        route = self.router.route(
            "如果通胀率变成 3%，客户 V500001 的缺口是多少？", "s1"
        )
        self.assertEqual(route.scenario["inflation_annual"], Decimal("0.03"))
        self.assertEqual(route.intent, "retirement")

    def test_hypothetical_monthly_expend_in_scenario(self) -> None:
        """'如果...每月想要1.5万' should go to scenario, not preferences."""
        route = self.router.route(
            "如果客户 V500002 退休后每月想要 1.5 万元生活费，她的缺口是多少？",
            "s1",
        )
        self.assertIn("retirement_goal_monthly_expend", route.scenario)
        self.assertNotIn("retirement_goal_monthly_expend", route.preferences)

    def test_preference_monthly_expend_in_preferences(self) -> None:
        """'希望...每月生活费1.5万' should go to preferences."""
        route = self.router.route(
            "客户 V500002 希望退休后每月生活费达到 1.5 万元。",
            "s1",
        )
        self.assertIn("retirement_goal_monthly_expend", route.preferences)
        self.assertNotIn("retirement_goal_monthly_expend", route.scenario)

    def test_count_query(self) -> None:
        route = self.router.route("我有多少客户年龄在 30 岁及以上？", "s1")
        self.assertEqual(route.intent, "profile")
        self.assertIsNone(route.customer_id)

    def test_behavior_query(self) -> None:
        route = self.router.route("客户 V500001 对什么类型的产品行为最多？", "s1")
        self.assertEqual(route.intent, "behavior")
        self.assertEqual(route.customer_id, "V500001")

    def test_retirement_duration(self) -> None:
        route = self.router.route("客户 V500003 距离退休还有多久？", "s1")
        self.assertEqual(route.intent, "retirement")

    def test_proposal(self) -> None:
        route = self.router.route("为客户 V500001 生成一份养老规划建议书", "s1")
        self.assertEqual(route.intent, "proposal")

    def test_allocation(self) -> None:
        route = self.router.route("客户 V500001 应该如何配置资产？", "s1")
        self.assertEqual(route.intent, "allocation")

    def test_focus_points(self) -> None:
        route = self.router.route("客户关注流动性和长寿风险", "s1")
        focus = route.preferences.get("focus_points", [])
        self.assertIn("流动性", focus)
        self.assertIn("长寿风险", focus)

    def test_context_intent(self) -> None:
        route = self.router.route("客户 V500002 偏好稳健，关注流动性和长寿风险", "s1")
        self.assertEqual(route.intent, "context")

    def test_hypothetical_monthly_expend_goes_to_scenario(self) -> None:
        route = self.router.route(
            "如果客户 V500002 退休后每月想要 1.5 万元生活费，该怎么规划？", "s1"
        )
        self.assertIn("retirement_goal_monthly_expend", route.scenario)
        self.assertNotIn("retirement_goal_monthly_expend", route.preferences)

    def test_no_customer_id_for_aggregate(self) -> None:
        """Aggregate queries should not require customer_id."""
        route = self.router.route(
            "浏览权益类产品在 2 次及以上的客户，他们的平均年龄是多大？", "s1"
        )
        self.assertEqual(route.intent, "behavior")
        self.assertIsNone(route.customer_id)

    # === F1: Average routing fix ===

    def test_average_age_routes_to_profile(self) -> None:
        """Simple average age query should route to profile, not behavior."""
        route = self.router.route("客户的年龄平均是多少？", "s1")
        self.assertEqual(route.intent, "profile")
        self.assertIsNone(route.customer_id)

    def test_average_income_routes_to_profile(self) -> None:
        """Simple average income query should route to profile."""
        route = self.router.route("客户的月收入平均是多少？", "s1")
        self.assertEqual(route.intent, "profile")

    def test_behavior_average_age_still_behavior(self) -> None:
        """Q4-type: average age with browse/purchase keywords still routes to behavior."""
        route = self.router.route(
            "浏览权益类产品在 2 次及以上的客户，他们的平均年龄是多大？", "s1"
        )
        self.assertEqual(route.intent, "behavior")

    # === F2: Clause-level scenario/preference isolation ===

    def test_mixed_scenario_and_preference(self) -> None:
        """Mixed question: '想要...如果...' should split correctly by clause."""
        route = self.router.route(
            "客户 V500002 想要退休后每月生活费达到 1.5 万元，如果通胀率变成 3%，她的缺口是多少？",
            "s1",
        )
        # The '想要' clause → preferences
        self.assertEqual(
            route.preferences.get("retirement_goal_monthly_expend"),
            Decimal("15000"),
        )
        # The '如果' clause → scenario
        self.assertEqual(route.scenario.get("inflation_annual"), Decimal("0.03"))

    def test_hypothetical_clause_does_not_pollute_preferences(self) -> None:
        """'如果...流动性...' should not add 流动性 to focus_points."""
        route = self.router.route(
            "如果客户关注流动性，那配置方案该怎么做？",
            "s1",
        )
        focus = route.preferences.get("focus_points", [])
        self.assertNotIn("流动性", focus)

    def test_preference_clause_still_adds_focus(self) -> None:
        """Non-hypothetical clause mentioning 流动性 should add to focus_points."""
        route = self.router.route(
            "客户关注流动性和长寿风险，如果通胀率变成3%呢？", "s1"
        )
        focus = route.preferences.get("focus_points", [])
        self.assertIn("流动性", focus)
        self.assertIn("长寿风险", focus)

    def test_goal_and_scenario_in_mixed_question(self) -> None:
        """'希望...生活费...如果通胀...' — goal in preferences, inflation in scenario."""
        route = self.router.route(
            "客户 V500002 希望退休后每月生活费达到 1.5 万元，如果通胀率变成 3%，她的缺口是多少？",
            "s1",
        )
        self.assertEqual(
            route.preferences.get("retirement_goal_monthly_expend"),
            Decimal("15000"),
        )
        self.assertEqual(route.scenario.get("inflation_annual"), Decimal("0.03"))


if __name__ == "__main__":
    unittest.main()
