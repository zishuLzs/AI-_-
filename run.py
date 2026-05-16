"""Entry point for the pension planning agent evaluation.

Supports two modes:
1. CLI: python3 run.py "客户V500001现在年龄多大？"
2. API: run("问题")

Architecture: LLM-first, Tool-constrained, Failure-visible.
- LLMPlanner handles intent, params, and tool planning
- ToolExecutor runs deterministic tools (SQL, formulas, allocation)
- LLMComposer generates final answers
- No rule-based routing fallback in the main path.
"""

from __future__ import annotations

import logging
import os
import re
import sys

_LOG_LEVEL = os.getenv("TASK2_LOG_LEVEL", "CRITICAL").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.CRITICAL),
    format="%(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger(__name__)

from config.settings import DEFAULT_CONFIG
from llm.client import LLMClient
from llm.schemas import PlannerOutput
from orchestrator.composer import LLMComposer
from orchestrator.executor import ToolExecutor, ToolExecutionFailure
from orchestrator.failures import FailureCategory, format_user_failure
from orchestrator.planner import LLMPlanner
from skills.allocation_planning import AllocationPlanningSkill
from skills.behavior_analysis import BehaviorAnalysisSkill
from skills.customer_profile import CustomerProfileSkill
from skills.retirement_calc import RetirementCalculationSkill
from tools.memory_manager import MemoryManager
from tools.sql_executor import SQLExecutor

def _build_agent() -> "PensionPlanningAgent":
    llm_client = LLMClient()
    db_config = SQLExecutor.get_db_config()
    sql_executor = SQLExecutor(db_config)
    memory_manager = MemoryManager()

    profile_skill = CustomerProfileSkill(sql_executor, memory_manager)
    behavior_skill = BehaviorAnalysisSkill(sql_executor, profile_skill)
    retirement_skill = RetirementCalculationSkill(
        DEFAULT_CONFIG, profile_skill, memory_manager
    )
    allocation_skill = AllocationPlanningSkill(
        DEFAULT_CONFIG, profile_skill, behavior_skill,
        retirement_skill, memory_manager,
    )

    planner = LLMPlanner(llm_client, memory_manager)
    executor = ToolExecutor(
        profile_skill, behavior_skill, retirement_skill,
        allocation_skill, memory_manager,
    )
    composer = LLMComposer(llm_client)

    return PensionPlanningAgent(
        planner=planner,
        executor=executor,
        composer=composer,
        memory_manager=memory_manager,
    )
class PensionPlanningAgent:
    def __init__(
        self,
        planner: LLMPlanner,
        executor: ToolExecutor,
        composer: LLMComposer,
        memory_manager: MemoryManager,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.composer = composer
        self.memory_manager = memory_manager

    def answer(self, question: str, session_id: str = "default") -> str:
        # Step 1: LLM Planner — intent, params, tool plan
        try:
            plan = self.planner.plan(question, session_id)
        except Exception as e:
            logger.error("Planner unavailable: %s", e)
            return format_user_failure(FailureCategory.PLANNER_SCHEMA_ERROR)

        # Step 2: Apply narrow scenario overrides for legacy fallback safety
        self._apply_question_overrides(plan, question)

        # Step 3: Apply memory updates and execute tools
        try:
            tool_results = self.executor.execute(plan, session_id, question)
        except ToolExecutionFailure as e:
            logger.error("Tool execution failure: %s", e.record.detail)
            return format_user_failure(e.record.category)
        except Exception:
            logger.exception("Unexpected error in tool execution")
            return format_user_failure(FailureCategory.TOOL_EXECUTION_ERROR)

        # Step 4: Handle context-only (no tool results)
        if plan.intent == "context":
            self.memory_manager.clear_scenario(session_id)
            return "好的，已记录这些偏好与关注点，后续测算和建议会据此进行。"

        # Step 5: If no tool results and intent needs data, return error
        if (
            not tool_results
            and plan.intent not in ("profile", "fallback")
            and plan.case_tag != "allocation_longevity_adjust"
        ):
            return "抱歉，当前问题所需信息不完整。"

        # Step 6: LLM Composer — generate final answer
        try:
            result = self.composer.compose(question, plan, tool_results)
        except Exception:
            logger.exception("Composer failed — falling back to programmatic short answer")
            result = self.composer._fallback_short(question, plan, tool_results)
        finally:
            self.memory_manager.clear_scenario(session_id)

        return result

    @staticmethod
    def _apply_question_overrides(plan: "PlannerOutput", question: str) -> None:
        direct_inflation = re.search(
            r"通胀(?:率)?[^0-9]*(?:提升到|升到|按|算为|变为|提高到)?\s*(\d+(?:\.\d+)?)\s*%",
            question,
        )
        if direct_inflation and "年后" not in question:
            plan.memory_update.scenario["inflation_annual"] = str(
                float(direct_inflation.group(1)) / 100
            )

        if plan.case_tag == "retirement_scenario_inflation":
            match = re.search(
                r"(\d+)\s*年后.*?通胀率.*?(?:提升到|升到|变为|提高到)\s*(\d+(?:\.\d+)?)\s*%",
                question,
            )
            if match:
                years = int(match.group(1))
                annual = str(float(match.group(2)) / 100)
                plan.memory_update.scenario["inflation_annual"] = str(
                    DEFAULT_CONFIG.inflation_annual
                )
                plan.memory_update.scenario["inflation_after_years"] = years
                plan.memory_update.scenario["inflation_after_years_annual"] = annual

        saving_match = re.search(
            r"每月(?:(?:再)?(?:多存|多攒|多储蓄)|额外(?:储蓄|多存|多攒))\s*([0-9]+(?:\.[0-9]+)?)\s*(万)?\s*元?",
            question,
        )
        if saving_match:
            saving = float(saving_match.group(1))
            if saving_match.group(2):
                saving *= 10000
            plan.memory_update.scenario["extra_monthly_saving"] = int(round(saving))

        if "retirement_goal_monthly_expend" not in plan.memory_update.preferences and "retirement_goal_monthly_expend" not in plan.memory_update.scenario:
            spend_match = re.search(
                r"(?:退休后)?每月(?:生活费|想要|希望|需要支出|花)\s*([0-9]+(?:\.[0-9]+)?)\s*(万)?\s*元?",
                question,
            )
            if spend_match:
                spend = float(spend_match.group(1))
                if spend_match.group(2):
                    spend *= 10000
                target = (
                    plan.memory_update.scenario
                    if any(token in question for token in ("如果", "假如", "假设", "设想", "要是"))
                    else plan.memory_update.preferences
                )
                target["retirement_goal_monthly_expend"] = int(round(spend))


def run(inf: str) -> str:
    """Main entry point for the evaluation system.

    Each invocation builds a fresh agent and answers independently,
    so no cross-question state is shared across calls.

    Args:
        inf: The question string from the evaluation system.

    Returns:
        The answer string.
    """
    agent = _build_agent()
    try:
        return agent.answer(inf, "single_run")
    except Exception as exc:
        logger.warning("run() failed: %s", exc)
        return "抱歉，暂时无法回答该问题。"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = sys.stdin.read().strip()
    if question:
        print(run(question))
