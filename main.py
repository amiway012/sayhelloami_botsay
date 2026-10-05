import asyncio
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, ADMINS
import database as db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ---------- АНТИФЛУД ----------
FLOOD_LIMIT = 5          # сколько сообщений
FLOOD_WINDOW = 10        # за сколько секунд
FLOOD_COOLDOWN = 30      # на сколько секунд затыкаем

_user_messages = defaultdict(deque)
_user_muted_until = {}


def check_flood(user_id: int) -> bool:
    """True, если юзер флудит."""
    now = time.time()

    if user_id in _user_muted_until:
        if now < _user_muted_until[user_id]:
            return True
        else:
            del _user_muted_until[user_id]

    q = _user_messages[user_id]
    while q and now - q[0] > FLOOD_WINDOW:
        q.popleft()
    q.append(now)

    if len(q) >= FLOOD_LIMIT:
        _user_muted_until[user_id] = now + FLOOD_COOLDOWN
        q.clear()
        return True

    return False


# ---------- СОСТОЯНИЯ (FSM) ----------
class ReplyState(StatesGroup):
    waiting_for_message = State()


class MuteState(StatesGroup):
    waiting_for_hours = State()


class UnblockState(StatesGroup):
    waiting_for_user_id = State()


class UnmuteState(StatesGroup):
    waiting_for_user_id = State()


# ---------- КЛАВИАТУРЫ ----------
def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Заблокированные", callback_data="admin:blocked_list")
    kb.button(text="🔇 Замученные", callback_data="admin:muted_list")
    kb.button(text="✅ Разблокировать по ID", callback_data="admin:unblock")
    kb.button(text="🔊 Размутить по ID", callback_data="admin:unmute")
    kb.adjust(1)
    return kb.as_markup()


def user_message_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Заблокировать", callback_data=f"block:{user_id}")
    kb.button(text="🔇 Замутить", callback_data=f"mute:{user_id}")
    kb.button(text="Ответить📝", callback_data=f"reply:{user_id}")
    kb.adjust(1)
    return kb.as_markup()


def human_time(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    parts = []
    if h:
        parts.append(f"{h}ч")
    if m or not parts:
        parts.append(f"{m}м")
    return " ".join(parts)


# ---------- STARTUP / SHUTDOWN ----------
async def on_startup(bot: Bot):
    await db.init_db()
    print(f"Бот запущен... ADMINS = {ADMINS}")


async def on_shutdown(bot: Bot):
    await db.close_db()
    print("Бот остановлен.")


dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)


# ============================================================
#  FSM-ОБРАБОТЧИКИ (регистрируем ПЕРВЫМИ)
# ============================================================

