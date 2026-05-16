from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CALIB = ROOT / "calibration_3customers"
DB_PATH = ROOT / "calibration_3customers" / "calibration_eval.db"
BASE_TABLE = "train_base_table"
ACTION_TABLE = "train_action_table"


def mapped_product_to_raw(product: str) -> tuple[str, str, str]:
    if product == "现金理财":
        return ("理财", "现金", "R1")
    if product == "定期存款":
        return ("存款", "一般性", "R1")
    if product == "短债类产品":
        return ("理财", "短债", "R2")
    if product == "固收+产品":
        return ("理财", "固收+", "R3")
    if product == "权益类产品":
        return ("基金", "权益", "R4")
    if product == "年金险":
        return ("保险", "养老年金", "R1")
    return ("其他", "其他", "R1")


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(f'DROP TABLE IF EXISTS "{BASE_TABLE}"')
    conn.execute(f'DROP TABLE IF EXISTS "{ACTION_TABLE}"')
    conn.execute(
        f'''
        CREATE TABLE "{BASE_TABLE}" (
            "User_ID" TEXT,
            "Age" TEXT,
            "Gender" TEXT,
            "Rsk_Cd" TEXT,
            "Net_Asset" TEXT,
            "Monthly_Income" TEXT,
            "Monthly_Expend" TEXT,
            "Pension" TEXT,
            "Enterprise_Ann" TEXT
        )
        '''
    )
    conn.execute(
        f'''
        CREATE TABLE "{ACTION_TABLE}" (
            "user_id" TEXT,
            "action_typ" TEXT,
            "prod_typ" TEXT,
            "prod_sub_typ" TEXT,
            "rsk_lvl" TEXT
        )
        '''
    )


def load_profiles(conn: sqlite3.Connection) -> None:
    path = CALIB / "customer_profiles.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = [
            (
                row["user_id"],
                row["age"],
                row["gender"],
                row["risk_level"],
                row["net_asset"],
                row["monthly_income"],
                row["monthly_expend"],
                row["pension"],
                row["enterprise_ann"],
            )
            for row in reader
        ]
    conn.executemany(
        f'''
        INSERT INTO "{BASE_TABLE}" (
            "User_ID", "Age", "Gender", "Rsk_Cd", "Net_Asset",
            "Monthly_Income", "Monthly_Expend", "Pension", "Enterprise_Ann"
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        rows,
    )


def load_actions(conn: sqlite3.Connection) -> None:
    path = CALIB / "customer_behavior_long.csv"
    action_rows: list[tuple[str, str, str, str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            user_id = row["user_id"]
            prod_typ, prod_sub_typ, rsk_lvl = mapped_product_to_raw(row["mapped_product"])
            counts = [
                ("购买", int(row["buy_cnt"])),
                ("赎回", int(row["redeem_cnt"])),
                ("浏览详情", int(row["browse_detail_cnt"])),
                ("浏览持仓", int(row["browse_holding_cnt"])),
                ("收藏", int(row["favorite_cnt"])),
            ]
            for action_typ, count in counts:
                for _ in range(count):
                    action_rows.append((user_id, action_typ, prod_typ, prod_sub_typ, rsk_lvl))
    conn.executemany(
        f'''
        INSERT INTO "{ACTION_TABLE}" (
            "user_id", "action_typ", "prod_typ", "prod_sub_typ", "rsk_lvl"
        ) VALUES (?, ?, ?, ?, ?)
        ''',
        action_rows,
    )


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        create_tables(conn)
        load_profiles(conn)
        load_actions(conn)
        conn.commit()
    finally:
        conn.close()
    print(DB_PATH)


if __name__ == "__main__":
    main()
