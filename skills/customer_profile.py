"""Customer profile skill — handles single-customer and aggregate queries."""

from __future__ import annotations

import re
from decimal import Decimal
from statistics import median

from models import CustomerProfile
from tools.memory_manager import MemoryManager
from tools.sql_executor import SQLExecutor
from tools.sql_templates import SQLTemplates


class CustomerProfileSkill:
    _RISK_ORDER = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}

    def __init__(
        self, sql_executor: SQLExecutor, memory_manager: MemoryManager
    ) -> None:
        self.sql_executor = sql_executor
        self.memory_manager = memory_manager

    def get_profile(self, session_id: str, customer_id: str) -> CustomerProfile:
        state = self.memory_manager.get_session(session_id)
        if state.profile and state.customer_id == customer_id:
            return CustomerProfile(**state.profile)

        sql, params = SQLTemplates.select_profile(
            customer_id,
            self.sql_executor.base_table,
        )
        row = self.sql_executor.fetch_one(sql, params)
        if not row:
            raise ValueError(f"Customer {customer_id} not found.")

        profile = CustomerProfile(
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
        self.memory_manager.remember_profile(session_id, profile)
        return profile

    def list_profiles(self) -> list[CustomerProfile]:
        rows = self.sql_executor.fetch_all(
            (
                "SELECT User_ID, Age, Gender, Rsk_Cd, Net_Asset, Monthly_Income, "
                "Monthly_Expend, Pension, Enterprise_Ann "
                f"FROM {self.sql_executor.base_table}"
            )
        )
        return [
            CustomerProfile(
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
            for row in rows
        ]

    @classmethod
    def _field_value(cls, profile: CustomerProfile, field: str) -> Decimal | int | str:
        if field == "age":
            return profile.age
        if field == "net_asset":
            return profile.net_asset
        if field == "monthly_income":
            return profile.monthly_income
        if field == "monthly_expend":
            return profile.monthly_expend
        if field == "monthly_saving":
            return profile.monthly_saving
        if field == "pension":
            return profile.pension
        if field == "enterprise_ann":
            return profile.enterprise_ann
        if field == "risk_level":
            return profile.risk_level
        raise ValueError(f"Unsupported profile field: {field}")

    @classmethod
    def _compare(
        cls,
        left: Decimal | int | str,
        operator: str,
        right: Decimal | int | str,
    ) -> bool:
        if isinstance(left, str) or isinstance(right, str):
            left_val = cls._RISK_ORDER.get(str(left), -1)
            right_val = cls._RISK_ORDER.get(str(right), -1)
        else:
            left_val = Decimal(str(left))
            right_val = Decimal(str(right))

        if operator == ">=":
            return left_val >= right_val
        if operator == ">":
            return left_val > right_val
        if operator == "<=":
            return left_val <= right_val
        if operator == "<":
            return left_val < right_val
        if operator == "==":
            return left_val == right_val
        raise ValueError(f"Unsupported operator: {operator}")

    @staticmethod
    def _format_result(field: str, agg: str, value: Decimal | int | str) -> str:
        if agg == "argmax_customer":
            return str(value)
        if agg == "median" and field == "age":
            return f"{int(value)} 岁"
        if agg == "count":
            return f"{int(value)} 个"
        if field == "age":
            return f"{int(value)} 岁"
        return f"{Decimal(str(value)).quantize(Decimal('1'))} 元"

    def query(self, params: dict[str, object]) -> dict[str, object]:
        profiles = self.list_profiles()
        field = str(params.get("field", "age"))
        agg = str(params.get("agg", "count"))
        operator = str(params.get("operator", ""))
        value = params.get("value")
        compare_field = params.get("compare_field")

        filtered = profiles
        if operator:
            if compare_field:
                filtered = [
                    profile
                    for profile in profiles
                    if self._compare(
                        self._field_value(profile, field),
                        operator,
                        self._field_value(profile, str(compare_field)),
                    )
                ]
            elif value is not None:
                filtered = [
                    profile
                    for profile in profiles
                    if self._compare(self._field_value(profile, field), operator, value)
                ]

        if agg == "count":
            result = len(filtered)
            return {"result": self._format_result(field, agg, result), "value": result}

        if agg == "avg":
            values = [Decimal(str(self._field_value(profile, field))) for profile in filtered]
            avg_value = (sum(values) / Decimal(len(values))) if values else Decimal("0")
            rounded = int(avg_value.quantize(Decimal("1")))
            return {
                "result": self._format_result(field, agg, rounded),
                "value": rounded,
            }

        if agg == "median":
            values = [Decimal(str(self._field_value(profile, field))) for profile in filtered]
            if not values:
                return {"result": self._format_result(field, agg, 0), "value": 0}
            median_value = int(Decimal(str(median(values))).quantize(Decimal("1")))
            return {
                "result": self._format_result(field, agg, median_value),
                "value": median_value,
            }

        if agg == "argmax_customer":
            if not filtered:
                return {"result": "未找到符合条件的客户。"}
            winner = max(
                filtered,
                key=lambda profile: (
                    Decimal(str(self._field_value(profile, field))),
                    profile.user_id,
                ),
            )
            return {"result": winner.user_id, "customer_id": winner.user_id}

        raise ValueError(f"Unsupported profile aggregate: {agg}")

    def answer_profile_question(
        self,
        session_id: str,
        customer_id: str | None,
        question: str,
    ) -> str:
        # Aggregate queries don't need customer_id
        if "多少客户" in question or "客户数" in question:
            return self._answer_count_question(question)
        if "平均" in question:
            return self._answer_avg_question(question)

        if not customer_id:
            return "请先在问题中给出客户 ID，例如 V500001。"

        profile = self.get_profile(session_id, customer_id)
        if "结余" in question:
            return f"{int(profile.monthly_saving)} 元"
        if "年龄" in question:
            return f"{profile.age} 岁"
        if "月收入" in question or "收入" in question:
            return f"{int(profile.monthly_income)} 元"
        if "月支出" in question or "支出" in question:
            return f"{int(profile.monthly_expend)} 元"
        if "风险" in question:
            return f"{profile.risk_level}"
        if "净资产" in question:
            return f"{int(profile.net_asset)} 元"
        if "退休金" in question or "养老金" in question:
            return f"{int(profile.pension)} 元"
        if "企业年金" in question:
            return f"{int(profile.enterprise_ann)} 元"
        return (
            f"客户 {customer_id} 当前 {profile.age} 岁，风险评级 {profile.risk_level}，"
            f"净资产 {int(profile.net_asset)} 元，月收入 {int(profile.monthly_income)} 元，"
            f"月支出 {int(profile.monthly_expend)} 元。"
        )

    def _answer_count_question(self, question: str) -> str:
        """Handle count queries like '多少客户年龄在30岁及以上'."""
        base = self.sql_executor.base_table
        age_match = re.search(r"年龄[^0-9]*(\d+)\s*岁及以上", question)
        if age_match:
            sql = SQLTemplates.count_users_by_condition(
                f"Age >= {age_match.group(1)}", base
            )
            row = self.sql_executor.fetch_one(sql)
            return f"{int(row['cnt'])} 个" if row else "0 个"
        age_match = re.search(r"年龄[^0-9]*(\d+)\s*岁以下", question)
        if age_match:
            sql = SQLTemplates.count_users_by_condition(
                f"Age < {age_match.group(1)}", base
            )
            row = self.sql_executor.fetch_one(sql)
            return f"{int(row['cnt'])} 个" if row else "0 个"
        sql = SQLTemplates.count_users_by_condition("1=1", base)
        row = self.sql_executor.fetch_one(sql)
        return f"{int(row['cnt'])} 个" if row else "0 个"

    def _answer_avg_question(self, question: str) -> str:
        """Handle average queries on base_table."""
        base = self.sql_executor.base_table
        if "年龄" in question:
            sql = SQLTemplates.avg_field_by_condition("Age", "1=1", base)
            row = self.sql_executor.fetch_one(sql)
            val = round(float(row["avg_value"])) if row and row["avg_value"] else 0
            return f"{val} 岁"
        if "收入" in question:
            sql = SQLTemplates.avg_field_by_condition("Monthly_Income", "1=1", base)
            row = self.sql_executor.fetch_one(sql)
            val = round(float(row["avg_value"])) if row and row["avg_value"] else 0
            return f"{val} 元"
        return "暂不支持该统计维度。"
