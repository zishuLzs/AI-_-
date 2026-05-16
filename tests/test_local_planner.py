from __future__ import annotations

import unittest

from llm.schemas import MemoryUpdate, PlannerOutput, ToolCall
from orchestrator.local_planner import LocalPlanner
from tools.memory_manager import MemoryManager
from tools.router import IntentRouter


class TestLocalPlanner(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = MemoryManager()
        self.planner = LocalPlanner(IntentRouter(self.memory))

    def test_build_profile_risk_count_variant(self) -> None:
        plan = self.planner.build("风险等级至少R3的客户有几个？", "s1")
        self.assertEqual(plan.intent, "profile")
        self.assertEqual(plan.case_tag, "profile_aggregate_value")
        self.assertEqual(plan.tool_calls[0].name, "profile_query")
        self.assertEqual(plan.tool_calls[0].params["field"], "risk_level")

    def test_build_retirement_aggregate_no_gap(self) -> None:
        plan = self.planner.build("通胀按3%算时，哪几位客户依然没有养老资金缺口？", "s1")
        self.assertEqual(plan.intent, "retirement")
        self.assertEqual(plan.case_tag, "retirement_aggregate")
        self.assertEqual(plan.tool_calls[0].name, "retirement_query")
        self.assertEqual(plan.tool_calls[0].params["metric"], "no_gap")

    def test_build_allocation_metric_from_min_risk_phrase(self) -> None:
        plan = self.planner.build(
            "客户V500002满足养老需求基础上的最小风险方案，预期年化收益率约是多少？",
            "s1",
        )
        self.assertEqual(plan.intent, "allocation")
        self.assertEqual(plan.case_tag, "allocation_metric")

    def test_merge_structured_plan_overrides_legacy_tools(self) -> None:
        llm_plan = PlannerOutput(
            intent="profile",
            customer_id=None,
            memory_update=MemoryUpdate(),
            tool_calls=[ToolCall(name="count_customers", params={"field": "age"})],
            answer_mode="short",
            case_tag="profile_count",
        )
        merged = self.planner.merge_with_llm_plan(
            llm_plan,
            "风险等级至少R3的客户有几个？",
            "s1",
        )
        self.assertEqual(merged.case_tag, "profile_aggregate_value")
        self.assertEqual(merged.tool_calls[0].name, "profile_query")


if __name__ == "__main__":
    unittest.main()
