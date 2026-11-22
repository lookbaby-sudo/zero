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
        session_id TEXT,
        text TEXT,
        score REAL,
        label TEXT,
        pinyin TEXT,
        engine TEXT DEFAULT 'snownlp',
        created_at TEXT
    )
    """)
    # 迁移：CREATE TABLE IF NOT EXISTS 不会改已存在的表，旧库得先查表结构再决定加不加列
    cols = [row[1] for row in cur.execute("PRAGMA table_info(history)").fetchall()]
    if "engine" not in cols:
        cur.execute("ALTER TABLE history ADD COLUMN engine TEXT DEFAULT 'snownlp'")
    if "session_id" not in cols:
        cur.execute("ALTER TABLE history ADD COLUMN session_id TEXT")
        cur.execute("DROP INDEX IF EXISTS idx_history_created")   # 旧索引按 created_at 排，已经不合用了
    # 索引跟着查询条件换：先按 session_id 定位到某个人，再按 created_at 排
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_session_created "
        "ON history(session_id, created_at)"
    )
    conn.commit()
    conn.close()

def save_record(session_id, record):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO history (session_id, text, score, label, pinyin, created_at, engine) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [session_id, record["text"], record["score"], record["label"],
         record["pinyin"], record["created_at"], record.get("engine", "snownlp")],
    )
    conn.commit()
    conn.close()


def get_history(session_id, limit):
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM history WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        [session_id, limit],
    ).fetchall()
    conn.close()

    records = []
    for row in rows:
        records.append(dict(row))
    return records
