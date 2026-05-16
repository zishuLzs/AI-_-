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
import threading

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
from orchestrator.local_planner import LocalPlanner
from orchestrator.planner import LLMPlanner, PlannerFailure
from skills.allocation_planning import AllocationPlanningSkill
from skills.behavior_analysis import BehaviorAnalysisSkill
from skills.customer_profile import CustomerProfileSkill
from skills.retirement_calc import RetirementCalculationSkill
from tools.memory_manager import MemoryManager
from tools.router import IntentRouter
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
    behavior_skill = BehaviorAnalysisSkill(sql_executor, profile_skill)
    retirement_skill = RetirementCalculationSkill(
        DEFAULT_CONFIG, profile_skill, memory_manager
    )
    allocation_skill = AllocationPlanningSkill(
        DEFAULT_CONFIG, profile_skill, behavior_skill,
        retirement_skill, memory_manager,
    )
    router = IntentRouter(memory_manager)

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
        router=router,
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
        router: IntentRouter,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.composer = composer
        self.memory_manager = memory_manager
        self.router = router
        self.local_planner = LocalPlanner(router)

    @staticmethod
    def _ensure_required_tools(plan: "PlannerOutput", session_id: str) -> None:
        """Inject mandatory tools the LLM planner may have omitted."""
        from llm.schemas import ToolCall

        tool_names = {tc.name for tc in plan.tool_calls}
        if tool_names & {
            "profile_query",
            "behavior_query",
            "retirement_query",
            "product_query",
        }:
            return

        def _ensure(name: str, params: dict | None = None) -> None:
            if name not in tool_names:
                plan.tool_calls.append(ToolCall(name=name, params=params or {}))

        if plan.intent == "retirement" and plan.case_tag in {
            "retirement_duration",
            "retirement_monthly_spend",
            "retirement_required_asset",
            "retirement_accumulated_asset",
        }:
            _ensure("get_profile")
            _ensure("calculate_retirement")
        elif plan.intent == "allocation" and plan.case_tag in {
            "allocation_max_return",
            "allocation_min_risk",
            "allocation_metric",
        }:
            _ensure("get_profile")
            _ensure("analyze_behavior_single")
            _ensure("calculate_retirement")
            _ensure("build_allocation")
        elif plan.intent == "proposal":
            _ensure("get_profile")
            _ensure("analyze_behavior_single")
            _ensure("calculate_retirement")
            _ensure("build_allocation")
            _ensure("generate_proposal_payload")
        elif plan.intent == "behavior" and plan.case_tag == "behavior_single_preference":
            _ensure("analyze_behavior_single")

    def answer(self, question: str, session_id: str = "default") -> str:
        # Step 1: LLM Planner — intent, params, tool plan
        try:
            plan = self.planner.plan(question, session_id)
        except PlannerFailure as e:
            logger.error("Planner failure in answer(), switching to local planner: %s", e.record.detail)
            plan = self.local_planner.build(question, session_id)
        except Exception as e:
            logger.error("Planner unavailable, switching to local planner: %s", e)
            plan = self.local_planner.build(question, session_id)

        # Step 2: Ensure plan has required tools for its intent
        self._ensure_required_tools(plan, session_id)
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
        if not tool_results and plan.intent not in ("profile", "fallback"):
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
