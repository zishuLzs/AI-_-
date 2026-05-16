from __future__ import annotations

import unittest

from llm.schemas import MemoryUpdate, PlannerOutput
from orchestrator.composer import LLMComposer


class _StubLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.messages: list[dict[str, str]] | None = None

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        self.messages = messages
        return self.response


class TestAnswerRegression(unittest.TestCase):
    def test_q1_single_value_answer_shape(self) -> None:
        llm = _StubLLMClient("22 岁")
        composer = LLMComposer(llm)
        plan = PlannerOutput(
            intent="profile",
            customer_id="V500001",
            memory_update=MemoryUpdate(),
            tool_calls=[],
            answer_mode="short",
            case_tag="profile_single_value",
        )
        answer = composer.compose(
            "客户 V500001 现在年龄多大？",
            plan,
            {"get_profile": {"age": 22}},
        )
        self.assertEqual(answer, "22 岁")
        assert llm.messages is not None
        self.assertIn("只输出最终值", llm.messages[1]["content"])

    def test_q13_min_risk_answer_shape(self) -> None:
        llm = _StubLLMClient("固收 + 产品配置 73%；现金理财 10%；年金险 17%\n主力产品为固收 + 产品。")
        composer = LLMComposer(llm)
        plan = PlannerOutput(
            intent="allocation",
            customer_id="V500001",
            memory_update=MemoryUpdate(),
            tool_calls=[],
            answer_mode="normal",
            case_tag="allocation_min_risk",
        )
        answer = composer.compose(
            "客户 V500001 想要在满足养老需求基础上最小化风险波动，请为他提供资产配置方案。",
            plan,
            {
                "build_allocation": {
                    "allocation": [
                        {"product": "固收+产品", "weight": "0.73"},
                        {"product": "现金理财", "weight": "0.10"},
                        {"product": "年金险", "weight": "0.17"},
                    ]
                }
            },
        )
        self.assertIn("73%", answer)
        assert llm.messages is not None
        self.assertIn("比例方案", llm.messages[1]["content"])
        self.assertIn("主力产品", llm.messages[1]["content"])

    def test_q15_proposal_prompt_contains_guidance(self) -> None:
        llm = _StubLLMClient("基本情况\n基本假设\n养老目标\n退休后财富需求测算\n产品偏好\n资产配置方式与具体方案\n其他建议")
        composer = LLMComposer(llm)
        plan = PlannerOutput(
            intent="proposal",
            customer_id="V500001",
            memory_update=MemoryUpdate(),
            tool_calls=[],
            answer_mode="proposal",
            case_tag="proposal_full",
        )
        payload = {
            "generate_proposal_payload": {
                "profile": {"customer_id": "V500001"},
                "proposal_guidance": {
                    "effective_allocation_objective": "minimize_risk",
                    "allocation_objective_source": "preference",
                    "conflict_notes": [
                        "客户长期观点与本轮临时假设在资产配置目标上冲突，最终建议书必须以长期观点为准。"
                    ],
                },
            }
        }
        answer = composer.compose("请为客户 V500001 生成养老规划建议书。", plan, payload)
        self.assertIn("基本情况", answer)
        assert llm.messages is not None
        self.assertIn("proposal_guidance", llm.messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
