from __future__ import annotations

import argparse
import csv
import os
import sqlite3
from pathlib import Path


DB_NAME = os.getenv("TASK2_DB_NAME", "pension_agent.db")
BASE_TABLE = os.getenv("TASK2_BASE_TABLE", "train_base_table")
ACTION_TABLE = os.getenv("TASK2_ACTION_TABLE", "train_action_table")


def create_table_from_csv(
    conn: sqlite3.Connection, csv_path: Path, table_name: str
) -> None:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"No header found in {csv_path}")
        columns = reader.fieldnames
        column_defs = ", ".join(f'"{col}" TEXT' for col in columns)
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.execute(f'CREATE TABLE "{table_name}" ({column_defs})')
        placeholders = ", ".join("?" for _ in columns)
        quoted_columns = ", ".join(f'"{col}"' for col in columns)
        rows = ([row.get(col, "") for col in columns] for row in reader)
        conn.executemany(
            f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})',
            rows,
        )


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS idx_base_user_id ON "{BASE_TABLE}"(User_ID)'
    )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS idx_action_user_id ON "{ACTION_TABLE}"(user_id)'
    )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS idx_action_prod ON "{ACTION_TABLE}"(prod_typ, prod_sub_typ, rsk_lvl)'
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize SQLite DB for pension agent."
    )
    parser.add_argument("--base", required=True, help="Path to base_table CSV")
    parser.add_argument("--action", required=True, help="Path to action_table CSV")
    parser.add_argument(
        "--db", default="./pension_agent.db", help="SQLite DB output path"
    )
    parser.add_argument(
        "--base-table",
        default=BASE_TABLE,
        help=f"Base table name (default: {BASE_TABLE})",
    )
    parser.add_argument(
        "--action-table",
        default=ACTION_TABLE,
        help=f"Action table name (default: {ACTION_TABLE})",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        create_table_from_csv(conn, Path(args.base), args.base_table)
        create_table_from_csv(conn, Path(args.action), args.action_table)
        create_indexes(conn)
        conn.commit()

    print(f"Database initialized at {db_path}")


if __name__ == "__main__":
    main()
