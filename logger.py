"""
Логгирование действий в чат и в консоль
"""

import logging
import os
from datetime import datetime
from aiogram import Bot
from config import LOG_CHAT_ID, DATA_DIR

os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("data/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("ROE_Parliament")


def _ts() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


async def send_log(bot: Bot, text: str):
    """Отправить лог в группу логов"""
    try:
        await bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=f"📋 <b>[Лог]</b> <code>{_ts()}</code>\n\n{text}",
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Ошибка отправки лога: {e}")


async def log_start(bot: Bot, user_id: int, username: str, full_name: str):
    msg = (
        f"🟢 <b>Запуск бота</b>\n"
        f"👤 <code>{full_name}</code> | @{username or 'нет'} | ID: <code>{user_id}</code>"
    )
    log.info(f"START: {full_name} (@{username}) [{user_id}]")
    await send_log(bot, msg)


async def log_post_counted(bot: Bot, user_id: int, username: str, full_name: str, slot_name: str, posts: int, party_name: str = None, pts: int = 0):
    party_line = f"\n💎 Партия: <b>{party_name}</b> (+{pts} ПВ)" if party_name else ""
    msg = (
        f"✍️ <b>Засчитан пост в новостнике</b>\n"
        f"👤 <code>{full_name}</code> | @{username or 'нет'} | ID: <code>{user_id}</code>\n"
        f"📍 Позиция: <b>{slot_name}</b>\n"
        f"📊 Постов: <code>{posts}</code>{party_line}"
    )
    log.info(f"POST: {full_name} [{user_id}] -> posts={posts}")
    await send_log(bot, msg)


async def log_party_created(bot: Bot, user_id: int, username: str, full_name: str, party_name: str, tag: str):
    msg = (
        f"🤝 <b>Создание партии</b>\n"
        f"👤 <code>{full_name}</code> | @{username or 'нет'} | ID: <code>{user_id}</code>\n"
        f"🏛 Партия: <b>{party_name}</b> [{tag}]"
    )
    log.info(f"PARTY CREATE: {party_name} [{tag}] by {user_id}")
    await send_log(bot, msg)


async def log_bill_created(bot: Bot, user_id: int, username: str, full_name: str, bill_id: str, category: str):
    msg = (
        f"📢 <b>Новый законопроект #{bill_id}</b>\n"
        f"👤 <code>{full_name}</code> | @{username or 'нет'} | ID: <code>{user_id}</code>\n"
        f"📋 Тип: <b>{category}</b>"
    )
    log.info(f"BILL #{bill_id}: by {user_id} ({category})")
    await send_log(bot, msg)


async def log_broadcast(bot: Bot, admin_id: int, text: str, count: int):
    msg = (
        f"📢 <b>Рассылка</b>\n"
        f"Admin ID: <code>{admin_id}</code>\n"
        f"Текст: {text[:100]}...\n"
        f"Отправлено: <code>{count}</code> пользователям"
    )
    log.info(f"BROADCAST by {admin_id}: {count} users")
    await send_log(bot, msg)