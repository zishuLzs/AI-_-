from __future__ import annotations

import unittest

from tools.memory_manager import MemoryManager


class TestMemoryManager(unittest.TestCase):
    def test_scenario_is_clearable(self) -> None:
        memory = MemoryManager()
        memory.remember_scenario("s1", {"inflation_annual": 0.03})
        self.assertEqual(memory.get_session("s1").scenario["inflation_annual"], 0.03)
        memory.clear_scenario("s1")
        self.assertEqual(memory.get_session("s1").scenario, {})

    def test_preferences_persist(self) -> None:
        memory = MemoryManager()
        memory.remember_preferences("s1", {"retirement_goal": "消费水平不下降"})
        memory.remember_preferences("s1", {"risk_preference_text": "稳健"})
        state = memory.get_session("s1")
        self.assertEqual(state.preferences["retirement_goal"], "消费水平不下降")
        self.assertEqual(state.preferences["risk_preference_text"], "稳健")

    def test_focus_points_accumulate(self) -> None:
        memory = MemoryManager()
        memory.remember_preferences("s1", {"focus_points": ["流动性"]})
        memory.remember_preferences("s1", {"focus_points": ["长寿风险"]})
        state = memory.get_session("s1")
        self.assertIn("流动性", state.focus_points)
        self.assertIn("长寿风险", state.focus_points)

    def test_scenario_does_not_affect_other_sessions(self) -> None:
        memory = MemoryManager()
        memory.remember_scenario("s1", {"inflation_annual": 0.03})
        memory.clear_scenario("s1")
        self.assertEqual(memory.get_session("s2").scenario, {})

    def test_customer_id_persists(self) -> None:
        memory = MemoryManager()
        memory.set_customer_id("s1", "V500001")
        self.assertEqual(memory.get_session("s1").customer_id, "V500001")

    def test_switch_customer_clears_old_context(self) -> None:
        memory = MemoryManager()
        memory.set_customer_id("s1", "V500001")
        memory.remember_preferences("s1", {"retirement_goal": "消费水平不下降"})
        memory.set_customer_id("s1", "V500002")
        state = memory.get_session("s1")
        self.assertEqual(state.customer_id, "V500002")
        self.assertEqual(state.preferences, {})
        self.assertEqual(state.focus_points, [])


if __name__ == "__main__":
    unittest.main()
