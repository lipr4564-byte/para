"""
Главный файл запуска бота Парламента Rise of Europe
"""

import asyncio
import os

from aiogram import Bot, Dispatcher, Router, BaseMiddleware
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.filters.chat_member_updated import MEMBER, LEFT, KICKED
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType

from config import BOT_TOKEN, GROUP_ID, LOG_CHAT_ID
from database import (
    init_db, close_db, get_setting, is_owner,
    sync_slots_from_reg_file, leave_or_remove_from_party
)
from admin import router as admin_router
from parliament import router as parl_router
from logger import log, send_log


class BotStatusMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = None
        chat = None

        if isinstance(event, Message):
            user = event.from_user
            chat = event.chat
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            chat = event.message.chat if event.message else None
        else:
            return await handler(event, data)

        if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            if chat.id not in (GROUP_ID, LOG_CHAT_ID):
                return

        if user and await is_owner(user):
            return await handler(event, data)

        status = await get_setting("bot_status")
        if status == "off":
            if isinstance(event, Message) and chat and chat.type == ChatType.PRIVATE:
                await event.answer(
                    "🔧 <b>Бот временно отключён на техническое обслуживание.</b>\n\nМы скоро вернёмся!",
                    parse_mode="HTML"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("🔧 Бот на техобслуживании", show_alert=True)
            return

        return await handler(event, data)


leave_router = Router()


@leave_router.chat_member(
    ChatMemberUpdatedFilter(member_status_changed=MEMBER >> (LEFT | KICKED))
)
async def on_user_left(event: ChatMemberUpdated, bot: Bot):
    if event.chat.id != GROUP_ID:
        return

    user = event.new_chat_member.user
    removed_party = await leave_or_remove_from_party(user.id)
    if removed_party:
        await send_log(
            bot,
            f"🚪 <b>Выход участника партии из группы</b>\n\n"
            f"👤 <code>{user.full_name}</code> | @{user.username or 'нет'} | ID: <code>{user.id}</code>\n"
            f"🏛 Исключён из партии: <b>{removed_party}</b>"
        )


async def on_startup(bot: Bot):
    log.info("Инициализация SQLite (WAL, миграции, индексы)...")
    os.makedirs("data", exist_ok=True)
    await init_db()

    synced = await sync_slots_from_reg_file()
    if synced:
        log.info(f"Синхронизировано {synced} позиций из базы @RegistrationROEbot")

    try:
        chat = await bot.get_chat(GROUP_ID)
        log.info(f"Группа проекта найдена: {chat.title} (ID: {GROUP_ID})")
    except Exception as e:
        log.error(f"Не удалось подключиться к группе {GROUP_ID}: {e}")

    me = await bot.get_me()
    log.info(f"Бот Парламента @{me.username} запущен!")


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(BotStatusMiddleware())
    dp.callback_query.middleware(BotStatusMiddleware())

    dp.include_router(leave_router)
    dp.include_router(admin_router)
    dp.include_router(parl_router)

    dp.startup.register(on_startup)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_member"],
            drop_pending_updates=True
        )
    finally:
        await close_db()
        await bot.session.close()
        log.info("Бот и соединение с БД корректно остановлены")


if __name__ == "__main__":
    asyncio.run(main())