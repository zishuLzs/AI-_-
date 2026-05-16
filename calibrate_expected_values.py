from __future__ import annotations

from decimal import Decimal

from config.settings import DEFAULT_CONFIG
from models import CustomerProfile
from predicted_eval_cases import all_single_turn_cases
from tools.allocation_engine import AllocationEngine
from tools.formula_engine import RetirementFormulaEngine
from tools.sql_executor import SQLExecutor
from tools.sql_templates import SQLTemplates


def fmt_money(value: Decimal | int | float | str) -> str:
    dec = Decimal(str(value))
    if dec == dec.quantize(Decimal("1")):
        return f"{int(dec)} 元"
    return f"{dec} 元"


def fmt_count(value: int) -> str:
    return f"{value} 个"


def fmt_duration(text: str) -> str:
    if "年" in text and "个月" in text and " " not in text:
        years, months = text.split("年")
        months = months.replace("个月", "")
        return f"{years} 年 {months} 个月"
    return text


def build_profile(sql_executor: SQLExecutor, customer_id: str) -> CustomerProfile:
    sql, params = SQLTemplates.select_profile(customer_id, sql_executor.base_table)
    row = sql_executor.fetch_one(sql, params)
    if not row:
        raise ValueError(f"Missing profile: {customer_id}")
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


def fetch_top_product(sql_executor: SQLExecutor, customer_id: str) -> str:
    sql, params = SQLTemplates.top_preference_product(
        customer_id, sql_executor.action_table
    )
    row = sql_executor.fetch_one(sql, params)
    return str(row["mapped_product"]) if row else "其他"


def fetch_equity_view_stats(sql_executor: SQLExecutor) -> tuple[int, int]:
    action = sql_executor.action_table
    base = sql_executor.base_table
    count_sql = f"""
    WITH T AS (
        SELECT user_id, COUNT(*) AS view_cnt
        FROM {action}
        WHERE action_typ IN ('浏览详情', '浏览持仓')
          AND prod_typ = '基金'
          AND rsk_lvl IN ('R4', 'R5')
        GROUP BY user_id
        HAVING view_cnt >= 2
    )
    SELECT COUNT(*) AS cnt, ROUND(AVG(b.Age), 6) AS avg_age
    FROM T INNER JOIN {base} b ON b.User_ID = T.user_id
    """.strip()
    row = sql_executor.fetch_one(count_sql)
    return int(row["cnt"]), round(float(row["avg_age"]))


def count_where(sql_executor: SQLExecutor, condition_sql: str) -> int:
    sql = SQLTemplates.count_by_condition(condition_sql, sql_executor.base_table)
    row = sql_executor.fetch_one(sql)
    return int(row["cnt"])


def avg_where(sql_executor: SQLExecutor, field_name: str, condition_sql: str) -> int:
    sql = SQLTemplates.avg_by_condition(field_name, condition_sql, sql_executor.base_table)
    row = sql_executor.fetch_one(sql)
    return round(float(row["avg_value"]))


