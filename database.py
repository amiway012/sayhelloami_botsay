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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked (
                user_id BIGINT PRIMARY KEY
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS muted (
                user_id BIGINT PRIMARY KEY,
                until BIGINT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins_seen (
                user_id BIGINT PRIMARY KEY
            )
        """)


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