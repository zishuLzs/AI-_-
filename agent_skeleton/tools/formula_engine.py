from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP, getcontext
import math

from config.settings import AppConfig
from models import CustomerProfile, RetirementResult


getcontext().prec = 28


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def round_percent(value: Decimal) -> Decimal:
    return (value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class RetirementFormulaEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def calculate(
        self,
        profile: CustomerProfile,
        preferences: dict[str, object],
        scenario: dict[str, object],
    ) -> RetirementResult:
        retirement_age_years, retirement_age_months = self.calculate_retirement_age(
            profile.gender,
            profile.age,
        )
        months_to_retirement = (
            retirement_age_years - profile.age
        ) * 12 + retirement_age_months
        inflation_annual = Decimal(
            str(scenario.get("inflation_annual", self.config.inflation_annual))
        )
        monthly_inflation = inflation_annual / Decimal("12")

        if "retirement_goal_monthly_expend" in scenario:
            retirement_monthly_expend = Decimal(
                str(scenario["retirement_goal_monthly_expend"])
            )
        elif "retirement_goal_monthly_expend" in preferences:
            retirement_monthly_expend = Decimal(
                str(preferences["retirement_goal_monthly_expend"])
            )
        else:
            retirement_monthly_expend = profile.monthly_expend * (
                (Decimal("1") + monthly_inflation) ** months_to_retirement
            )

        retirement_age_decimal = Decimal(retirement_age_years) + (
            Decimal(retirement_age_months) / Decimal("12")
        )
        retirement_months = max(
            int(
                (Decimal(self.config.life_expectancy) - retirement_age_decimal)
                * Decimal("12")
            ),
            0,
        )

        # Required asset: PV of expenses - PV of pension - enterprise annuity
        # Using nominal rates (when r=i, real rate=0, PV = nominal sum)
        nominal_discount = self.config.monthly_default_return
        monthly_pension = profile.pension
        pension_pv = self.present_value_annuity(
            monthly_pension, nominal_discount, retirement_months
        )

        # PV of retirement expenses using real discount rate
        real_monthly_rate = self._real_monthly_rate(
            self.config.default_return_annual,
            inflation_annual,
        )
        if real_monthly_rate == 0:
            pv_expenses = retirement_monthly_expend * Decimal(retirement_months)
        else:
            pv_expenses = retirement_monthly_expend * self.present_value_annuity_factor(
                real_monthly_rate,
                retirement_months,
            )

        required_asset = max(
            pv_expenses - pension_pv - profile.enterprise_ann, Decimal("0")
        )

        # Accumulated asset at retirement
        monthly_return = self.config.monthly_default_return
        extra_monthly_saving = Decimal(str(scenario.get("extra_monthly_saving", "0")))
        monthly_saving = profile.monthly_saving + extra_monthly_saving
        accumulated_asset = self.future_value(
            profile.net_asset, monthly_return, months_to_retirement
        )
        accumulated_asset += self.future_value_annuity(
            monthly_saving,
            monthly_return,
            months_to_retirement,
        )
        gap = required_asset - accumulated_asset

        return RetirementResult(
            retirement_age_years=retirement_age_years,
            retirement_age_months=retirement_age_months,
            months_to_retirement=months_to_retirement,
            retirement_duration_text=self.duration_text(months_to_retirement),
            retirement_monthly_expend=round_money(retirement_monthly_expend),
            required_asset_at_retirement=round_money(required_asset),
            accumulated_asset_at_retirement=round_money(accumulated_asset),
            gap=round_money(gap),
        )

    @staticmethod
    def _real_monthly_rate(
        annual_return: Decimal, annual_inflation: Decimal
    ) -> Decimal:
        """Calculate real monthly rate: (1+r/12)/(1+i/12) - 1."""
        r_monthly = annual_return / Decimal("12")
        i_monthly = annual_inflation / Decimal("12")
        return (Decimal("1") + r_monthly) / (Decimal("1") + i_monthly) - Decimal("1")

    @staticmethod
    def present_value_annuity_factor(monthly_rate: Decimal, periods: int) -> Decimal:
        """PV factor for annuity: (1 - (1+r)^-n) / r."""
        if periods <= 0:
            return Decimal("0")
        if monthly_rate == 0:
            return Decimal(periods)
        ratio = Decimal("1") / (Decimal("1") + monthly_rate)
        return (Decimal("1") - (ratio**periods)) / monthly_rate

    def calculate_retirement_age(
        self, gender: str, current_age: int
    ) -> tuple[int, int]:
        base_age = 60 if gender == "男" else 55
        birth_year = self.config.current_date.year - current_age
        original_retirement_date = date(
            birth_year + base_age,
            self.config.current_date.month,
            self.config.current_date.day,
        )
        # Delay retirement policy: from policy start (2025-01-01) to original
        # retirement date, every 4 months delays 1 month, max 36 months
        policy_start = date(2025, 1, 1)
        months_from_policy = max(
            self.months_between(policy_start, original_retirement_date), 0
        )
        max_delay_months = 36
        delay_months = min(max_delay_months, math.ceil(months_from_policy / 4))
        years = base_age + delay_months // 12
        months = delay_months % 12
        return years, months

    @staticmethod
    def months_between(start_date: date, end_date: date) -> int:
        return (end_date.year - start_date.year) * 12 + (
            end_date.month - start_date.month
        )

    @staticmethod
    def duration_text(months: int) -> str:
        years = months // 12
        remain_months = months % 12
        return f"{years}年{remain_months}个月"

    @staticmethod
    def future_value(
        principal: Decimal, monthly_rate: Decimal, periods: int
    ) -> Decimal:
        if periods <= 0:
            return principal
        return principal * ((Decimal("1") + monthly_rate) ** periods)

    @staticmethod
    def future_value_annuity(
        payment: Decimal, monthly_rate: Decimal, periods: int
    ) -> Decimal:
        if periods <= 0:
            return Decimal("0")
        if monthly_rate == 0:
            return payment * Decimal(periods)
        growth = (Decimal("1") + monthly_rate) ** periods
        return payment * ((growth - Decimal("1")) / monthly_rate)

    @staticmethod
    def present_value_annuity(
        payment: Decimal, monthly_rate: Decimal, periods: int
    ) -> Decimal:
        """Present value: Σ(1/(1+r)^k, k=0..periods-1).

        Computes annuity-due (first payment at t=0), matching the spec's
        Σ(k=0..n-1) convention. When r=i (real rate=0), simplifies to nominal sum.
        """
        if periods <= 0:
            return Decimal("0")
        if monthly_rate == 0:
            return payment * Decimal(periods)
        ratio = Decimal("1") / (Decimal("1") + monthly_rate)
        return payment * ((Decimal("1") - (ratio**periods)) / (Decimal("1") - ratio))
