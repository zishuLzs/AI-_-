from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ProductSpec:
    risk_level: str
    annual_return: Decimal
    liquidity_note: str
    risk_score: int = 1  # 1-10 scale, higher = more risk


@dataclass(frozen=True)
class AppConfig:
    current_date: date = date(2025, 3, 31)
    inflation_annual: Decimal = Decimal("0.02")
    default_return_annual: Decimal = Decimal("0.02")
    life_expectancy: int = 80
    identity_default: str = "干部"
    pension_raise_after_retirement: bool = False
    return_skewness: Decimal = Decimal("0")
    product_specs: dict[str, ProductSpec] = field(
        default_factory=lambda: {
            "现金理财": ProductSpec("R1", Decimal("0.015"), "灵活申赎", 1),
            "定期存款": ProductSpec("R1", Decimal("0.020"), "5年", 1),
            "短债类产品": ProductSpec("R2", Decimal("0.024"), "2年", 2),
            "固收+产品": ProductSpec("R3", Decimal("0.0425"), "建议持有2年以上", 4),
            "权益类产品": ProductSpec("R4", Decimal("0.060"), "建议持有5年以上", 8),
            "年金险": ProductSpec("R1", Decimal("0.025"), "退休后起领", 2),
        }
    )

    @property
    def monthly_inflation(self) -> Decimal:
        return self.inflation_annual / Decimal("12")

    @property
    def monthly_default_return(self) -> Decimal:
        return self.default_return_annual / Decimal("12")


DEFAULT_CONFIG = AppConfig()
