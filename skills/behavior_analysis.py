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

    def list_actions(self) -> list[dict[str, Any]]:
        sql = (
            "SELECT user_id, action_typ, prod_typ, prod_sub_typ, rsk_lvl "
            f"FROM {self.sql_executor.action_table} WHERE prod_typ <> '非财富'"
        )
        return self.sql_executor.fetch_all(sql)

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

        rows = self.list_actions()
        filtered = []
        for row in rows:
            mapped_product = self._map_product(row)
            if product and mapped_product != str(product):
                continue
            if not self._matches_action(str(row.get("action_typ", "")), action_type):
                continue
            if customer_id and str(row.get("user_id")) != str(customer_id):
                continue
            filtered.append({**row, "mapped_product": mapped_product})

        if agg == "total_count":
            count = len(filtered)
            return {"result": f"{count} 次", "value": count}

        grouped: dict[str, int] = {}
        for row in filtered:
            user_id = str(row.get("user_id", ""))
            grouped[user_id] = grouped.get(user_id, 0) + 1

        qualified_ids = [user_id for user_id, cnt in grouped.items() if cnt >= min_count]

        if agg == "customer_count":
            return {"result": f"{len(qualified_ids)} 个", "value": len(qualified_ids)}

        if agg == "customer_action_count":
            count = grouped.get(str(customer_id), 0)
            return {"result": f"{count} 次", "value": count}

        if agg == "max_customer_id":
            if not grouped:
                return {"result": "未找到符合条件的客户。"}
            winner = max(grouped.items(), key=lambda item: (item[1], item[0]))
            return {"result": winner[0], "customer_id": winner[0], "count": winner[1]}

        if agg == "avg_age":
            if not qualified_ids or self.profile_skill is None:
                return {"result": "未找到符合条件的客户。"}
            profile_map = {
                profile.user_id: profile
                for profile in self.profile_skill.list_profiles()
            }
            ages = [profile_map[user_id].age for user_id in qualified_ids if user_id in profile_map]
            if not ages:
                return {"result": "未找到符合条件的客户。"}
            avg_age = int((sum(Decimal(age) for age in ages) / Decimal(len(ages))).quantize(Decimal("1")))
            return {"result": f"{avg_age} 岁", "value": avg_age}

        raise ValueError(f"Unsupported behavior aggregate: {agg}")

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