@router.message(ReplyState.waiting_for_message)
async def handle_admin_reply(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    data = await state.get_data()
    target = data.get("target_user_id")
    await state.clear()

    if not target:
        await message.answer("⚠️ Не найден получатель. Попробуй снова.")
        return

    try:
        await bot.send_message(target, f"📨 Ответ:\n\n{message.text}")
        await message.answer("✅ Сообщение отправлено.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить: {e}")


@router.message(MuteState.waiting_for_hours)
async def handle_mute_hours(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    if not message.text or not message.text.isdigit():
        await message.answer("Отправь число часов, например: 24")
        return

    hours = int(message.text)
    data = await state.get_data()
    target = data.get("target_user_id")
    await state.clear()

    if not target:
        await message.answer("⚠️ Не найден пользователь.")
        return

    await db.mute_user(target, hours)

    try:
        await bot.send_message(target, f"⏳ Вы замучены на {hours} ч.")
    except Exception:
        pass

    await message.answer(
        f"🔇 Пользователь `{target}` замучен на {hours} ч.",
        parse_mode="Markdown",
    )


@router.message(UnblockState.waiting_for_user_id)
async def handle_unblock(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    if not message.text or not message.text.isdigit():
        await message.answer("Отправь числовой ID.")
        return

    user_id = int(message.text)
    await state.clear()

    if not await db.is_blocked(user_id):
        await message.answer(f"Пользователь `{user_id}` не в блоке.", parse_mode="Markdown")
        return

    await db.unblock_user(user_id)

    try:
        await bot.send_message(user_id, "✅ Вы были разблокированы.")
    except Exception:
        pass

    await message.answer(f"✅ `{user_id}` разблокирован.", parse_mode="Markdown")


@router.message(UnmuteState.waiting_for_user_id)
async def handle_unmute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    if not message.text or not message.text.isdigit():
        await message.answer("Отправь числовой ID.")
        return

    user_id = int(message.text)
    await state.clear()

    if not await db.get_mute_until(user_id):
        await message.answer(f"Пользователь `{user_id}` не в муте.", parse_mode="Markdown")
        return

    await db.unmute_user(user_id)

    try:
        await bot.send_message(user_id, "✅ Мут снят.")
    except Exception:
        pass

    await message.answer(f"🔊 `{user_id}` размучен.", parse_mode="Markdown")


# ============================================================
#  /start
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id

    # --- АДМИН ---
    if user_id in ADMINS:
        if await db.is_admin_seen(user_id):
            await message.answer("С возвращением, я вас ждал!")
        else:
            await message.answer("Привет, рады видеть вас!")
            await db.mark_admin_seen(user_id)

        await message.answer("🛠 Админ-панель", reply_markup=admin_menu())
        return

    # --- ЗАБЛОКИРОВАННЫЙ ---
    if await db.is_blocked(user_id):
        return

    # --- ЗАМУЧЕННЫЙ ---
    mute_until = await db.get_mute_until(user_id)
    if mute_until:
        remaining = mute_until - int(time.time())
        await message.answer(f"⏳ Вы замучены. Осталось: {human_time(remaining)}")
        return

    # --- ОБЫЧНЫЙ ЮЗЕР ---
    await message.answer("Привет! пиши что тебе нужно, скоро тебя ответят...")


# ============================================================
#  ВХОДЯЩИЕ СООБЩЕНИЯ
# ============================================================

@router.message(F.text & ~F.text.startswith("/"))
async def silent_handler(message: Message):
    user_id = message.from_user.id

    if user_id in ADMINS:
        return

    if await db.is_blocked(user_id):
        return

    mute_until = await db.get_mute_until(user_id)
    if mute_until:
        remaining = mute_until - int(time.time())
        await message.answer(f"⏳ Вы замучены. Осталось: {human_time(remaining)}")
        return

    # ---------- АНТИФЛУД ----------
    if check_flood(user_id):
        user = message.from_user
        username = f"@{user.username}" if user.username else "без юзернейма"
        warning = (
            f"⚠️ Антифлуд сработал\n"
            f"От: {user.full_name} ({username})\n"
            f"ID: `{user.id}`\n"
            f"Больше {FLOOD_LIMIT} сообщений за {FLOOD_WINDOW} сек.\n"
            f"Игнорируем на {FLOOD_COOLDOWN} сек."
        )
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    warning,
                    parse_mode="Markdown",
                    reply_markup=user_message_kb(user.id),
                )
            except Exception as e:
                logging.warning(f"Антифлуд: не смог уведомить {admin_id}: {e}")
        return
    # ---------- /АНТИФЛУД ----------

    user = message.from_user
    username = f"@{user.username}" if user.username else "без юзернейма"
    text = (
        f"📩 Новое сообщение\n"
        f"От: {user.full_name} ({username})\n"
        f"ID: `{user.id}`\n\n"
        f"{message.text}"
    )

    for admin_id in ADMINS:
        try:
            await bot.send_message(
                admin_id,
                text,
                parse_mode="Markdown",
                reply_markup=user_message_kb(user.id),
            )
        except Exception as e:
            logging.warning(f"Не смог переслать админу {admin_id}: {e}")


# ============================================================
#  ИНЛАЙН-КНОПКИ
# ============================================================

@router.callback_query(F.data.startswith("block:"))
async def cb_block(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return

    user_id = int(call.data.split(":")[1])

    if await db.is_blocked(user_id):
        await call.answer("Уже заблокирован", show_alert=True)
        return

    await db.block_user(user_id)

    try:
        await bot.send_message(user_id, "Вы были заблокированы⛔")
    except Exception as e:
        logging.warning(f"Не смог уведомить юзера {user_id}: {e}")

    try:
        new_text = (call.message.text or "") + "\n\n🚫 Заблокирован"
        await call.message.edit_text(new_text, reply_markup=None)
    except Exception as e:
        logging.warning(f"edit_text failed: {e}")

    await call.answer(f"Пользователь {user_id} заблокирован")


@router.callback_query(F.data.startswith("mute:"))
async def cb_mute(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return

    user_id = int(call.data.split(":")[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(MuteState.waiting_for_hours)
    await call.message.answer(
        f"На сколько часов замутить `{user_id}`?\n"
        f"Отправь число, например: `24`",
        parse_mode="Markdown",
    )
    await call.answer()


@router.callback_query(F.data.startswith("reply:"))
async def cb_reply(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return

    user_id = int(call.data.split(":")[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(ReplyState.waiting_for_message)
    await call.message.answer("Напишите сообщение!")
    await call.answer()


# ============================================================
#  АДМИН-ПАНЕЛЬ
# ============================================================

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("🛠 Админ-панель", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:blocked_list")
async def admin_blocked_list(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return

    blocked = await db.get_all_blocked()
    if not blocked:
        await call.message.answer("Список пуст.")
    else:
        text = "🚫 Заблокированные ID:\n" + "\n".join(f"• `{uid}`" for uid in blocked)
        await call.message.answer(text, parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data == "admin:muted_list")
async def admin_muted_list(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return

    muted = await db.get_all_muted()
    if not muted:
        await call.message.answer("Список пуст.")
    else:
        now = int(time.time())
        lines = [f"• `{uid}` — осталось {human_time(until - now)}" for uid, until in muted]
        await call.message.answer("🔇 Замученные:\n" + "\n".join(lines), parse_mode="Markdown")
    await call.answer()


@router.callback_query(F.data == "admin:unblock")
async def admin_unblock_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(UnblockState.waiting_for_user_id)
    await call.message.answer("Отправь ID для разблокировки.")
    await call.answer()


@router.callback_query(F.data == "admin:unmute")
async def admin_unmute_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(UnmuteState.waiting_for_user_id)
    await call.message.answer("Отправь ID для снятия мута.")
    await call.answer()


# ---------- ЗАПУСК ----------
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())