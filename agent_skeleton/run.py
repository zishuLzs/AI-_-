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
import sys
import threading

logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import DEFAULT_CONFIG
from llm.client import LLMClient
from orchestrator.composer import LLMComposer
from orchestrator.executor import ToolExecutor, ToolExecutionFailure
from orchestrator.failures import FailureCategory, format_user_failure
from orchestrator.planner import LLMPlanner, PlannerFailure
from skills.allocation_planning import AllocationPlanningSkill
from skills.behavior_analysis import BehaviorAnalysisSkill
from skills.customer_profile import CustomerProfileSkill
from skills.retirement_calc import RetirementCalculationSkill
from tools.memory_manager import MemoryManager
from tools.sql_executor import SQLExecutor


_RUNTIME_LOCK = threading.Lock()
_AGENT: "PensionPlanningAgent | None" = None
_SESSION_ID = "eval_session"


def _build_agent() -> "PensionPlanningAgent":
    llm_client = LLMClient()
    db_config = SQLExecutor.get_db_config()
    sql_executor = SQLExecutor(db_config)
    memory_manager = MemoryManager()

    profile_skill = CustomerProfileSkill(sql_executor, memory_manager)
    behavior_skill = BehaviorAnalysisSkill(sql_executor)
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


def _get_agent() -> "PensionPlanningAgent":
    global _AGENT
    with _RUNTIME_LOCK:
        if _AGENT is None:
            _AGENT = _build_agent()
        return _AGENT


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
        except PlannerFailure as e:
            logger.error("Planner failure in answer(): %s", e.record.detail)
            return format_user_failure(e.record.category)

        # Step 2: Apply memory updates and execute tools
        try:
            tool_results = self.executor.execute(plan, session_id, question)
        except ToolExecutionFailure as e:
            logger.error("Tool execution failure: %s", e.record.detail)
            return format_user_failure(e.record.category)
        except Exception as e:
            logger.error("Unexpected error in tool execution: %s", e)
            return format_user_failure(FailureCategory.TOOL_EXECUTION_ERROR)

        # Step 3: Handle context-only (no tool results)
        if plan.intent == "context":
            self.memory_manager.clear_scenario(session_id)
            return "好的，已记录这些偏好与关注点，后续测算和建议会据此进行。"

        # Step 4: If no tool results and intent needs data, return error
        if not tool_results and plan.intent not in ("profile", "fallback"):
            return "抱歉，当前问题所需信息不完整。"

        # Step 5: LLM Composer — generate final answer
        try:
            result = self.composer.compose(question, plan, tool_results)
        except Exception as e:
            logger.warning("Composer failed: %s — falling back to programmatic short answer", e)
            result = self.composer._fallback_short(question, plan, tool_results)
        finally:
            self.memory_manager.clear_scenario(session_id)

        return result


def run(inf: str) -> str:
    """Main entry point for the evaluation system.

    State is preserved within the same process to support multi-turn
    follow-up questions, while different processes remain isolated.

    Args:
        inf: The question string from the evaluation system.

    Returns:
        The answer string.
    """
    agent = _get_agent()
    try:
        return agent.answer(inf, _SESSION_ID)
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
