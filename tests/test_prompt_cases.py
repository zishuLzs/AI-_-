from __future__ import annotations

import unittest

from llm.schemas import MemoryUpdate, PlannerOutput
from orchestrator.composer import LLMComposer
from orchestrator.executor import ToolExecutor
from tools.memory_manager import MemoryManager


class _StubSkill:
    pass


class TestPromptCases(unittest.TestCase):
    def test_case_style_hint_for_single_value(self) -> None:
        hint = LLMComposer._build_case_style_hint("profile_single_value")
        self.assertIn("只输出最终值", hint)

    def test_case_style_hint_for_min_risk(self) -> None:
        hint = LLMComposer._build_case_style_hint("allocation_min_risk")
        self.assertIn("比例方案", hint)
        self.assertIn("主力产品", hint)

    def test_planner_output_has_case_tag_field(self) -> None:
        plan = PlannerOutput(
            intent="retirement",
            customer_id="V500001",
            memory_update=MemoryUpdate(),
            tool_calls=[],
            answer_mode="short",
            case_tag="retirement_required_asset",
        )
        self.assertEqual(plan.case_tag, "retirement_required_asset")

    def test_proposal_guidance_prefers_long_term_objective(self) -> None:
        memory = MemoryManager()
        memory.remember_preferences(
            "s1",
            {"allocation_objective": "minimize_risk"},
        )
        memory.remember_scenario(
            "s1",
            {"allocation_objective": "maximize_return"},
        )
        state = memory.get_session("s1")

        guidance = ToolExecutor._build_proposal_guidance(state)
        self.assertEqual(guidance["effective_allocation_objective"], "minimize_risk")
        self.assertEqual(guidance["allocation_objective_source"], "preference")
        self.assertTrue(guidance["conflict_notes"])

    def test_proposal_guidance_prefers_long_term_goal_amount(self) -> None:
        memory = MemoryManager()
        memory.remember_preferences(
            "s1",
            {"retirement_goal_monthly_expend": 12000},
        )
        memory.remember_scenario(
            "s1",
            {"retirement_goal_monthly_expend": 15000},
        )
        state = memory.get_session("s1")

        guidance = ToolExecutor._build_proposal_guidance(state)
        self.assertEqual(guidance["effective_retirement_goal_monthly_expend"], 12000)
        self.assertEqual(guidance["retirement_goal_monthly_expend_source"], "preference")
        self.assertTrue(guidance["conflict_notes"])


if __name__ == "__main__":
    unittest.main()
