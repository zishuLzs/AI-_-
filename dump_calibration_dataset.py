from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from config.settings import DEFAULT_CONFIG
from models import CustomerProfile
from tools.allocation_engine import AllocationEngine
from tools.formula_engine import RetirementFormulaEngine
from tools.sql_executor import SQLExecutor
from tools.sql_templates import SQLTemplates


PRODUCTS = [
    "现金理财",
    "定期存款",
    "短债类产品",
    "固收+产品",
    "权益类产品",
    "年金险",
    "其他",
]

ACTION_TYPES = ["购买", "赎回", "浏览详情", "浏览持仓", "收藏"]


def dec_to_str(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return dec_to_str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported type: {type(value)!r}")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: dec_to_str(v) for k, v in row.items()})


def build_profile(row: dict[str, Any]) -> CustomerProfile:
    return CustomerProfile(
        user_id=str(row["User_ID"]),
        age=int(row["Age"]),
        gender=str(row["Gender"]),
        risk_level=str(row["Rsk_Cd"]),
        net_asset=Decimal(str(row["Net_Asset"] or 0)),
        monthly_income=Decimal(str(row["Monthly_Income"] or 0)),
        monthly_expend=Decimal(str(row["Monthly_Expend"] or 0)),
        pension=Decimal(str(row["Pension"] or 0)),
        enterprise_ann=Decimal(str(row["Enterprise_Ann"] or 0)),
    )


def age_bucket(age: int) -> str:
    if age < 30:
        return "<30"
    if age < 40:
        return "30-39"
    if age < 50:
        return "40-49"
    if age < 60:
        return "50-59"
    return "60+"


def extract_profiles(
    sql_executor: SQLExecutor,
    limit: int | None,
    customer_ids: list[str],
) -> list[CustomerProfile]:
    base = sql_executor.base_table
    if customer_ids:
        quoted = ", ".join(f"'{cid}'" for cid in customer_ids)
        sql = f"""
        SELECT User_ID, Age, Gender, Rsk_Cd, Net_Asset,
               Monthly_Income, Monthly_Expend, Pension, Enterprise_Ann
        FROM {base}
        WHERE User_ID IN ({quoted})
        ORDER BY User_ID
        """.strip()
    else:
        limit_sql = f" LIMIT {limit}" if limit is not None else ""
        sql = f"""
        SELECT User_ID, Age, Gender, Rsk_Cd, Net_Asset,
               Monthly_Income, Monthly_Expend, Pension, Enterprise_Ann
        FROM {base}
        ORDER BY User_ID
        {limit_sql}
        """.strip()
    rows = sql_executor.fetch_all(sql)
    return [build_profile(row) for row in rows]


def fetch_behavior_grouped(
    sql_executor: SQLExecutor,
    customer_ids: list[str],
) -> list[dict[str, Any]]:
    action = sql_executor.action_table
    case_expr = SQLTemplates._product_case_expr()
    where_parts = ["prod_typ <> '非财富'"]
    if customer_ids:
        quoted = ", ".join(f"'{cid}'" for cid in customer_ids)
        where_parts.append(f"user_id IN ({quoted})")
    where_sql = " AND ".join(where_parts)
    sql = f"""
    SELECT
        user_id,
        {case_expr} AS mapped_product,
        COUNT(*) AS cnt,
        SUM(CASE WHEN action_typ = '购买' THEN 1 ELSE 0 END) AS buy_cnt,
        SUM(CASE WHEN action_typ = '赎回' THEN 1 ELSE 0 END) AS redeem_cnt,
        SUM(CASE WHEN action_typ = '浏览详情' THEN 1 ELSE 0 END) AS browse_detail_cnt,
        SUM(CASE WHEN action_typ = '浏览持仓' THEN 1 ELSE 0 END) AS browse_holding_cnt,
        SUM(CASE WHEN action_typ = '收藏' THEN 1 ELSE 0 END) AS favorite_cnt
    FROM {action}
    WHERE {where_sql}
    GROUP BY user_id, mapped_product
    ORDER BY user_id, cnt DESC, mapped_product ASC
    """.strip()
    return sql_executor.fetch_all(sql)


def fetch_equity_view_counts(
    sql_executor: SQLExecutor,
    customer_ids: list[str],
) -> dict[str, int]:
    action = sql_executor.action_table
    where_parts = [
        "action_typ IN ('浏览详情', '浏览持仓')",
        "prod_typ = '基金'",
        "rsk_lvl IN ('R4', 'R5')",
    ]
    if customer_ids:
        quoted = ", ".join(f"'{cid}'" for cid in customer_ids)
        where_parts.append(f"user_id IN ({quoted})")
    sql = f"""
    SELECT user_id, COUNT(*) AS equity_view_cnt
    FROM {action}
    WHERE {" AND ".join(where_parts)}
    GROUP BY user_id
    """.strip()
    rows = sql_executor.fetch_all(sql)
    return {str(row["user_id"]): int(row["equity_view_cnt"]) for row in rows}


def summarize_behavior(
    profiles: list[CustomerProfile],
    grouped_rows: list[dict[str, Any]],
    equity_view_counts: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in grouped_rows:
        by_user[str(row["user_id"])].append(row)

    wide_rows: list[dict[str, Any]] = []
    long_rows: list[dict[str, Any]] = []
    behavior_map: dict[str, dict[str, Any]] = {}

    for profile in profiles:
        user_rows = by_user.get(profile.user_id, [])
        counts = {product: 0 for product in PRODUCTS}
        action_totals = {
            "购买": 0,
            "赎回": 0,
            "浏览详情": 0,
            "浏览持仓": 0,
            "收藏": 0,
        }
        for row in user_rows:
            product = str(row["mapped_product"])
            cnt = int(row["cnt"])
            counts[product] = cnt
            action_totals["购买"] += int(row["buy_cnt"] or 0)
            action_totals["赎回"] += int(row["redeem_cnt"] or 0)
            action_totals["浏览详情"] += int(row["browse_detail_cnt"] or 0)
            action_totals["浏览持仓"] += int(row["browse_holding_cnt"] or 0)
            action_totals["收藏"] += int(row["favorite_cnt"] or 0)
            long_rows.append(
                {
                    "user_id": profile.user_id,
                    "mapped_product": product,
                    "count": cnt,
                    "buy_cnt": int(row["buy_cnt"] or 0),
                    "redeem_cnt": int(row["redeem_cnt"] or 0),
                    "browse_detail_cnt": int(row["browse_detail_cnt"] or 0),
                    "browse_holding_cnt": int(row["browse_holding_cnt"] or 0),
                    "favorite_cnt": int(row["favorite_cnt"] or 0),
                }
            )

        top_product = "其他"
        top_product_count = 0
        for product in sorted(PRODUCTS):
            if counts[product] > top_product_count:
                top_product = product
                top_product_count = counts[product]

        wide = {
            "user_id": profile.user_id,
            "top_product": top_product,
            "top_product_count": top_product_count,
            "equity_view_count": equity_view_counts.get(profile.user_id, 0),
            "total_behavior_count": sum(counts.values()),
        }
        for product in PRODUCTS:
            wide[f"cnt_{product}"] = counts[product]
        for action_type in ACTION_TYPES:
            wide[f"action_{action_type}"] = action_totals[action_type]
        wide_rows.append(wide)

        behavior_map[profile.user_id] = {
            "top_product": top_product,
            "counts": counts,
        }

    return wide_rows, long_rows, behavior_map


def retirement_row(
    label: str,
    profile: CustomerProfile,
    result: Any,
) -> dict[str, Any]:
    return {
        "scenario": label,
        "user_id": profile.user_id,
        "age": profile.age,
        "risk_level": profile.risk_level,
        "retirement_age_years": result.retirement_age_years,
        "retirement_age_months": result.retirement_age_months,
        "months_to_retirement": result.months_to_retirement,
        "retirement_duration_text": result.retirement_duration_text,
        "retirement_monthly_expend": result.retirement_monthly_expend,
        "required_asset_at_retirement": result.required_asset_at_retirement,
        "accumulated_asset_at_retirement": result.accumulated_asset_at_retirement,
        "gap": result.gap,
    }


def allocation_text(plan: Any) -> str:
    return "；".join(
        f"{item.product}:{int(item.weight * 100)}%"
        for item in plan.allocation
        if item.weight > 0
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump a rich calibration dataset from the task2 database."
    )
    parser.add_argument(
        "--output-dir",
        default=f"calibration_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Directory for dumped CSV/JSON files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of customers to dump.",
    )
    parser.add_argument(
        "--customer-id",
        action="append",
        default=[],
        help="Repeatable customer ID filter. If provided, only dump these customers.",
    )
    parser.add_argument(
        "--skip-allocation",
        action="store_true",
        help="Skip allocation planning outputs to speed up the dump.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sql_executor = SQLExecutor(SQLExecutor.get_db_config())
    formula = RetirementFormulaEngine(DEFAULT_CONFIG)
    allocator = AllocationEngine(DEFAULT_CONFIG)

    profiles = extract_profiles(sql_executor, args.limit, args.customer_id)
    if not profiles:
        raise SystemExit("No customer rows returned from database.")

    customer_ids = [profile.user_id for profile in profiles]
    behavior_grouped = fetch_behavior_grouped(sql_executor, customer_ids)
    equity_view_counts = fetch_equity_view_counts(sql_executor, customer_ids)
    behavior_wide, behavior_long, behavior_map = summarize_behavior(
        profiles, behavior_grouped, equity_view_counts
    )

    profile_rows = [
        {
            **asdict(profile),
            "monthly_saving": profile.monthly_saving,
            "age_bucket": age_bucket(profile.age),
        }
        for profile in profiles
    ]
    write_csv(output_dir / "customer_profiles.csv", profile_rows)
    write_csv(output_dir / "customer_behavior_summary.csv", behavior_wide)
    write_csv(output_dir / "customer_behavior_long.csv", behavior_long)

    retirement_rows: list[dict[str, Any]] = []
    projection_rows: list[dict[str, Any]] = []
    allocation_rows: list[dict[str, Any]] = []

    top_product_counter: Counter[str] = Counter()
    for wide in behavior_wide:
        top_product_counter[str(wide["top_product"])] += 1

    for idx, profile in enumerate(profiles, start=1):
        print(
            f"[{idx}/{len(profiles)}] processing {profile.user_id}",
            file=sys.stderr,
        )

        scenarios = {
            "default_goal_keep_consumption": (
                {"retirement_goal": "消费水平不下降"},
                {},
            ),
            "inflation_3pct": (
                {"retirement_goal": "消费水平不下降"},
                {"inflation_annual": Decimal("0.03")},
            ),
            "split_10y_to_3pct": (
                {"retirement_goal": "消费水平不下降"},
                {
                    "inflation_annual": Decimal("0.02"),
                    "inflation_after_years": 10,
                    "inflation_after_years_annual": Decimal("0.03"),
                },
            ),
            "extra_saving_1000": (
                {"retirement_goal": "消费水平不下降"},
                {"extra_monthly_saving": Decimal("1000")},
            ),
            "extra_saving_2000": (
                {"retirement_goal": "消费水平不下降"},
                {"extra_monthly_saving": Decimal("2000")},
            ),
            "goal_monthly_12000": (
                {"retirement_goal_monthly_expend": Decimal("12000")},
                {},
            ),
            "goal_monthly_15000": (
                {"retirement_goal_monthly_expend": Decimal("15000")},
                {},
            ),
        }

        default_result = None
        for label, (prefs, scenario) in scenarios.items():
            result = formula.calculate(profile, prefs, scenario)
            if label == "default_goal_keep_consumption":
                default_result = result
            retirement_rows.append(retirement_row(label, profile, result))

        if default_result is None:
            raise RuntimeError("Default retirement result missing.")

        projections = allocator.analyze_product_projections(profile, default_result, {})
        for row in projections:
            projection_rows.append(
                {
                    "user_id": profile.user_id,
                    "risk_level": profile.risk_level,
                    **row,
                }
            )

        if not args.skip_allocation:
            top_product = behavior_map.get(profile.user_id, {}).get("top_product", "其他")
            max_plan = allocator.build_plan(
                profile,
                default_result,
                {"top_product": top_product},
                {},
                {"allocation_objective": "maximize_return"},
            )
            min_plan = allocator.build_plan(
                profile,
                default_result,
                {"top_product": top_product},
                {"allocation_objective": "minimize_risk"},
                {},
            )
            allocation_rows.append(
                {
                    "user_id": profile.user_id,
                    "risk_level": profile.risk_level,
                    "top_product": top_product,
                    "default_gap": default_result.gap,
                    "max_return_plan": allocation_text(max_plan),
                    "max_return_projection": max_plan.retirement_asset_projection,
                    "max_return_covers_gap": max_plan.covers_gap,
                    "min_risk_plan": allocation_text(min_plan),
                    "min_risk_projection": min_plan.retirement_asset_projection,
                    "min_risk_covers_gap": min_plan.covers_gap,
                    "min_risk_portfolio_return": min_plan.portfolio_return,
                    "min_risk_portfolio_risk": min_plan.portfolio_risk,
                }
            )

    write_csv(output_dir / "customer_retirement_metrics.csv", retirement_rows)
    write_csv(output_dir / "customer_product_projections.csv", projection_rows)
    if allocation_rows:
        write_csv(output_dir / "customer_allocation_metrics.csv", allocation_rows)

    aggregate_summary = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "customer_count": len(profiles),
            "db_backend": sql_executor.db_config.get("backend"),
            "base_table": sql_executor.base_table,
            "action_table": sql_executor.action_table,
            "limit": args.limit,
            "customer_ids": args.customer_id,
            "skip_allocation": args.skip_allocation,
        },
        "profile_summary": {
            "gender_counts": Counter(profile.gender for profile in profiles),
            "risk_level_counts": Counter(profile.risk_level for profile in profiles),
            "age_bucket_counts": Counter(age_bucket(profile.age) for profile in profiles),
            "avg_age": round(sum(profile.age for profile in profiles) / len(profiles)),
            "avg_monthly_income": round(
                sum(profile.monthly_income for profile in profiles) / len(profiles)
            ),
            "avg_monthly_expend": round(
                sum(profile.monthly_expend for profile in profiles) / len(profiles)
            ),
            "avg_net_asset": round(
                sum(profile.net_asset for profile in profiles) / len(profiles)
            ),
            "enterprise_ann_positive_count": sum(
                1 for profile in profiles if profile.enterprise_ann > 0
            ),
            "pension_ge_6000_count": sum(
                1 for profile in profiles if profile.pension >= 6000
            ),
        },
        "behavior_summary": {
            "top_product_distribution": top_product_counter,
            "equity_view_ge_2_count": sum(
                1 for profile in profiles if equity_view_counts.get(profile.user_id, 0) >= 2
            ),
            "equity_view_ge_2_avg_age": round(
                sum(
                    profile.age
                    for profile in profiles
                    if equity_view_counts.get(profile.user_id, 0) >= 2
                )
                / max(
                    1,
                    sum(
                        1
                        for profile in profiles
                        if equity_view_counts.get(profile.user_id, 0) >= 2
                    ),
                )
            ),
        },
        "products": {
            product: {
                "annual_return": dec_to_str(spec.annual_return),
                "risk_level": spec.risk_level,
                "risk_score": spec.risk_score,
                "liquidity_note": spec.liquidity_note,
            }
            for product, spec in DEFAULT_CONFIG.product_specs.items()
        },
    }

    (output_dir / "aggregate_summary.json").write_text(
        json.dumps(aggregate_summary, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )

    readme_lines = [
        "# Calibration Dump",
        "",
        f"- Generated at: {aggregate_summary['meta']['generated_at']}",
        f"- Customer count: {aggregate_summary['meta']['customer_count']}",
        f"- Backend: {aggregate_summary['meta']['db_backend']}",
        f"- Base table: {aggregate_summary['meta']['base_table']}",
        f"- Action table: {aggregate_summary['meta']['action_table']}",
        "",
        "## Files",
        "- `customer_profiles.csv`: base_table profiles plus monthly saving and age bucket.",
        "- `customer_behavior_summary.csv`: one row per customer, top product and behavior counts.",
        "- `customer_behavior_long.csv`: one row per customer-product behavior group.",
        "- `customer_retirement_metrics.csv`: per-customer retirement outputs under multiple scenarios.",
        "- `customer_product_projections.csv`: per-customer projected retirement assets by allowed product.",
        "- `customer_allocation_metrics.csv`: max-return and min-risk plan summaries (unless skipped).",
        "- `aggregate_summary.json`: global aggregates useful for expected-value calibration.",
        "",
        "## Notes",
        "- Default retirement scenario uses the long-term goal `消费水平不下降`.",
        "- `goal_monthly_12000` and `goal_monthly_15000` are generic scenario surfaces for QA expansion.",
        "- Allocation output can be relatively slow on larger dumps; use `--skip-allocation` if needed.",
    ]
    (output_dir / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")

    print(f"Dump complete: {output_dir}")


if __name__ == "__main__":
    main()
