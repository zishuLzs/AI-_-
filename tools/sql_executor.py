"""SQL executor supporting both MySQL (production) and SQLite (local dev)."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
_DB_TIMEOUT = 10  # seconds


class SQLExecutor:
    """Execute SQL against MySQL or SQLite depending on environment."""

    def __init__(self, db_config: dict[str, Any]) -> None:
        self.db_config = db_config
        self._backend = db_config.get("backend", "sqlite")

    @staticmethod
    def get_db_config() -> dict[str, Any]:
        """Read DB config from environment variables.

        MySQL env vars (production):
            TASK2_DB_HOST, TASK2_DB_PORT, TASK2_DB_USER,
            TASK2_DB_PASSWORD, TASK2_DB_NAME,
            TASK2_BASE_TABLE, TASK2_ACTION_TABLE

        SQLite env var (local dev):
            TASK2_SQLITE_PATH (optional, defaults to ./pension_agent.db)
        """
        base_table = os.environ.get("TASK2_BASE_TABLE", "train_base_table")
        action_table = os.environ.get("TASK2_ACTION_TABLE", "train_action_table")

        db_host = os.environ.get("TASK2_DB_HOST")
        if db_host:
            config: dict[str, Any] = {
                "backend": "mysql",
                "host": db_host,
                "port": int(os.environ.get("TASK2_DB_PORT", "3306")),
                "user": os.environ.get("TASK2_DB_USER", "root"),
                "password": os.environ.get("TASK2_DB_PASSWORD", ""),
                "database": os.environ.get("TASK2_DB_NAME", ""),
                "base_table": base_table,
                "action_table": action_table,
            }
            # Validate required MySQL config
            missing = [k for k in ("host", "user", "database") if not config.get(k)]
            if missing:
                logger.warning(
                    "MySQL config missing: %s — falling back to SQLite", missing
                )
                return SQLExecutor._sqlite_config(base_table, action_table)
            return config

        return SQLExecutor._sqlite_config(base_table, action_table)

    @staticmethod
    def _sqlite_config(base_table: str, action_table: str) -> dict[str, Any]:
        sqlite_path = os.environ.get(
            "TASK2_SQLITE_PATH",
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "pension_agent.db"
            ),
        )
        return {
            "backend": "sqlite",
            "path": sqlite_path,
            "base_table": base_table,
            "action_table": action_table,
        }

    @property
    def base_table(self) -> str:
        return self.db_config.get("base_table", "train_base_table")

    @property
    def action_table(self) -> str:
        return self.db_config.get("action_table", "train_action_table")

    def _connect(self) -> Any:
        if self._backend == "mysql":
            import pymysql

            try:
                return pymysql.connect(
                    host=self.db_config["host"],
                    port=self.db_config["port"],
                    user=self.db_config["user"],
                    password=self.db_config["password"],
                    database=self.db_config["database"],
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                    connect_timeout=_DB_TIMEOUT,
                    read_timeout=_DB_TIMEOUT,
                )
            except (pymysql.err.OperationalError, pymysql.err.InternalError) as exc:
                raise ConnectionError(
                    f"MySQL connection failed: {exc}. "
                    "Check TASK2_DB_HOST/PORT/USER/PASSWORD/NAME."
                ) from exc
        else:
            import sqlite3
            from pathlib import Path

            db_path = Path(self.db_config["path"])
            if not db_path.exists():
                raise FileNotFoundError(
                    f"Database not found at {db_path}. "
                    "Run init_db.py or set TASK2_SQLITE_PATH."
                )
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

    def fetch_one(self, sql: str, params: tuple | None = None) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            if self._backend == "mysql":
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.fetchone()
            else:
                row = conn.execute(sql, params or ()).fetchone()
                return dict(row) if row else None
        finally:
            conn.close()

    def fetch_all(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if self._backend == "mysql":
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.fetchall()
            else:
                rows = conn.execute(sql, params or ()).fetchall()
                return [dict(row) for row in rows]
        finally:
            conn.close()
