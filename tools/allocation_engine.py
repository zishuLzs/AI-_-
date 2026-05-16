"""Asset allocation engine with risk scoring and sparse portfolio search."""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations
import math
from typing import Any

from config.settings import AppConfig
from models import AllocationItem, AllocationPlan, CustomerProfile, RetirementResult
from tools.formula_engine import round_money

# Risk score by product (1-10, higher = riskier)
_PRODUCT_RISK: dict[str, int] = {
    "现金理财": 1,
    "定期存款": 1,
    "短债类产品": 2,
    "固收+产品": 4,
    "权益类产品": 8,
    "年金险": 2,
}

_WEIGHT_CACHE: dict[int, list[list[Decimal]]] = {}


class AllocationEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def build_plan(
        self,
        profile: CustomerProfile,
        retirement_result: RetirementResult,
        behavior_summary: dict[str, Any] | None,
        preferences: dict[str, Any],
        scenario: dict[str, Any] | None = None,
    ) -> AllocationPlan:
        candidates = self._allowed_products(profile.risk_level)
        top_product = (behavior_summary or {}).get("top_product")
        years_to_retirement = retirement_result.months_to_retirement / 12
        extra_saving = Decimal(str((scenario or {}).get("extra_monthly_saving", "0")))
        actual_monthly_saving = profile.monthly_saving + extra_saving
        allocation_objective = str(
            (scenario or {}).get(
                "allocation_objective",
                preferences.get("allocation_objective", ""),
            )
        ).strip()

        if allocation_objective == "maximize_return":
            best_product = max(
                candidates,
                key=lambda product_name: self.config.product_specs[product_name].annual_return,
            )
            spec = self.config.product_specs[best_product]
            projected_asset = self._project_asset(
                profile,
                retirement_result.months_to_retirement,
                spec.annual_return,
                actual_monthly_saving,
            )
            return AllocationPlan(
                allocation=[
                    AllocationItem(
                        product=best_product,
                        weight=Decimal("1"),
                        expected_return=spec.annual_return,
                        risk_score=_PRODUCT_RISK.get(best_product, 1),
                    )
                ],
                portfolio_return=spec.annual_return,
                portfolio_risk=Decimal(_PRODUCT_RISK.get(best_product, 1)),
                retirement_asset_projection=round_money(projected_asset),
                covers_gap=projected_asset >= retirement_result.required_asset_at_retirement,
                reasoning_tags=["收益最大化", "单一主力产品"],
            )

        if allocation_objective == "minimize_risk":
            heuristic_plan = self._build_min_risk_plan(
                profile,
                retirement_result,
                candidates,
                top_product,
                preferences,
                actual_monthly_saving,
            )
            if heuristic_plan is not None:
                return heuristic_plan

        best: AllocationPlan | None = None
        best_risk: Decimal = Decimal("Inf")
        best_shortfall: Decimal | None = None
        best_preference_match = Decimal("-1")

        required_asset = retirement_result.required_asset_at_retirement
        max_non_zero = 3 if required_asset > 0 else min(2, len(candidates))
        candidate_subsets = self._rank_candidate_subsets(
            candidates, top_product, preferences, years_to_retirement, max_non_zero
        )
        for subset in candidate_subsets:
            subset_size = len(subset)
            for weights in self._generate_sparse_weights(subset_size):
                allocation = []
                portfolio_return = Decimal("0")
                portfolio_risk = Decimal("0")

                for product_name, weight in zip(subset, weights, strict=True):
                    spec = self.config.product_specs[product_name]
                    risk_score = _PRODUCT_RISK.get(product_name, 1)
                    allocation.append(
                        AllocationItem(product_name, weight, spec.annual_return, risk_score)
                    )
                    portfolio_return += weight * spec.annual_return
                    portfolio_risk += weight * Decimal(risk_score)

                projected_asset = self._project_asset(
                    profile, retirement_result.months_to_retirement,
                    portfolio_return, actual_monthly_saving,
                )
                shortfall = (
                    retirement_result.required_asset_at_retirement - projected_asset
                )
                covers_gap = shortfall <= 0
                preference_match = self._preference_match_score(
                    allocation, top_product, preferences, years_to_retirement
                )
                tags = self._build_tags(
                    allocation, top_product, preferences, years_to_retirement
                )

                plan = AllocationPlan(
                    allocation=allocation,
                    portfolio_return=portfolio_return,
                    portfolio_risk=portfolio_risk,
                    retirement_asset_projection=round_money(projected_asset),
                    covers_gap=covers_gap,
                    reasoning_tags=tags,
                )

                if covers_gap:
                    objective_prefers_return = allocation_objective == "maximize_return"
                    objective_prefers_risk = allocation_objective == "minimize_risk"
                    if (
                        best is None
                        or not best.covers_gap
                        or (
                            objective_prefers_return
                            and portfolio_return > best.portfolio_return
                        )
                        or (
                            objective_prefers_return
                            and portfolio_return == best.portfolio_return
                            and portfolio_risk < best_risk
                        )
                        or (
                            not objective_prefers_return
                            and portfolio_risk < best_risk
                        )
                        or (
                            portfolio_risk == best_risk
                            and preference_match > best_preference_match
                        )
                        or (
                            portfolio_risk == best_risk
                            and preference_match == best_preference_match
                            and projected_asset < best.retirement_asset_projection
                        )
                    ):
                        best = plan
                        best_risk = portfolio_risk
                        best_preference_match = preference_match
                else:
                    if best is None or (
                        not best.covers_gap
                        and (
                            best_shortfall is None
                            or shortfall < best_shortfall
                            or (
                                shortfall == best_shortfall
                                and portfolio_risk < best_risk
                            )
                        )
                    ):
                        best = plan
                        best_shortfall = shortfall
                        best_risk = portfolio_risk
                        best_preference_match = preference_match

        if best is None:
            raise RuntimeError("No allocation plan generated.")
        return best

    def analyze_product_projections(
        self,
        profile: CustomerProfile,
        retirement_result: RetirementResult,
        scenario: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        extra_saving = Decimal(str((scenario or {}).get("extra_monthly_saving", "0")))
        actual_monthly_saving = profile.monthly_saving + extra_saving
        result: list[dict[str, Any]] = []
        for product in self._allowed_products(profile.risk_level):
            spec = self.config.product_specs[product]
            projected_asset = self._project_asset(
                profile,
                retirement_result.months_to_retirement,
                spec.annual_return,
                actual_monthly_saving,
            )
            result.append(
                {
                    "product": product,
                    "annual_return": str(spec.annual_return),
                    "retirement_asset_projection": str(round_money(projected_asset)),
                    "covers_gap": projected_asset
                    >= retirement_result.required_asset_at_retirement,
                    "risk_score": _PRODUCT_RISK.get(product, 1),
                }
            )
        return result

    def _allowed_products(self, risk_level: str) -> list[str]:
        if risk_level == "R1":
            return ["现金理财", "定期存款", "年金险"]
        if risk_level == "R2":
            return ["现金理财", "定期存款", "短债类产品", "年金险"]
        if risk_level == "R3":
            return ["现金理财", "定期存款", "短债类产品", "固收+产品", "年金险"]
        return [
            "现金理财",
            "定期存款",
            "短债类产品",
            "固收+产品",
            "权益类产品",
            "年金险",
        ]

    def _build_min_risk_plan(
        self,
        profile: CustomerProfile,
        retirement_result: RetirementResult,
        candidates: list[str],
        top_product: object,
        preferences: dict[str, Any],
        actual_monthly_saving: Decimal,
    ) -> AllocationPlan | None:
        required_asset = retirement_result.required_asset_at_retirement
        if required_asset <= 0:
            return None

        eligible: list[tuple[str, Decimal, Decimal]] = []
        for product in candidates:
            annual_return = self.config.product_specs[product].annual_return
            projected_asset = self._project_asset(
                profile,
                retirement_result.months_to_retirement,
                annual_return,
                actual_monthly_saving,
            )
            if projected_asset >= required_asset:
                eligible.append((product, annual_return, projected_asset))

        if not eligible:
            return None

        primary_product, primary_return, primary_projection = min(
            eligible,
            key=lambda item: (
                item[1],
                _PRODUCT_RISK.get(item[0], 99),
                item[0],
            ),
        )

        primary_ratio = (required_asset / primary_projection) * Decimal("100")
        primary_weight = Decimal(math.ceil(float(primary_ratio))) / Decimal("100")
        primary_weight = min(primary_weight, Decimal("1"))
        remainder = Decimal("1") - primary_weight

        weight_map: dict[str, Decimal] = {primary_product: primary_weight}

        if remainder > 0 and "现金理财" in candidates and primary_product != "现金理财":
            cash_weight = min(Decimal("0.10"), remainder)
            if cash_weight > 0:
                weight_map["现金理财"] = cash_weight
                remainder -= cash_weight

        if remainder > 0 and "年金险" in candidates and primary_product != "年金险":
            weight_map["年金险"] = weight_map.get("年金险", Decimal("0")) + remainder
            remainder = Decimal("0")

        if remainder > 0:
            for product in candidates:
                if product == primary_product:
                    continue
                weight_map[product] = weight_map.get(product, Decimal("0")) + remainder
                break

        ordered_products: list[str] = []
        for product in (
            primary_product,
            "现金理财",
            "年金险",
            "定期存款",
            "短债类产品",
            "固收+产品",
            "权益类产品",
        ):
            if product not in ordered_products:
                ordered_products.append(product)
        allocation: list[AllocationItem] = []
        portfolio_return = Decimal("0")
        portfolio_risk = Decimal("0")
        for product in ordered_products:
            weight = weight_map.get(product, Decimal("0"))
            if weight <= 0:
                continue
            spec = self.config.product_specs[product]
            risk_score = _PRODUCT_RISK.get(product, 1)
            allocation.append(
                AllocationItem(
                    product=product,
                    weight=weight,
                    expected_return=spec.annual_return,
                    risk_score=risk_score,
                )
            )
            portfolio_return += weight * spec.annual_return
            portfolio_risk += weight * Decimal(risk_score)

        tags = ["最小化风险波动", "主力产品覆盖养老需求"]
        if top_product == "现金理财" and "现金理财" in weight_map:
            tags.append("偏好匹配")
        if "现金理财" in weight_map:
            tags.append("兼顾流动性")
        if "年金险" in weight_map:
            tags.append("对冲长寿风险")
        if preferences.get("focus_points"):
            tags.append("关注点已覆盖")

        return AllocationPlan(
            allocation=allocation,
            portfolio_return=portfolio_return,
            portfolio_risk=portfolio_risk,
            retirement_asset_projection=round_money(primary_projection * primary_weight),
            covers_gap=(primary_projection * primary_weight) >= required_asset,
            reasoning_tags=tags,
        )

    def _rank_candidate_subsets(
        self,
        candidates: list[str],
        top_product: object,
        preferences: dict[str, Any],
        years_to_retirement: float,
        max_non_zero: int,
    ) -> list[tuple[str, ...]]:
        scored: list[tuple[Decimal, tuple[str, ...]]] = []
        for subset_size in range(1, max_non_zero + 1):
            for subset in combinations(candidates, subset_size):
                score = Decimal("0")
                if top_product in subset:
                    score += Decimal("5")
                focus = preferences.get("focus_points", [])
                if "流动性" in focus and any(
                    product in subset for product in ("现金理财", "短债类产品")
                ):
                    score += Decimal("2")
                if "长寿风险" in focus and "年金险" in subset:
                    score += Decimal("2")
                if years_to_retirement > 15 and "权益类产品" in subset:
                    score += Decimal("1")
                score -= Decimal("0.1") * Decimal(len(subset))
                scored.append((score, subset))
        scored.sort(key=lambda item: (item[0], -len(item[1])), reverse=True)
        return [subset for _, subset in scored[:12]]

    def _generate_sparse_weights(self, product_count: int) -> list[list[Decimal]]:
        if product_count in _WEIGHT_CACHE:
            return _WEIGHT_CACHE[product_count]

        slots = 100
        combinations_list: list[list[Decimal]] = []
        if product_count == 1:
            combinations_list.append([Decimal("1")])
        elif product_count == 2:
            for first in range(1, slots):
                second = slots - first
                combinations_list.append(
                    [Decimal(first) / Decimal(slots), Decimal(second) / Decimal(slots)]
                )
        else:
            for first in range(1, slots - 1):
                for second in range(1, slots - first):
                    third = slots - first - second
                    combinations_list.append(
                        [
                            Decimal(first) / Decimal(slots),
                            Decimal(second) / Decimal(slots),
                            Decimal(third) / Decimal(slots),
                        ]
                    )
        _WEIGHT_CACHE[product_count] = combinations_list
        return combinations_list

    def _project_asset(
        self,
        profile: CustomerProfile,
        months_to_retirement: int,
        annual_return: Decimal,
        monthly_saving: Decimal,
    ) -> Decimal:
        monthly_rate = annual_return / Decimal("12")
        growth = (Decimal("1") + monthly_rate) ** months_to_retirement
        if monthly_rate == 0:
            return profile.net_asset + monthly_saving * Decimal(months_to_retirement)
        net_asset_fv = profile.net_asset * growth
        saving_fv = monthly_saving * ((growth - Decimal("1")) / monthly_rate)
        return net_asset_fv + saving_fv

    @staticmethod
    def _preference_match_score(
        allocation: list[AllocationItem],
        top_product: object,
        preferences: dict[str, Any],
        years_to_retirement: float,
    ) -> Decimal:
        score = Decimal("0")
        weight_map = {item.product: item.weight for item in allocation}
        if top_product in weight_map:
            score += weight_map[top_product] * Decimal("5")
        focus = preferences.get("focus_points", [])
        if "流动性" in focus:
            score += (
                weight_map.get("现金理财", Decimal("0"))
                + weight_map.get("短债类产品", Decimal("0"))
            ) * Decimal("2")
        if "长寿风险" in focus:
            score += weight_map.get("年金险", Decimal("0")) * Decimal("2")
        if years_to_retirement > 15:
            score += weight_map.get("权益类产品", Decimal("0"))
        return score

    @staticmethod
    def _build_tags(
        allocation: list[AllocationItem],
        top_product: object,
        preferences: dict[str, Any],
        years_to_retirement: float,
    ) -> list[str]:
        tags = ["风险可接受", "覆盖长期养老目标"]
        if top_product and any(
            item.product == top_product and item.weight > 0 for item in allocation
        ):
            tags.append("偏好匹配")
        focus = preferences.get("focus_points", [])
        if "流动性" in focus:
            tags.append("兼顾流动性")
        if "长寿风险" in focus:
            tags.append("覆盖长寿风险")
        if any(item.product == "年金险" and item.weight > 0 for item in allocation):
            tags.append("长寿风险对冲")
        if years_to_retirement > 15:
            tags.append("长线投资")
        return tags
