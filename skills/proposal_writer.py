"""Proposal writer skill — generates comprehensive retirement planning proposals."""

from __future__ import annotations

from typing import Any

from models import SessionState
from tools.memory_manager import MemoryManager

from skills.allocation_planning import AllocationPlanningSkill
from skills.behavior_analysis import BehaviorAnalysisSkill
from skills.customer_profile import CustomerProfileSkill
from skills.retirement_calc import RetirementCalculationSkill


class ProposalWriterSkill:
    def __init__(
        self,
        profile_skill: CustomerProfileSkill,
        behavior_skill: BehaviorAnalysisSkill,
        retirement_skill: RetirementCalculationSkill,
        allocation_skill: AllocationPlanningSkill,
        memory_manager: MemoryManager,
    ) -> None:
        self.profile_skill = profile_skill
        self.behavior_skill = behavior_skill
        self.retirement_skill = retirement_skill
        self.allocation_skill = allocation_skill
        self.memory_manager = memory_manager

    def write(self, session_id: str, customer_id: str) -> str:
        state = self.memory_manager.get_session(session_id)
        profile = self.profile_skill.get_profile(session_id, customer_id)
        behavior = self.behavior_skill.analyze(customer_id)
        retirement = self.retirement_skill.calculate(session_id, customer_id)
        plan = self.allocation_skill.plan(session_id, customer_id)

        # Gather context from session
        focus_points = (
            "、".join(state.focus_points)
            if state.focus_points
            else "稳健增值与退休保障"
        )
        retirement_goal = state.preferences.get(
            "retirement_goal", "退休后养老支出可持续"
        )

        # Build allocation lines with rationale
        allocation_lines = []
        ordered_items = sorted(
            (item for item in plan.allocation if item.weight > 0),
            key=lambda item: item.weight,
            reverse=True,
        )
        for item in ordered_items:
            weight_pct = int(item.weight * 100)
            expected_pct = f"{item.expected_return * 100:.2f}"
            rationale = self._product_rationale(
                item.product, state.preferences, behavior
            )
            allocation_lines.append(
                f"- 将 {weight_pct}% 配置于 {item.product}（年化 {expected_pct}%），{rationale}"
            )
        allocation_text = "\n".join(allocation_lines)

        # Determine overall assessment
        gap_val = int(retirement.gap)
        if gap_val <= 0:
            overall_assessment = "较好，在默认假设下已无资金缺口"
            gap_result_text = "能够覆盖养老金缺口"
            core_strategy = "稳健积累 + 长期养老保障"
        else:
            overall_assessment = "仍有提升空间，当前测算存在资金缺口"
            gap_result_text = f"仍需通过提升储蓄或优化目标继续补足约 {gap_val} 元缺口"
            core_strategy = "适度提升储蓄 + 优化资产配置 + 延长积累期"

        # Behavior detail
        top_product = (
            behavior.get("top_product", "其他")
            if isinstance(behavior, dict)
            else "其他"
        )
        counts = behavior.get("counts", {}) if isinstance(behavior, dict) else {}
        top_count = counts.get(top_product, 0)
        insight = behavior.get("insight", "") if isinstance(behavior, dict) else ""

        # Assumption section
        assumptions = self._build_assumptions(state)

        return f"""# 客户 {customer_id} 养老规划建议书

## 一、客户概况
客户 {customer_id}，{profile.age} 岁，{profile.gender}，当前风险评级为 {profile.risk_level}。目前净资产约 {int(profile.net_asset)} 元，月收入 {int(profile.monthly_income)} 元，月支出 {int(profile.monthly_expend)} 元，月结余约 {int(profile.monthly_saving)} 元。社保养老金预计每月 {int(profile.pension)} 元，企业年金预计 {int(profile.enterprise_ann)} 元。

## 二、基本假设
{assumptions}

## 三、养老目标与核心关注点
结合前序沟通，客户当前的主要养老目标为：{retirement_goal}。当前重点关注：{focus_points}。

## 四、退休后财富需求测算
按题目默认假设，客户距离退休还有 {retirement.retirement_duration_text}。若保持当前消费能力，退休首月预计支出约 {int(retirement.retirement_monthly_expend)} 元。综合退休支出、社保养老金和企业年金测算，客户退休时最低需积攒 {int(retirement.required_asset_at_retirement)} 元，预计可积攒 {int(retirement.accumulated_asset_at_retirement)} 元，养老金缺口约为 {int(retirement.gap)} 元。

## 五、产品偏好分析
根据客户历史行为记录，客户对 {top_product} 相关行为最多（共 {top_count} 次），{insight}

## 六、资产配置方式与具体方案
{allocation_text}

在当前假设下，该组合预计年化收益率约为 {plan.portfolio_return * 100:.2f}%，退休时预计积累 {int(plan.retirement_asset_projection)} 元，{gap_result_text}。整体方案以风险等级匹配为前提，优先兼顾客户已表达的偏好与关注点。

## 七、其他建议
- 客户目前 {profile.age} 岁，距退休长达 {retirement.retirement_duration_text}，复利效应显著，建议尽早开始投资积累。
- 建议每年或在收入、支出、家庭结构、风险偏好发生明显变化时，重新检视养老规划方案。
- 若后续出现市场波动、退休目标调整或对流动性的要求上升，应同步调整资产配置结构。
- {self._lifecycle_advice(profile.age, retirement.months_to_retirement)}

## 八、综合结论
总体来看，客户当前养老规划基础 {overall_assessment}，建议以"{core_strategy}"为主线持续推进，并结合客户既有偏好和实际现金流情况逐步优化退休储备。
"""

    def _product_rationale(self, product: str, preferences: dict, behavior: Any) -> str:
        """Generate rationale for a specific product allocation."""
        rationales = {
            "现金理财": "用于应对意外事件的流动性储备，确保客户在突发情况下有充足资金周转",
            "定期存款": "提供稳定的本金保障和固定收益，适合作为养老储备的安全底仓",
            "短债类产品": "在低波动前提下提供略高于存款的收益，兼顾安全性与收益性",
            "固收+产品": "通过固收打底、权益增强的策略，追求稳健增值与适度收益弹性",
            "权益类产品": "长期持有可获取较高收益空间，通过时间平滑短期波动，适合长期积累",
            "年金险": "用于对冲长寿风险，退休后可领取终身年金，确保养老现金流不中断",
        }
        focus = preferences.get("focus_points", [])
        base_rationale = rationales.get(product, "作为资产配置的重要组成部分")

        # Reference behavior data if this is the customer's top product
        top_product = (
            behavior.get("top_product") if isinstance(behavior, dict) else None
        )
        counts = behavior.get("counts", {}) if isinstance(behavior, dict) else {}
        if top_product and product == top_product:
            count = counts.get(top_product, 0)
            if count > 0:
                base_rationale += (
                    f"，客户历史对该类产品关注度最高（{count} 次相关行为）"
                )

        if "流动性" in focus and product in ("现金理财", "短债类产品"):
            return base_rationale + "，同时兼顾客户对流动性的关注"
        if "长寿风险" in focus and product == "年金险":
            return base_rationale + "，特别匹配客户对长寿风险的关注"
        return base_rationale

    def _build_assumptions(self, state: SessionState) -> str:
        """Build assumptions section, clearly separating defaults, preferences, and scenarios."""
        lines = [
            "**系统默认假设：**",
            "- 未来通胀率预测值：年化 2%，按月调整",
            "- 默认投资回报率：年化 2%（全部投资定期理财），按月复利",
            "- 默认预期寿命：80 岁",
            "- 当前日期：2025 年 3 月 31 日，假设所有客户均为当天生日",
            '- 计算退休年龄时身份默认为"干部"，并按照现行延迟退休政策退休',
        ]

        # Customer long-term preferences
        if state.preferences:
            pref_lines = []
            if "retirement_goal" in state.preferences:
                pref_lines.append(f"- 养老目标：{state.preferences['retirement_goal']}")
            if "retirement_goal_monthly_expend" in state.preferences:
                pref_lines.append(
                    f"- 退休后月支出目标：{int(state.preferences['retirement_goal_monthly_expend'])} 元"
                )
            if "risk_preference_text" in state.preferences:
                pref_lines.append(
                    f"- 风险偏好：{state.preferences['risk_preference_text']}"
                )
            if pref_lines:
                lines.append("")
                lines.append("**客户长期观点（已确认，后续问题继承）：**")
                lines.extend(pref_lines)

        # Temporary hypothetical scenarios
        if state.scenario:
            scenario_lines = []
            if "inflation_annual" in state.scenario:
                scenario_lines.append(
                    f"- 假设通胀率：{float(state.scenario['inflation_annual']) * 100:.1f}%"
                )
            if "extra_monthly_saving" in state.scenario:
                scenario_lines.append(
                    f"- 假设每月额外储蓄：{int(state.scenario['extra_monthly_saving'])} 元"
                )
            if "retirement_goal_monthly_expend" in state.scenario:
                scenario_lines.append(
                    f"- 假设退休后月支出：{int(state.scenario['retirement_goal_monthly_expend'])} 元"
                )
            if scenario_lines:
                lines.append("")
                lines.append("**本轮临时假设（仅本次测算生效）：**")
                lines.extend(scenario_lines)

        return "\n".join(lines)

    def _lifecycle_advice(self, age: int, months_to_retirement: int) -> str:
        """Generate lifecycle-specific advice."""
        years_to_retirement = months_to_retirement / 12
        if years_to_retirement > 30:
            return "客户距离退休时间较长，可适度配置长期资产以获取更高收益，但需注意定期再平衡。"
        if years_to_retirement > 15:
            return "客户处于事业上升期，建议在风险可控前提下逐步积累养老储备。"
        if years_to_retirement > 5:
            return "客户临近退休，建议逐步降低高波动资产比例，增加稳健型产品配置。"
        return "客户即将退休，建议以保本和流动性为首要目标，确保退休生活平稳过渡。"
