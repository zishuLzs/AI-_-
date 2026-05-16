"""SQL templates with dynamic table names.

All templates use format placeholders {base_table} and {action_table}
which are filled by the caller from SQLExecutor.base_table / action_table.
"""

from __future__ import annotations


class SQLTemplates:
    PROFILE_FIELD_MAP = {
        "age": "Age",
        "gender": "Gender",
        "risk_level": "Rsk_Cd",
        "net_asset": "Net_Asset",
        "monthly_income": "Monthly_Income",
        "monthly_expend": "Monthly_Expend",
        "pension": "Pension",
        "enterprise_ann": "Enterprise_Ann",
    }

    @classmethod
    def select_profile(
        cls, user_id: str, base_table: str = "base_table"
    ) -> tuple[str, tuple[str, ...]]:
        return (
            f"""
        SELECT User_ID, Age, Gender, Rsk_Cd, Net_Asset,
               Monthly_Income, Monthly_Expend, Pension, Enterprise_Ann
        FROM {base_table}
        WHERE User_ID = %s
        """.strip(),
            (user_id,),
        )

    @classmethod
    def select_single_field(
        cls,
        user_id: str,
        field_key: str,
        base_table: str = "base_table",
    ) -> tuple[str, tuple[str, ...]]:
        if field_key not in cls.PROFILE_FIELD_MAP:
            raise ValueError(f"Unsupported field key: {field_key}")
        field_name = cls.PROFILE_FIELD_MAP[field_key]
        return f"SELECT {field_name} FROM {base_table} WHERE User_ID = %s", (user_id,)

    @staticmethod
    def count_by_condition(
        condition_sql: str,
        base_table: str = "base_table",
    ) -> str:
        return f"SELECT COUNT(*) AS cnt FROM {base_table} WHERE {condition_sql}"

    @staticmethod
    def avg_by_condition(
        field_name: str,
        condition_sql: str,
        base_table: str = "base_table",
    ) -> str:
        return (
            f"SELECT ROUND(AVG({field_name}), 6) AS avg_value "
            f"FROM {base_table} WHERE {condition_sql}"
        )

    @staticmethod
    def count_users_by_condition(
        condition_sql: str,
        base_table: str = "base_table",
    ) -> str:
        """Deprecated alias — use count_by_condition."""
        return SQLTemplates.count_by_condition(condition_sql, base_table)

    @staticmethod
    def avg_field_by_condition(
        field_name: str,
        condition_sql: str,
        base_table: str = "base_table",
    ) -> str:
        """Deprecated alias — use avg_by_condition."""
        return SQLTemplates.avg_by_condition(field_name, condition_sql, base_table)

    @staticmethod
    def _product_case_expr() -> str:
        """Standard product mapping CASE expression."""
        return """
            CASE
                WHEN prod_sub_typ = '现金' AND prod_typ = '理财' THEN '现金理财'
                WHEN prod_sub_typ = '一般性' AND prod_typ = '存款' THEN '定期存款'
                WHEN prod_typ IN ('理财', '基金') AND rsk_lvl = 'R2' THEN '短债类产品'
                WHEN prod_typ IN ('理财', '基金') AND rsk_lvl = 'R3' THEN '固收+产品'
                WHEN prod_typ = '基金' AND rsk_lvl IN ('R4', 'R5') THEN '权益类产品'
                WHEN prod_typ = '保险' AND prod_sub_typ IN ('税延养老年金', '养老年金') THEN '年金险'
                ELSE '其他'
            END
        """.strip()

    @classmethod
    def top_preference_product(
        cls,
        user_id: str,
        action_table: str = "action_table",
    ) -> tuple[str, tuple[str, ...]]:
        case_expr = cls._product_case_expr()
        return (
            f"""
        SELECT mapped_product, COUNT(*) AS cnt
        FROM (
            SELECT {case_expr} AS mapped_product
            FROM {action_table}
            WHERE user_id = %s AND prod_typ <> '非财富'
        ) t
        GROUP BY mapped_product
        ORDER BY cnt DESC, mapped_product ASC
        LIMIT 1
        """.strip(),
            (user_id,),
        )

    @classmethod
    def preference_breakdown(
        cls,
        user_id: str,
        action_table: str = "action_table",
    ) -> tuple[str, tuple[str, ...]]:
        case_expr = cls._product_case_expr()
        return (
            f"""
        SELECT mapped_product, COUNT(*) AS cnt
        FROM (
            SELECT {case_expr} AS mapped_product
            FROM {action_table}
            WHERE user_id = %s AND prod_typ <> '非财富'
        ) t
        GROUP BY mapped_product
        ORDER BY cnt DESC, mapped_product ASC
        """.strip(),
            (user_id,),
        )

    @staticmethod
    def avg_age_by_behavior(
        prod_typ: str,
        rsk_lvl_list: list[str],
        act_types: list[str],
        min_count: int,
        action_table: str = "action_table",
        base_table: str = "base_table",
    ) -> str:
        """Deprecated — behavior queries are built inline in BehaviorAnalysisSkill."""
        from skills.behavior_analysis import BehaviorAnalysisSkill
        raise NotImplementedError("Use BehaviorAnalysisSkill instead")
