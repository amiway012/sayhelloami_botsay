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
FLOOD_LIMIT = 5
FLOOD_WINDOW = 10
FLOOD_COOLDOWN = 10 * 60

_user_messages = defaultdict(deque)
_user_muted_until = {}


def check_flood(user_id: int) -> str:
    now = time.time()

    if user_id in _user_muted_until:
        if now < _user_muted_until[user_id]:
            return "ignoring"
        else:
            del _user_muted_until[user_id]

    q = _user_messages[user_id]
    while q and now - q[0] > FLOOD_WINDOW:
        q.popleft()
    q.append(now)

    if len(q) >= FLOOD_LIMIT:
        _user_muted_until[user_id] = now + FLOOD_COOLDOWN
        q.clear()
        return "trigger"

    return "ok"


# ---------- СОСТОЯНИЯ ----------
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
    kb.button(text="📜 История", callback_data=f"history:{user_id}")
    kb.adjust(2, 2)
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


def make_caption(header: str, message: Message) -> str:
    caption = message.caption or ""
    full = f"{header}\n\n{caption}" if caption else header
    return full[:1024]


def extract_content(message: Message):
    if message.text:
        return "text", None, None, message.text
    if message.photo:
        return "photo", message.photo[-1].file_id, message.caption, None
    if message.voice:
        return "voice", message.voice.file_id, message.caption, None
    if message.video:
        return "video", message.video.file_id, message.caption, None
    if message.document:
        return "document", message.document.file_id, message.caption, None
    if message.audio:
        return "audio", message.audio.file_id, message.caption, None
    if message.video_note:
        return "video_note", message.video_note.file_id, None, None
    if message.sticker:
        return "sticker", message.sticker.file_id, None, None
    return None, None, None, None


# ---------- STARTUP / SHUTDOWN ----------
_cleanup_task: asyncio.Task | None = None


async def cleanup_task():
    while True:
        try:
            deleted = await db.cleanup_old_messages(days=7)
            if deleted:
                logging.info(f"Очистка истории: удалено {deleted} сообщений старше 7 дней")
        except Exception as e:
            logging.error(f"Очистка не удалась: {e}")
        await asyncio.sleep(24 * 3600)


async def on_startup(bot: Bot):
    global _cleanup_task
    await db.init_db()
    _cleanup_task = asyncio.create_task(cleanup_task())
    print("🚀 VERSION 4.0 FLOOD-FIX")
    print(f"Бот запущен... ADMINS = {ADMINS}")


async def on_shutdown(bot: Bot):
    global _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    await db.close_db()
    print("Бот остановлен.")


dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)


# ============================================================
#  FSM-ОБРАБОТЧИКИ
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
        if message.text:
            await bot.send_message(target, f"📨 Ответ:\n\n{message.text}")
            await db.save_message(target, True, message.text, None, None, None)

        elif message.photo:
            await bot.send_photo(
                target, message.photo[-1].file_id,
                caption="📨 Ответ:" + ("\n\n" + message.caption if message.caption else ""),
            )
            await db.save_message(target, True, None, "photo", message.photo[-1].file_id, message.caption)

        elif message.voice:
            await bot.send_voice(
                target, message.voice.file_id,
                caption="📨 Ответ:" + ("\n\n" + message.caption if message.caption else ""),
            )
            await db.save_message(target, True, None, "voice", message.voice.file_id, message.caption)

        elif message.video:
            await bot.send_video(
                target, message.video.file_id,
                caption="📨 Ответ:" + ("\n\n" + message.caption if message.caption else ""),
            )
            await db.save_message(target, True, None, "video", message.video.file_id, message.caption)

        elif message.document:
            await bot.send_document(
                target, message.document.file_id,
                caption="📨 Ответ:" + ("\n\n" + message.caption if message.caption else ""),
            )
            await db.save_message(target, True, None, "document", message.document.file_id, message.caption)

        elif message.audio:
            await bot.send_audio(
                target, message.audio.file_id,
                caption="📨 Ответ:" + ("\n\n" + message.caption if message.caption else ""),
            )
            await db.save_message(target, True, None, "audio", message.audio.file_id, message.caption)

        elif message.video_note:
            await bot.send_video_note(target, message.video_note.file_id)
            await db.save_message(target, True, None, "video_note", message.video_note.file_id, None)

        elif message.sticker:
            await bot.send_sticker(target, message.sticker.file_id)
            await db.save_message(target, True, None, "sticker", message.sticker.file_id, None)

        else:
            await message.answer("⚠️ Такой тип сообщения не поддерживается.")
            return

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
#  КОМАНДЫ
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id

    if user_id in ADMINS:
        if await db.is_admin_seen(user_id):
            await message.answer("С возвращением, я вас ждал!")
        else:
            await message.answer("Привет, рады видеть вас!")
            await db.mark_admin_seen(user_id)

        await message.answer("🛠 Админ-панель", reply_markup=admin_menu())
        return

    if await db.is_blocked(user_id):
        return

    mute_until = await db.get_mute_until(user_id)
    if mute_until:
        remaining = mute_until - int(time.time())
        await message.answer(f"⏳ Вы замучены. Осталось: {human_time(remaining)}")
        return

    await message.answer("Привет! пиши что тебе нужно, скоро тебя ответят...")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("🛠 Админ-панель", reply_markup=admin_menu())


