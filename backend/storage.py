# backend/storage.py
import sqlite3

DB_FILE = "history.db"

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row      # 让查询结果带上列名（默认是元组）
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        score REAL,
        label TEXT,
        pinyin TEXT,
        created_at TEXT
    )
    """)
    # 迁移：旧库补上 engine 列（记录结果来源：llm / snownlp），SQLite 不支持
    # ADD COLUMN IF NOT EXISTS，所以先查表结构再决定是否加列
    cols = [row[1] for row in cur.execute("PRAGMA table_info(history)").fetchall()]
    if "engine" not in cols:
        cur.execute("ALTER TABLE history ADD COLUMN engine TEXT DEFAULT 'snownlp'")
    conn.commit()
    conn.close()

def save_record(record):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO history (text, score, label, pinyin, created_at, engine) VALUES (?, ?, ?, ?, ?, ?)",
        [record["text"], record["score"], record["label"], record["pinyin"],
         record["created_at"], record.get("engine", "snownlp")],
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at)")
    conn.commit()
    conn.close()


def get_history(limit):
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM history ORDER BY created_at DESC LIMIT ?",
        [limit],
    ).fetchall()
    conn.close()

    records = []
    for row in rows:
        records.append(dict(row))
    return records
