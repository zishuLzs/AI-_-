from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FailureCategory(Enum):
    PLANNER_SCHEMA_ERROR = "planner_schema_error"
    PLANNER_MISSING_CUSTOMER_ID = "planner_missing_customer_id"
    PLANNER_INVALID_TOOL = "planner_invalid_tool"
    PLANNER_INVALID_MEMORY_UPDATE = "planner_invalid_memory_update"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    COMPOSER_SCHEMA_ERROR = "composer_schema_error"
    PROPOSAL_CONSISTENCY_ERROR = "proposal_consistency_error"


@dataclass
class FailureRecord:
    category: FailureCategory
    question: str
    detail: str
    raw_llm_output: str | None = None
    session_summary: dict[str, Any] = field(default_factory=dict)


def format_user_failure(category: FailureCategory) -> str:
    messages = {
        FailureCategory.PLANNER_SCHEMA_ERROR: "抱歉，当前问题解析失败，请重新表述。",
        FailureCategory.PLANNER_MISSING_CUSTOMER_ID: "抱歉，当前问题所需信息不完整。",
        FailureCategory.PLANNER_INVALID_TOOL: "抱歉，当前问题解析失败，请重新表述。",
        FailureCategory.PLANNER_INVALID_MEMORY_UPDATE: "抱歉，当前问题解析失败，请重新表述。",
        FailureCategory.TOOL_EXECUTION_ERROR: "抱歉，暂时无法回答该问题。",
        FailureCategory.COMPOSER_SCHEMA_ERROR: "抱歉，暂时无法回答该问题。",
        FailureCategory.PROPOSAL_CONSISTENCY_ERROR: "抱歉，当前建议书生成失败。",
    }
    return messages.get(category, "抱歉，暂时无法回答该问题。")
