import os
import pymysql

DB_HOST = os.getenv("TASK2_DB_HOST", "172.16.48.27")
DB_PORT = int(os.getenv("TASK2_DB_PORT", "3306"))
DB_USER = os.getenv("TASK2_DB_USER", "test_user")
DB_PASSWORD = os.getenv("TASK2_DB_PASSWORD", "R6#pV9@kT3!xM2$q")
DB_NAME = os.getenv("TASK2_DB_NAME", "cmb_contest")
BASE_TABLE = os.getenv("TASK2_BASE_TABLE", "train_base_table")
ACTION_TABLE = os.getenv("TASK2_ACTION_TABLE", "train_action_table")

conn = pymysql.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME,
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    connect_timeout=5,
    read_timeout=10,
    write_timeout=10,
)

try:
    with conn.cursor() as cur:
        cur.execute(f"SELECT Age FROM {BASE_TABLE} WHERE User_ID=%s", ("V500001",))
        row = cur.fetchone()
finally:
    conn.close()

print(f"{row['Age']}岁")