# ============================================================
#  УВЕДОМЛЕНИЕ АДМИНАМ
# ============================================================

async def notify_admins(message: Message):
    user = message.from_user
    username = f"@{user.username}" if user.username else "без юзернейма"
    header = f"📩 От: {user.full_name} ({username})\nID: {user.id}"
    kb = user_message_kb(user.id)

    for admin_id in ADMINS:
        try:
            if message.text:
                await bot.send_message(
                    admin_id,
                    f"📩 Новое сообщение\nОт: {user.full_name} ({username})\nID: `{user.id}`\n\n{message.text}",
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            elif message.photo:
                await bot.send_photo(
                    admin_id, message.photo[-1].file_id,
                    caption=make_caption(f"📩 Фото\n{header}", message),
                    reply_markup=kb,
                )
            elif message.voice:
                await bot.send_voice(
                    admin_id, message.voice.file_id,
                    caption=make_caption(f"📩 Голосовое\n{header}", message),
                    reply_markup=kb,
                )
            elif message.video:
                await bot.send_video(
                    admin_id, message.video.file_id,
                    caption=make_caption(f"📩 Видео\n{header}", message),
                    reply_markup=kb,
                )
            elif message.document:
                await bot.send_document(
                    admin_id, message.document.file_id,
                    caption=make_caption(f"📩 Документ\n{header}", message),
                    reply_markup=kb,
                )
            elif message.audio:
                await bot.send_audio(
                    admin_id, message.audio.file_id,
                    caption=make_caption(f"📩 Аудио\n{header}", message),
                    reply_markup=kb,
                )
            elif message.video_note:
                await bot.send_message(admin_id, f"📩 Видео-кружок\n{header}", reply_markup=kb)
                await bot.send_video_note(admin_id, message.video_note.file_id)
            elif message.sticker:
                await bot.send_message(admin_id, f"📩 Стикер\n{header}", reply_markup=kb)
                await bot.send_sticker(admin_id, message.sticker.file_id)
        except Exception as e:
            logging.warning(f"Не смог отправить админу {admin_id}: {e}")


# ============================================================
#  ЛОВУШКА
# ============================================================

@router.message()
async def silent_handler(message: Message):
    if message.from_user is None:
        return

    if message.text and message.text.startswith("/"):
        return

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

    flood_status = check_flood(user_id)

    if flood_status == "ignoring":
        return

    if flood_status == "trigger":
        user = message.from_user
        username = f"@{user.username}" if user.username else "без юзернейма"

        try:
            await message.answer("⚠️ Слишком много сообщений. Подождите 10 минут.")
        except Exception:
            pass

        warning = (
            f"⚠️ Антифлуд сработал\n"
            f"От: {user.full_name} ({username})\n"
            f"ID: `{user.id}`\n"
            f"Отправляет слишком много сообщений.\n"
            f"Игнорируем на 10 минут."
        )
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id, warning,
                    parse_mode="Markdown",
                    reply_markup=user_message_kb(user.id),
                )
            except Exception as e:
                logging.warning(f"Антифлуд: не смог уведомить {admin_id}: {e}")
        return

    file_type, file_id, caption, text = extract_content(message)
    try:
        await db.save_message(user_id, False, text, file_type, file_id, caption)
    except Exception as e:
        logging.warning(f"Не смог сохранить сообщение в историю: {e}")

    await notify_admins(message)


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
        new_text = (call.message.text or call.message.caption or "") + "\n\n🚫 Заблокирован"
        if call.message.caption is not None:
            await call.message.edit_caption(caption=new_text[:1024], reply_markup=None)
        else:
            await call.message.edit_text(new_text, reply_markup=None)
    except Exception as e:
        logging.warning(f"Не смог отредактировать сообщение: {e}")

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


@router.callback_query(F.data.startswith("history:"))
async def cb_history(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return

    user_id = int(call.data.split(":")[1])
    messages = await db.get_history(user_id, limit=15)

    if not messages:
        await call.message.answer("📜 История пуста.")
        await call.answer()
        return

    lines = [f"📜 История с {user_id}:", ""]
    for m in messages:
        who = "👤 Админ" if m["from_admin"] else "🙋 Юзер"
        content = m["text"] or m["caption"] or f"[{m['file_type']}]"
        if len(content) > 80:
            content = content[:80] + "…"
        ts = time.strftime("%d.%m %H:%M", time.localtime(m["ts"]))
        lines.append(f"{who} ({ts}): {content}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n…"

    await call.message.answer(text)
    await call.answer()


# ============================================================
#  АДМИН-ПАНЕЛЬ (callback-кнопки)
# ============================================================

@router.callback_query(F.data == "admin:blocked_list")
async def admin_blocked_list(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return

    blocked = await db.get_all_blocked()
    if not blocked:
        await call.message.answer("Список пуст.")
    else:
        joined = "\n".join("• " + str(uid) for uid in blocked)
        await call.message.answer("🚫 Заблокированные ID:\n" + joined)
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
        lines = []
        for uid, until in muted:
            lines.append("• " + str(uid) + " — осталось " + human_time(until - now))
        await call.message.answer("🔇 Замученные:\n" + "\n".join(lines))