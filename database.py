import os
import time
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не задан в переменных окружения!")

_pool: asyncpg.Pool | None = None


async def init_db():
    """Создаёт пул и таблицы."""
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async with _pool.acquire() as conn:
        # Блокировки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked (
                user_id BIGINT PRIMARY KEY
            )
        """)
        # Муты
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS muted (
                user_id BIGINT PRIMARY KEY,
                until BIGINT
            )
        """)
        # Админы, которые уже видели приветствие
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins_seen (
                user_id BIGINT PRIMARY KEY
            )
        """)
        # История переписки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                from_admin BOOLEAN NOT NULL,
                text TEXT,
                file_type TEXT,
                file_id TEXT,
                caption TEXT,
                ts BIGINT NOT NULL
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_ts ON messages (user_id, ts DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages (ts)"
        )


async def close_db():
    global _pool
    if _pool:
        await _pool.close()


# ---------- БЛОКИРОВКА ----------
async def block_user(user_id: int):
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO blocked (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id,
        )


async def unblock_user(user_id: int):
    async with _pool.acquire() as conn:
        await conn.execute("DELETE FROM blocked WHERE user_id = $1", user_id)


async def is_blocked(user_id: int) -> bool:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM blocked WHERE user_id = $1", user_id)
        return row is not None


async def get_all_blocked():
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM blocked")
        return [r["user_id"] for r in rows]


# ---------- МУТ ----------
async def mute_user(user_id: int, hours: int):
    until = int(time.time()) + hours * 3600
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO muted (user_id, until) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET until = EXCLUDED.until
            """,
            user_id, until,
        )


async def unmute_user(user_id: int):
    async with _pool.acquire() as conn:
        await conn.execute("DELETE FROM muted WHERE user_id = $1", user_id)


async def get_mute_until(user_id: int):
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT until FROM muted WHERE user_id = $1", user_id)
        if not row:
            return None
        if row["until"] <= int(time.time()):
            await conn.execute("DELETE FROM muted WHERE user_id = $1", user_id)
            return None
        return row["until"]


async def get_all_muted():
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, until FROM muted")
        now = int(time.time())
        return [(r["user_id"], r["until"]) for r in rows if r["until"] > now]


# ---------- АДМИНЫ ----------
async def mark_admin_seen(user_id: int):
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins_seen (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id,
        )


async def is_admin_seen(user_id: int) -> bool:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM admins_seen WHERE user_id = $1", user_id)
        return row is not None


# ---------- ИСТОРИЯ ----------
async def save_message(
    user_id: int,
    from_admin: bool,
    text: str | None,
    file_type: str | None,
    file_id: str | None,
    caption: str | None,
):
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages (user_id, from_admin, text, file_type, file_id, caption, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            user_id, from_admin, text, file_type, file_id, caption, int(time.time()),
        )


async def get_history(user_id: int, limit: int = 15):
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT from_admin, text, file_type, caption, ts
            FROM messages
            WHERE user_id = $1
            ORDER BY ts DESC
            LIMIT $2
            """,
            user_id, limit,
        )
        return list(reversed(rows))


async def cleanup_old_messages(days: int = 7) -> int:
    cutoff = int(time.time()) - days * 86400
    async with _pool.acquire() as conn:
        result = await conn.execute("DELETE FROM messages WHERE ts < $1", cutoff)
        # asyncpg возвращает строку вида "DELETE 5"
        try:
            parts = result.split()
            if len(parts) >= 2:
                return int(parts[-1])
            return 0
        except (ValueError, IndexError):
            return 0