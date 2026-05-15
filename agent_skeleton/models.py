from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class CustomerProfile:
    user_id: str
    age: int
    gender: str
    risk_level: str
    net_asset: Decimal
    monthly_income: Decimal
    monthly_expend: Decimal
    pension: Decimal
    enterprise_ann: Decimal

    @property
    def monthly_saving(self) -> Decimal:
        return self.monthly_income - self.monthly_expend


@dataclass
class SessionState:
    session_id: str
    customer_id: str | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    focus_points: list[str] = field(default_factory=list)
    scenario: dict[str, Any] = field(default_factory=dict)


@dataclass
class AllocationItem:
    product: str
    weight: Decimal
    expected_return: Decimal
    risk_score: int = 1


@dataclass
class AllocationPlan:
    allocation: list[AllocationItem]
    portfolio_return: Decimal
    portfolio_risk: Decimal
    retirement_asset_projection: Decimal
    covers_gap: bool
    reasoning_tags: list[str]


@dataclass
class RetirementResult:
    retirement_age_years: int
    retirement_age_months: int
    months_to_retirement: int
    retirement_duration_text: str
    retirement_monthly_expend: Decimal
    required_asset_at_retirement: Decimal
    accumulated_asset_at_retirement: Decimal
    gap: Decimal
