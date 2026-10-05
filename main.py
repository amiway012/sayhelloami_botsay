import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
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


# ---------- КЛАВИАТУРЫ ----------
def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Заблокировать", callback_data="admin:block")
    kb.button(text="✅ Разблокировать", callback_data="admin:unblock")
    kb.button(text="📋 Список заблокированных", callback_data="admin:list")
    kb.adjust(1)
    return kb.as_markup()


# ---------- УВЕДОМЛЕНИЕ ПРИ СТАРТЕ ----------
async def on_startup(bot: Bot):
    print("Бот запущен...")
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, "✅ Бот запущен и готов к работе")
        except Exception as e:
            logging.warning(f"Не смог уведомить админа {admin_id}: {e}")


dp.startup.register(on_startup)


# ---------- ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ ----------
@router.message(CommandStart())
async def cmd_start(message: Message):
    if db.is_blocked(message.from_user.id):
        return
    await message.answer("Привет! Напиши что тебе нужно, и жди ответа.
say hello?")


@router.message(F.text & ~F.text.startswith("/"))
async def silent_handler(message: Message):
    # Заблокированным — молчим совсем
    if db.is_blocked(message.from_user.id):
        return

    # Пересылаем сообщение всем админам
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
            await bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception as e:
            logging.warning(f"Не смог переслать админу {admin_id}: {e}")


# ---------- АДМИН-ПАНЕЛЬ ----------
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("🛠 Админ-панель", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:block")
async def admin_block_start(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.answer(
        "Отправь ID пользователя для блокировки.\n"
        "Пример: `123456789`",
        parse_mode="Markdown",
    )
    await call.answer()


@router.callback_query(F.data == "admin:unblock")
async def admin_unblock_start(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.answer(
        "Отправь ID пользователя для разблокировки.\n"
        "Пример: `123456789`",
        parse_mode="Markdown",
    )
    await call.answer()


@router.callback_query(F.data == "admin:list")
async def admin_list(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Нет доступа", show_alert=True)
        return
    blocked = db.get_all_blocked()
    if not blocked:
        await call.message.answer("Список заблокированных пуст.")
    else:
        text = "🚫 Заблокированные ID:\n" + "\n".join(f"• `{uid}`" for uid in blocked)
        await call.message.answer(text, parse_mode="Markdown")
    await call.answer()


# ---------- ОБРАБОТКА ID ОТ АДМИНА ----------
@router.message(F.text.regexp(r"^\d+$"))
async def admin_id_input(message: Message):
    if message.from_user.id not in ADMINS:
        return

    user_id = int(message.text)

    if db.is_blocked(user_id):
        db.unblock_user(user_id)
        await message.answer(
            f"✅ Пользователь `{user_id}` разблокирован.",
            parse_mode="Markdown",
        )
    else:
        db.block_user(user_id)
        await message.answer(
            f"🚫 Пользователь `{user_id}` заблокирован.",
            parse_mode="Markdown",
        )


# ---------- ЗАПУСК ----------
async def main():
    db.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())