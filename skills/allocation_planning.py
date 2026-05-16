from __future__ import annotations

from config.settings import AppConfig
from tools.allocation_engine import AllocationEngine
from tools.memory_manager import MemoryManager

from skills.behavior_analysis import BehaviorAnalysisSkill
from skills.customer_profile import CustomerProfileSkill
from skills.retirement_calc import RetirementCalculationSkill


class AllocationPlanningSkill:
    def __init__(
        self,
        config: AppConfig,
        profile_skill: CustomerProfileSkill,
        behavior_skill: BehaviorAnalysisSkill,
        retirement_skill: RetirementCalculationSkill,
        memory_manager: MemoryManager,
    ) -> None:
        self.profile_skill = profile_skill
        self.behavior_skill = behavior_skill
        self.retirement_skill = retirement_skill
        self.memory_manager = memory_manager
        self.engine = AllocationEngine(config)

    def plan(self, session_id: str, customer_id: str):
        state = self.memory_manager.get_session(session_id)
        profile = self.profile_skill.get_profile(session_id, customer_id)
        behavior = self.behavior_skill.analyze(customer_id)
        retirement = self.retirement_skill.calculate(session_id, customer_id)
        return self.engine.build_plan(profile, retirement, behavior, state.preferences, state.scenario)

    def answer(self, session_id: str, customer_id: str) -> str:
        plan = self.plan(session_id, customer_id)
        ordered_items = sorted(
            (item for item in plan.allocation if item.weight > 0),
            key=lambda item: item.weight,
            reverse=True,
        )
        allocation_text = "，".join(
            f"{int(item.weight * 100)}% 配置于 {item.product}" for item in ordered_items
        )
        cover_text = "能够覆盖养老金缺口" if plan.covers_gap else "暂时仍无法完全覆盖养老金缺口"
        return (
            f"建议客户 {customer_id} {allocation_text}。在当前假设下，组合预计年化收益率约 "
            f"{plan.portfolio_return * 100:.2f}%，"
            f"退休时预计积累 {int(plan.retirement_asset_projection)} 元，{cover_text}。"
        )
