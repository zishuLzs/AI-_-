"""Behavior analysis skill — handles single-customer and aggregate behavior queries."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from skills.customer_profile import CustomerProfileSkill
from tools.sql_executor import SQLExecutor
from tools.sql_templates import SQLTemplates


_EQUITY_KEYWORDS = ("权益", "R4", "R5")
_BOND_KEYWORDS = ("短债", "R2")
_FIXED_INCOME_KEYWORDS = ("固收", "R3")
_CASH_KEYWORDS = ("现金理财",)
_DEPOSIT_KEYWORDS = ("定期存款",)
_ANNUITY_KEYWORDS = ("年金险", "年金")

# Standard action types for browsing
_VIEW_ACTION_TYPES = ["浏览详情", "浏览持仓"]
_ALL_ACTION_TYPES = ["购买", "赎回", "浏览详情", "浏览持仓", "收藏"]


class BehaviorAnalysisSkill:
    def __init__(
        self,
        sql_executor: SQLExecutor,
        profile_skill: CustomerProfileSkill | None = None,
    ) -> None:
        self.sql_executor = sql_executor
        self.profile_skill = profile_skill

    def analyze(self, customer_id: str) -> dict[str, Any]:
        action = self.sql_executor.action_table
        top_sql, top_params = SQLTemplates.top_preference_product(customer_id, action)
        top_row = self.sql_executor.fetch_one(top_sql, top_params)
        breakdown_sql, breakdown_params = SQLTemplates.preference_breakdown(
            customer_id, action
        )
        rows = self.sql_executor.fetch_all(breakdown_sql, breakdown_params) or []
        counts = {str(row["mapped_product"]): int(row["cnt"]) for row in rows}
        top_product = str(top_row["mapped_product"]) if top_row else "其他"

        insight_map = {
            "现金理财": "流动性与安全性",
            "定期存款": "稳健收益与本金安全",
            "短债类产品": "低波动下的略高收益",
            "固收+产品": "稳健增值与适度收益弹性",
            "权益类产品": "长期成长与较高收益空间",
            "年金险": "长期养老保障与长寿风险对冲",
        }
        return {
            "top_product": top_product,
            "counts": counts,
            "insight": f"客户更关注{insight_map.get(top_product, '综合资产配置')}。",
        }

    def answer(self, customer_id: str) -> str:
        result = self.analyze(customer_id)
        top_product = result["top_product"]
        count = result["counts"].get(top_product, 0)
        return f"客户 {customer_id} 行为最多的产品类型为 {top_product}，相关行为共 {count} 次。"

    @staticmethod
    def _map_product(row: dict[str, Any]) -> str:
        prod_typ = str(row.get("prod_typ", ""))
        prod_sub_typ = str(row.get("prod_sub_typ", ""))
        rsk_lvl = str(row.get("rsk_lvl", ""))
        if prod_sub_typ == "现金" and prod_typ == "理财":
            return "现金理财"
        if prod_sub_typ == "一般性" and prod_typ == "存款":
            return "定期存款"
        if prod_typ in ("理财", "基金") and rsk_lvl == "R2":
            return "短债类产品"
        if prod_typ in ("理财", "基金") and rsk_lvl == "R3":
            return "固收+产品"
        if prod_typ == "基金" and rsk_lvl in ("R4", "R5"):
            return "权益类产品"
        if prod_typ == "保险" and prod_sub_typ in ("税延养老年金", "养老年金"):
            return "年金险"
        return "其他"

    @staticmethod
    def _matches_action(row_action: str, action_type: str) -> bool:
        if action_type == "浏览":
            return row_action in _VIEW_ACTION_TYPES
        return row_action == action_type

    def query(self, params: dict[str, object]) -> dict[str, object]:
        agg = str(params.get("agg", "total_count"))
        action_type = str(params.get("action_type", "浏览"))
        customer_id = params.get("customer_id")
        product = params.get("product")
        min_count = int(params.get("min_count", 1))
        where_sql, where_params = self._build_behavior_where_clause(action_type, product, customer_id)
        action_table = self.sql_executor.action_table
        base_table = self.sql_executor.base_table

        if agg == "total_count":
            sql = (
                f"SELECT COUNT(*) AS cnt FROM {action_table} "
                f"WHERE {where_sql}"
            )
            row = self.sql_executor.fetch_one(sql, tuple(where_params))
            count = int(row["cnt"]) if row and row.get("cnt") is not None else 0
            return {"result": f"{count} 次", "value": count}

        grouped_sql = f"""
        SELECT user_id, COUNT(*) AS cnt
        FROM {action_table}
        WHERE {where_sql}
        GROUP BY user_id
        """.strip()

        if agg == "customer_action_count":
            sql = f"SELECT cnt FROM ({grouped_sql}) t WHERE user_id = %s"
            row = self.sql_executor.fetch_one(sql, tuple(where_params + [str(customer_id)]))
            count = int(row["cnt"]) if row and row.get("cnt") is not None else 0
            return {"result": f"{count} 次", "value": count}

        if agg == "customer_count":
            sql = f"SELECT COUNT(*) AS cnt FROM ({grouped_sql}) t WHERE cnt >= %s"
            row = self.sql_executor.fetch_one(sql, tuple(where_params + [min_count]))
            count = int(row["cnt"]) if row and row.get("cnt") is not None else 0
            return {"result": f"{count} 个", "value": count}

        if agg == "max_customer_id":
            sql = (
                f"SELECT user_id, cnt FROM ({grouped_sql}) t "
                "ORDER BY cnt DESC, user_id DESC LIMIT 1"
            )
            row = self.sql_executor.fetch_one(sql, tuple(where_params))
            if not row:
                return {"result": "未找到符合条件的客户。"}
            return {"result": str(row["user_id"]), "customer_id": str(row["user_id"]), "count": int(row["cnt"])}

        if agg == "avg_age":
            if self.profile_skill is None:
                return {"result": "未找到符合条件的客户。"}
            sql = f"""
            SELECT ROUND(AVG(b.Age), 6) AS avg_age
            FROM (
                {grouped_sql}
            ) t
            INNER JOIN {base_table} b ON b.User_ID = t.user_id
            WHERE t.cnt >= %s
            """.strip()
            row = self.sql_executor.fetch_one(sql, tuple(where_params + [min_count]))
            if not row or row.get("avg_age") is None:
                return {"result": "未找到符合条件的客户。"}
            avg_age = int(Decimal(str(row["avg_age"])).quantize(Decimal("1")))
            return {"result": f"{avg_age} 岁", "value": avg_age}

        raise ValueError(f"Unsupported behavior aggregate: {agg}")

    def _build_behavior_where_clause(
        self,
        action_type: str,
        product: object,
        customer_id: object,
    ) -> tuple[str, list[object]]:
        conditions = ["prod_typ <> '非财富'"]
        params: list[object] = []

        action_types = self._action_types_from_label(action_type)
        placeholders = ", ".join(["%s"] * len(action_types))
        conditions.append(f"action_typ IN ({placeholders})")
        params.extend(action_types)

        if product:
            prod_filter, rsk_filter = self._product_filters_by_name(str(product))
            if prod_filter:
                conditions.append(prod_filter)
            if rsk_filter:
                conditions.append(rsk_filter)

        if customer_id:
            conditions.append("user_id = %s")
            params.append(str(customer_id))

        return " AND ".join(conditions), params

    @staticmethod
    def _action_types_from_label(action_type: str) -> list[str]:
        if action_type == "浏览":
            return _VIEW_ACTION_TYPES
        return [action_type]

    @staticmethod
    def _product_filters_by_name(product: str) -> tuple[str, str]:
        if product == "权益类产品":
            return "prod_typ = '基金'", "rsk_lvl IN ('R4', 'R5')"
        if product == "短债类产品":
            return "prod_typ IN ('理财', '基金')", "rsk_lvl = 'R2'"
        if product == "固收+产品":
            return "prod_typ IN ('理财', '基金')", "rsk_lvl = 'R3'"
        if product == "年金险":
            return "prod_typ = '保险' AND prod_sub_typ IN ('税延养老年金', '养老年金')", ""
        if product == "现金理财":
            return "prod_sub_typ = '现金' AND prod_typ = '理财'", ""
        if product == "定期存款":
            return "prod_typ = '存款' AND prod_sub_typ = '一般性'", ""
        return "", ""

    def answer_question(
        self,
        session_id: str,
        customer_id: str | None,
        question: str,
    ) -> str:
        """Handle behavior-related questions."""
        # Aggregate queries don't need customer_id
        if "平均年龄" in question and ("浏览" in question or "购买" in question):
            return self._answer_avg_age_by_behavior(question)
        if "多少客户" in question or "客户数" in question:
            if "浏览" in question or "购买" in question:
                return self._answer_count_by_behavior(question)
        # Single customer behavior
        if customer_id:
            return self.answer(customer_id)
        return "请指定客户 ID。"

    def _answer_avg_age_by_behavior(self, question: str) -> str:
        """Handle Q4-type: avg age of customers with N+ behavior on a product type."""
        action = self.sql_executor.action_table
        base = self.sql_executor.base_table

        prod_filter, rsk_filter = self._resolve_product_filters(question)
        if not prod_filter:
            return "暂不支持该产品类型的统计。"

        count_match = re.search(r"(\d+)\s*次及以上", question)
        min_count = int(count_match.group(1)) if count_match else 1

        act_types = _VIEW_ACTION_TYPES
        if "购买" in question and "浏览" not in question:
            act_types = ["购买"]

        act_condition = ", ".join(f"'{a}'" for a in act_types)
        conditions = [f"action_typ IN ({act_condition})"]
        conditions.append(prod_filter)
        if rsk_filter:
            conditions.append(rsk_filter)
        conditions.append("prod_typ <> '非财富'")
        where_clause = " AND ".join(conditions)

        sql = f"""
        WITH T AS (
            SELECT user_id, COUNT(*) AS view_cnt
            FROM {action}
            WHERE {where_clause}
            GROUP BY user_id
            HAVING view_cnt >= {min_count}
        )
        SELECT ROUND(AVG(b.Age), 6) AS avg_age
        FROM T INNER JOIN {base} b ON b.User_ID = T.user_id
        """.strip()

        row = self.sql_executor.fetch_one(sql)
        if row and row.get("avg_age") is not None:
            avg_age = round(float(row["avg_age"]))
            return f"{avg_age} 岁"
        return "未找到符合条件的客户。"

    def _answer_count_by_behavior(self, question: str) -> str:
        """Handle count queries on behavior table, e.g. '多少客户浏览权益类产品2次及以上'."""
        action = self.sql_executor.action_table
        base = self.sql_executor.base_table

        prod_filter, rsk_filter = self._resolve_product_filters(question)

        count_match = re.search(r"(\d+)\s*次及以上", question)
        min_count = int(count_match.group(1)) if count_match else 1

        act_types = _VIEW_ACTION_TYPES
        if "购买" in question and "浏览" not in question:
            act_types = ["购买"]

        act_condition = ", ".join(f"'{a}'" for a in act_types)

        # Build WHERE clause dynamically
        conditions = [f"action_typ IN ({act_condition})"]
        if prod_filter:
            conditions.append(prod_filter)
        if rsk_filter:
            conditions.append(rsk_filter)
        conditions.append("prod_typ <> '非财富'")
        where_clause = " AND ".join(conditions)

        sql = f"""
        WITH T AS (
            SELECT user_id, COUNT(*) AS view_cnt
            FROM {action}
            WHERE {where_clause}
            GROUP BY user_id
            HAVING view_cnt >= {min_count}
        )
        SELECT COUNT(*) AS cnt
        FROM T INNER JOIN {base} b ON b.User_ID = T.user_id
        """.strip()

        row = self.sql_executor.fetch_one(sql)
        count = int(row["cnt"]) if row and row.get("cnt") is not None else 0
        return f"{count} 个"

    @staticmethod
    def _resolve_product_filters(question: str) -> tuple[str, str]:
        """Resolve product type and risk level filters from question keywords.

        Returns:
            Tuple of (prod_filter_sql, rsk_filter_sql).
        """
        if any(k in question for k in _EQUITY_KEYWORDS):
            return "prod_typ = '基金'", "rsk_lvl IN ('R4', 'R5')"
        if any(k in question for k in _BOND_KEYWORDS):
            return "prod_typ IN ('理财', '基金')", "rsk_lvl = 'R2'"
        if any(k in question for k in _FIXED_INCOME_KEYWORDS):
            return "prod_typ IN ('理财', '基金')", "rsk_lvl = 'R3'"
        if any(k in question for k in _ANNUITY_KEYWORDS):
            return (
                "prod_typ = '保险' AND prod_sub_typ IN ('税延养老年金', '养老年金')",
                "",
            )
        if any(k in question for k in _CASH_KEYWORDS):
            return "prod_sub_typ = '现金' AND prod_typ = '理财'", ""
        if any(k in question for k in _DEPOSIT_KEYWORDS):
            return "prod_typ = '存款' AND prod_sub_typ = '一般性'", ""
        return "", ""
