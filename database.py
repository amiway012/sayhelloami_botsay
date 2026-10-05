import sqlite3
import time

# Если настроил Volume на Railway — оставь /data/bot.db
# Локально можешь поменять на "bot.db"
DB_PATH = "/data/bot.db"


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS blocked (user_id INTEGER PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS muted (user_id INTEGER PRIMARY KEY, until INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS admins_seen (user_id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


# ---------- БЛОКИРОВКА ----------
def block_user(user_id: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO blocked (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def unblock_user(user_id: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM blocked WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def is_blocked(user_id: int) -> bool:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM blocked WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    conn.close()
    return r is not None


def get_all_blocked():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM blocked")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


# ---------- МУТ ----------
def mute_user(user_id: int, hours: int):
    until = int(time.time()) + hours * 3600
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO muted (user_id, until) VALUES (?, ?)",
        (user_id, until),
    )
    conn.commit()
    conn.close()


def unmute_user(user_id: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM muted WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_mute_until(user_id: int):
    """Возвращает timestamp окончания мута или None."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT until FROM muted WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    if row[0] <= int(time.time()):
        unmute_user(user_id)
        return None
    return row[0]


def get_all_muted():
    """Список (user_id, until), где until > сейчас."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, until FROM muted")
    rows = cur.fetchall()
    conn.close()
    now = int(time.time())
    return [(u, t) for u, t in rows if t > now]


# ---------- АДМИНЫ ----------
def mark_admin_seen(user_id: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO admins_seen (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def is_admin_seen(user_id: int) -> bool:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins_seen WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    conn.close()
    return r is not None