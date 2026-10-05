import sqlite3

DB_PATH = "bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocked (
            user_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()

def block_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO blocked (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def unblock_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM blocked WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_blocked(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM blocked WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result is not None

def get_all_blocked():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM blocked")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]
