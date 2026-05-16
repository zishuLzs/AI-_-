from __future__ import annotations

from config.settings import AppConfig
from models import RetirementResult
from tools.formula_engine import RetirementFormulaEngine
from tools.memory_manager import MemoryManager

from skills.customer_profile import CustomerProfileSkill


class RetirementCalculationSkill:
    def __init__(
        self,
        config: AppConfig,
        profile_skill: CustomerProfileSkill,
        memory_manager: MemoryManager,
    ) -> None:
        self.profile_skill = profile_skill
        self.memory_manager = memory_manager
        self.formula_engine = RetirementFormulaEngine(config)

    def calculate(self, session_id: str, customer_id: str) -> RetirementResult:
        state = self.memory_manager.get_session(session_id)
        profile = self.profile_skill.get_profile(session_id, customer_id)
        return self.formula_engine.calculate(profile, state.preferences, state.scenario)

    def answer(self, session_id: str, customer_id: str, question: str) -> str:
        result = self.calculate(session_id, customer_id)
        if "退休还有多久" in question or "距离退休" in question or "离退休" in question:
            return f"{result.retirement_duration_text}"
        if "每月需要支出" in question or "退休时支出" in question or "每月预计需要支出" in question:
            return f"{int(result.retirement_monthly_expend)} 元"
        if "最低需要积攒" in question or "最低需要攒" in question or "最低需积攒" in question:
            return f"{int(result.required_asset_at_retirement)} 元"
        if "可以积攒下多少钱" in question or "能积攒多少钱" in question or "可以积攒" in question:
            return f"{int(result.accumulated_asset_at_retirement)} 元"
        if "缺口" in question:
            gap_val = int(result.gap)
            if gap_val <= 0:
                return "在当前假设下不存在资金缺口"
            return f"{gap_val} 元"
        return (
            f"客户 {customer_id} 距离退休还有 {result.retirement_duration_text}，"
            f"退休首月支出约 {int(result.retirement_monthly_expend)} 元，"
            f"退休最低所需储备 {int(result.required_asset_at_retirement)} 元，"
            f"预计可积攒 {int(result.accumulated_asset_at_retirement)} 元，"
            f"缺口约 {int(result.gap)} 元。"
        )