def main() -> None:
    sql_executor = SQLExecutor(SQLExecutor.get_db_config())
    formula = RetirementFormulaEngine(DEFAULT_CONFIG)
    allocator = AllocationEngine(DEFAULT_CONFIG)

    profiles = {
        cid: build_profile(sql_executor, cid)
        for cid in ("V500001", "V500002", "V500003")
    }
    top_v500001 = fetch_top_product(sql_executor, "V500001")
    equity_cnt, equity_avg_age = fetch_equity_view_stats(sql_executor)

    risk_rank = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}

    def retirement(profile: CustomerProfile, prefs: dict, scen: dict):
        return formula.calculate(profile, prefs, scen)

    # Default retirement results
    r1 = retirement(profiles["V500001"], {"retirement_goal": "消费水平不下降"}, {})
    r2 = retirement(profiles["V500002"], {"retirement_goal": "消费水平不下降"}, {})
    r3 = retirement(profiles["V500003"], {"retirement_goal": "消费水平不下降"}, {})

    # Scenario results
    r1_infl3 = retirement(
        profiles["V500001"],
        {"retirement_goal": "消费水平不下降"},
        {"inflation_annual": Decimal("0.03")},
    )
    r2_split = retirement(
        profiles["V500002"],
        {"retirement_goal": "消费水平不下降"},
        {
            "inflation_annual": Decimal("0.02"),
            "inflation_after_years": 10,
            "inflation_after_years_annual": Decimal("0.03"),
        },
    )
    r3_split = retirement(
        profiles["V500003"],
        {"retirement_goal": "消费水平不下降"},
        {
            "inflation_annual": Decimal("0.02"),
            "inflation_after_years": 10,
            "inflation_after_years_annual": Decimal("0.03"),
        },
    )
    r1_extra2k = retirement(
        profiles["V500001"],
        {"retirement_goal": "消费水平不下降"},
        {"extra_monthly_saving": Decimal("2000")},
    )
    r1_goal12k = retirement(
        profiles["V500001"],
        {"retirement_goal_monthly_expend": Decimal("12000")},
        {},
    )
    r1_goal12k_extra2k = retirement(
        profiles["V500001"],
        {"retirement_goal_monthly_expend": Decimal("12000")},
        {"extra_monthly_saving": Decimal("2000")},
    )
    r1_goal12k_infl3 = retirement(
        profiles["V500001"],
        {"retirement_goal_monthly_expend": Decimal("12000")},
        {"inflation_annual": Decimal("0.03")},
    )
    r2_goal15k = retirement(
        profiles["V500002"],
        {"retirement_goal_monthly_expend": Decimal("15000")},
        {},
    )
    r2_goal15k_infl3 = retirement(
        profiles["V500002"],
        {"retirement_goal_monthly_expend": Decimal("15000")},
        {"inflation_annual": Decimal("0.03")},
    )
    r2_extra1k = retirement(
        profiles["V500002"],
        {"retirement_goal": "消费水平不下降"},
        {"extra_monthly_saving": Decimal("1000")},
    )
    r3_infl3 = retirement(
        profiles["V500003"],
        {"retirement_goal": "消费水平不下降"},
        {"inflation_annual": Decimal("0.03")},
    )
    r3_extra2k = retirement(
        profiles["V500003"],
        {"retirement_goal": "消费水平不下降"},
        {"extra_monthly_saving": Decimal("2000")},
    )

    # Allocation results
    plan_v500001_max = allocator.build_plan(
        profiles["V500001"], r1, {"top_product": top_v500001}, {}, {"allocation_objective": "maximize_return"}
    )
    plan_v500001_min = allocator.build_plan(
        profiles["V500001"], r1, {"top_product": top_v500001}, {"allocation_objective": "minimize_risk"}, {}
    )
    plan_v500002_max = allocator.build_plan(
        profiles["V500002"], r2, {"top_product": top_v500001}, {}, {"allocation_objective": "maximize_return"}
    )
    plan_v500002_min = allocator.build_plan(
        profiles["V500002"], r2, {"top_product": top_v500001}, {"allocation_objective": "minimize_risk"}, {}
    )
    plan_v500003_max = allocator.build_plan(
        profiles["V500003"], r3, {"top_product": top_v500001}, {}, {"allocation_objective": "maximize_return"}
    )
    plan_v500003_min = allocator.build_plan(
        profiles["V500003"], r3, {"top_product": top_v500001}, {"allocation_objective": "minimize_risk"}, {}
    )
    proj_v500001 = {item["product"]: item for item in allocator.analyze_product_projections(profiles["V500001"], r1, {})}
    proj_v500002 = {item["product"]: item for item in allocator.analyze_product_projections(profiles["V500002"], r2, {})}
    proj_v500003 = {item["product"]: item for item in allocator.analyze_product_projections(profiles["V500003"], r3, {})}

    expected = {
        "S01": f"{profiles['V500002'].age} 岁",
        "S02": profiles["V500003"].risk_level,
        "S03": str(int(profiles["V500002"].net_asset)),
        "S04": fmt_money(profiles["V500001"].monthly_saving),
        "S05": str(int(profiles["V500002"].enterprise_ann)),
        "S06": fmt_money(profiles["V500003"].monthly_saving),
        "S07": fmt_count(count_where(sql_executor, "Age < 40")),
        "S08": fmt_count(count_where(sql_executor, "Age >= 30")),
        "S09": fmt_count(count_where(sql_executor, "Pension >= 6000")),
        "S10": fmt_count(count_where(sql_executor, "Enterprise_Ann > 0")),
        "S11": f"{avg_where(sql_executor, 'Age', '1=1')} 岁",
        "S12": fmt_money(avg_where(sql_executor, "Monthly_Income", "1=1")),
        "S13": fmt_money(avg_where(sql_executor, "Monthly_Expend", "1=1")),
        "S14": f"{avg_where(sql_executor, 'Age', 'Age >= 30')} 岁",
        "S15": f"{avg_where(sql_executor, 'Age', 'Age < 40')} 岁",
        "S16": top_v500001,
        "S17": fmt_count(equity_cnt),
        "S18": f"{equity_avg_age} 岁",
        "S19": fmt_duration(r1.retirement_duration_text),
        "S20": fmt_duration(r2.retirement_duration_text),
        "S21": fmt_duration(r3.retirement_duration_text),
        "S22": fmt_money(r2.retirement_monthly_expend),
        "S23": fmt_money(r2.required_asset_at_retirement),
        "S24": fmt_money(r2.accumulated_asset_at_retirement),
        "S25": fmt_money(r3.retirement_monthly_expend),
        "S26": fmt_money(r3.required_asset_at_retirement),
        "S27": fmt_money(r3.accumulated_asset_at_retirement),
        "S28": fmt_money(r1.gap if r1.gap > 0 else 0) if r1.gap > 0 else "在当前假设下不存在资金缺口",
        "S29": "在当前假设下不存在资金缺口" if r2.gap <= 0 else fmt_money(r2.gap),
        "S30": "在当前假设下不存在资金缺口" if r3.gap <= 0 else fmt_money(r3.gap),
        "S31": fmt_money(r1_infl3.required_asset_at_retirement),
        "S32": fmt_money(r2_split.required_asset_at_retirement),
        "S33": fmt_money(r3_split.required_asset_at_retirement),
        "S34": fmt_money(r1_extra2k.accumulated_asset_at_retirement),
        "S35": "在当前假设下不存在资金缺口" if r1_extra2k.gap <= 0 else fmt_money(r1_extra2k.gap),
        "S36": fmt_money(r1_goal12k.required_asset_at_retirement),
        "S37": fmt_money(r1_goal12k.gap) if r1_goal12k.gap > 0 else "在当前假设下不存在资金缺口",
        "S38": "在当前假设下不存在资金缺口" if r1_goal12k_extra2k.gap <= 0 else fmt_money(r1_goal12k_extra2k.gap),
        "S39": fmt_money(r2_goal15k.required_asset_at_retirement),
        "S40": fmt_money(r2_goal15k_infl3.required_asset_at_retirement),
        "S41": "在当前假设下不存在资金缺口" if r2_goal15k_infl3.gap <= 0 else fmt_money(r2_goal15k_infl3.gap),
        "S42": "权益类产品配置 100%",
        "S43": "年金险配置 100%",
        "S44": "；".join(
            f"{('固收 + 产品' if i.product == '固收+产品' else i.product)}配置 {int(i.weight * 100)}%"
            for i in plan_v500001_min.allocation if i.weight > 0
        ),
        "S45": "；".join(
            f"{('固收 + 产品' if i.product == '固收+产品' else i.product)}配置 {int(i.weight * 100)}%"
            for i in plan_v500002_min.allocation if i.weight > 0
        ),
        "S46": "；".join(
            f"{('固收 + 产品' if i.product == '固收+产品' else i.product)}配置 {int(i.weight * 100)}%"
            for i in plan_v500003_min.allocation if i.weight > 0
        ),
        "S47": "不能，需要改为投资 固收 + 产品",
        "S48": f"能达成，全部投资现金理财时退休时预计积累 {proj_v500002['现金理财']['retirement_asset_projection']} 元，高于所需的 {int(r2.required_asset_at_retirement)} 元，无需额外调整。",
        "S49": f"能达成，全部投资现金理财时退休时预计积累 {proj_v500003['现金理财']['retirement_asset_projection']} 元，高于所需的 {int(r3.required_asset_at_retirement)} 元，无需额外调整。",
        "S50": "年金险",
        "N01": f"{profiles['V500001'].age} 岁",
        "N02": fmt_duration(r3.retirement_duration_text),
        "N03": f"{profiles['V500002'].age} 岁",
        "N04": fmt_count(count_where(sql_executor, "Net_Asset >= 500000")),
        "N05": fmt_count(count_where(sql_executor, "Monthly_Income > 10000")),
        "N06": fmt_count(count_where(sql_executor, "Monthly_Expend <= 6000")),
        "N07": fmt_count(sum(1 for p in profiles.values() if risk_rank[p.risk_level] >= 2)),
        "N08": fmt_money(avg_where(sql_executor, "Net_Asset", "1=1")),
        "N09": fmt_money(r2.retirement_monthly_expend),
        "N10": fmt_money(r3_infl3.retirement_monthly_expend),
        "N11": fmt_money(r2_split.retirement_monthly_expend),
        "N12": fmt_money(r3_split.retirement_monthly_expend),
        "N13": fmt_money(r1_goal12k_infl3.required_asset_at_retirement),
        "N14": fmt_money(r3_extra2k.accumulated_asset_at_retirement),
        "N15": fmt_money(r2_extra1k.accumulated_asset_at_retirement),
        "N16": f"不够，全部投资年金险时退休时预计积累 {proj_v500001['年金险']['retirement_asset_projection']} 元，低于所需的 {int(r1.required_asset_at_retirement)} 元。",
        "N17": f"够，全部投资现金理财时退休时预计积累 {proj_v500002['现金理财']['retirement_asset_projection']} 元，高于所需的 {int(r2.required_asset_at_retirement)} 元。",
        "N18": f"够，全部投资定期存款时退休时预计积累 {proj_v500003['定期存款']['retirement_asset_projection']} 元，高于所需的 {int(r3.required_asset_at_retirement)} 元。",
        "N19": "权益类产品配置 100%",
        "N20": "；".join(
            f"{('固收 + 产品' if i.product == '固收+产品' else i.product)}配置 {int(i.weight * 100)}%"
            for i in plan_v500003_min.allocation if i.weight > 0
        ),
        "N21": "年金险",
    }

    print("# Suggested expected overrides")
    for label, question, _ in all_single_turn_cases:
        print(f'("{label}", "{question}", "{expected.get(label, "TODO")}"),')


if __name__ == "__main__":
    main()
