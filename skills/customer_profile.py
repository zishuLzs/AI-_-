"""Customer profile skill — handles single-customer and aggregate queries."""

from __future__ import annotations

import re
from decimal import Decimal

from models import CustomerProfile
from tools.memory_manager import MemoryManager
from tools.sql_executor import SQLExecutor
from tools.sql_templates import SQLTemplates


class CustomerProfileSkill:
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
