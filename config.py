"""
Безопасная конфигурация проекта.
Все секретные данные и ID загружаются из .env или переменных окружения хостинга.
"""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_int_env(key: str, default: int) -> int:
    val = os.getenv(key, str(default)).strip()
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"Критическая ошибка: переменная {key} в .env должна быть числом!")


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_username: str
    co_admin_username: str
    owner_id: int
    group_id: int
    reg_topic_id: int
    news_topic_id: int
    chancellery_topic_id: int
    log_chat_id: int
    reg_bot_id: int
    reg_bot_db_path: str
    data_dir: str
    sqlite_path: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or ":" not in token:
        raise ValueError(
            "Критическая ошибка: переменная окружения BOT_TOKEN не установлена! "
            "Проверьте файл .env или настройки переменных на хостинге."
        )

    data_dir = os.getenv("DATA_DIR", "data").strip()
    os.makedirs(data_dir, exist_ok=True)

    return Config(
        bot_token=token,
        owner_username=os.getenv("OWNER_USERNAME", "asdewrx").strip().lstrip("@"),
        co_admin_username=os.getenv("CO_ADMIN_USERNAME", "Versaillee").strip().lstrip("@"),
        owner_id=_get_int_env("OWNER_ID", 0),
        group_id=_get_int_env("GROUP_ID", -1003410277945),
        reg_topic_id=_get_int_env("REG_TOPIC_ID", 1376529),
        news_topic_id=_get_int_env("NEWS_TOPIC_ID", 1376336),
        chancellery_topic_id=_get_int_env("CHANCELLERY_TOPIC_ID", 2010433),
        log_chat_id=_get_int_env("LOG_CHAT_ID", -5288630698),
        reg_bot_id=_get_int_env("REG_BOT_ID", 8813857960),
        reg_bot_db_path=os.getenv("REG_BOT_DB_PATH", "../data/db.json").strip(),
        data_dir=data_dir,
        sqlite_path=os.path.join(data_dir, "parliament.db"),
    )


CFG = load_config()

# Экспорт констант для модулей
BOT_TOKEN = CFG.bot_token
OWNER_USERNAME = CFG.owner_username
CO_ADMIN_USERNAME = CFG.co_admin_username
OWNER_ID = CFG.owner_id
GROUP_ID = CFG.group_id
REG_TOPIC_ID = CFG.reg_topic_id
NEWS_TOPIC_ID = CFG.news_topic_id
CHANCELLERY_TOPIC_ID = CFG.chancellery_topic_id
LOG_CHAT_ID = CFG.log_chat_id
REG_BOT_ID = CFG.reg_bot_id
REG_BOT_DB_PATH = CFG.reg_bot_db_path
DATA_DIR = CFG.data_dir
SQLITE_PATH = CFG.sqlite_path