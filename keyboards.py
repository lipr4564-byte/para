"""
Клавиатуры и текстовые шаблоны (Views) для бота Парламента Rise of Europe
"""

from html import escape
from typing import Optional
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from premium_emoji import pe, btn


# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ШАБЛОНЫ =====================

def esc(text: str) -> str:
    return escape(str(text or ""))


def _blockquote(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"


BILL_TYPES = {
    "un": {
        "name": "Резолюция ООН",
        "cost": 20,
        "majority": 50,
    },
    "mech": {
        "name": "Поправка в механики",
        "cost": 40,
        "majority": 60,
    },
    "tribunal": {
        "name": "Трибунал",
        "cost": 50,
        "majority": 66,
    },
    "poll": {
        "name": "Опрос",
        "cost": 10,
        "majority": 50,
    },
}


class Views:
    RULES_TEXT = (
        f"{pe('🌍')} <b>Положение о политических партиях и Парламенте Rise of Europe</b>\n\n"
        f"<b>Статья 1. Общие положения</b>\n"
        f"Парламент является высшим представительным и законодательным органом проекта Rise of Europe.\n\n"
        f"<b>Статья 2. Право голоса</b>\n"
        f"Голосовать могут игроки, занимающие официальные позиции (страны) и выполнившие ценз активности по РП-постам в новостнике.\n\n"
        f"<b>Статья 3. Программа партии</b>\n"
        f"Каждая партия обязана иметь программу (от 20 до 800 символов), описывающую её цели, взгляды и направления деятельности.\n\n"
        f"<b>Статья 4 и 6. Выборы в Парламент</b>\n"
        f"Всеобщие выборы проводятся периодически по истечении установленного числа вайпов. Мандаты распределяются пропорционально голосам избирателей.\n\n"
        f"<b>Статья 5. Состав и регистрация партии</b>\n"
        f"Для создания партии требуется подтверждение сооснователей и одобрение администрации проекта (@asdewrx / @Versaillee).\n\n"
        f"<b>Статья 7. Политический вес (ПВ) и прекращение деятельности</b>\n"
        f"7.1. Партии получают ПВ за РП-посты своих участников в новостнике и тратят их на выдвижение законопроектов.\n"
        f"7.2. Администрация проекта вправе лишить партию государственной регистрации или наложить Вето на законопроект."
    )

    @staticmethod
    def format_bill(bill: dict, party: Optional[dict] = None) -> str:
        binfo = BILL_TYPES.get(bill.get("category", "poll"), BILL_TYPES["poll"])
        party_str = (
            f"{party['flag']} <b>{esc(party['name'])}</b> [{esc(party['tag'])}]"
            if party else "<b>Администрация / Внепартийный</b>"
        )

        status_map = {
            "active": f"{pe('📢')} <b>Идёт голосование</b> (порог: {binfo['majority']}%)",
            "passed": f"{pe('✅')} <b>Принят Парламентом</b>",
            "rejected": f"{pe('❌')} <b>Отклонён</b>",
            "vetoed": f"{pe('👑')} <b>Наложено ВЕТО администрации</b>",
        }
        status_text = status_map.get(bill.get("status", "active"), bill.get("status", "active"))

        c_for = len(bill.get("votes_for", []))
        c_against = len(bill.get("votes_against", []))
        c_abstain = len(bill.get("votes_abstain", []))

        return (
            f"{pe('📋')} <b>Законопроект #{bill['id']} — {esc(binfo['name'])}</b>\n"
            f"─────────────────────\n"
            f"Автор: <b>{esc(bill.get('author_name', '?'))}</b> ({esc(bill.get('author_slot', '?'))})\n"
            f"Партия: {party_str}\n"
            f"Статус: {status_text}\n\n"
            f"<b>Текст законопроекта:</b>\n"
            f"{_blockquote(esc(bill.get('text', '')))}\n\n"
            f"{pe('📊')} <b>Голоса:</b> За: <b>{c_for}</b> | Против: <b>{c_against}</b> | Воздержались: <b>{c_abstain}</b>"
        )

    @staticmethod
    def format_chancellery_decree(bill: dict, party: Optional[dict] = None) -> str:
        binfo = BILL_TYPES.get(bill.get("category", "poll"), BILL_TYPES["poll"])
        party_str = (
            f"{party['flag']} <b>{esc(party['name'])}</b> [{esc(party['tag'])}]"
            if party else "<b>Администрация</b>"
        )
        c_for = len(bill.get("votes_for", []))
        c_against = len(bill.get("votes_against", []))
        c_abstain = len(bill.get("votes_abstain", []))

        return (
            f"{pe('👑')} <b>КАНЦЕЛЯРИЯ RISE OF EUROPE</b>\n"
            f"{pe('✅')} <b>Принят закон #{bill['id']} ({esc(binfo['name'])})</b>\n"
            f"─────────────────────\n"
            f"Инициатор: <b>{esc(bill.get('author_name', '?'))}</b> ({esc(bill.get('author_slot', '?'))})\n"
            f"Партия: {party_str}\n\n"
            f"<b>Постановление:</b>\n"
            f"{_blockquote(esc(bill.get('text', '')))}\n\n"
            f"Итоги голосования: За — <b>{c_for}</b>, Против — <b>{c_against}</b>, Воздержались — <b>{c_abstain}</b>."
        )


# ===================== ГЛАВНОЕ МЕНЮ =====================

def main_menu_kb(is_admin: bool = False, election_active: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("Парламент", "parl_menu", "📋"),
        btn("Партии", "party_menu", "🤝"),
    )
    builder.row(
        btn("Мой профиль", "my_profile", "📍"),
        btn("Рейтинг актива", "top_stats", "📊"),
    )
    builder.row(btn("Положение о партиях", "rules_info", "🌍"))
    if election_active:
        builder.row(btn("Выборы в Парламент", "election_menu", "👑"))
    if is_admin:
        builder.row(btn("Панель администратора", "back_admin", "🔧"))
    return builder.as_markup()


def back_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("Назад", "back_main", "🔙"))
    return builder.as_markup()


# ===================== ПАРТИИ =====================

def party_menu_kb(has_party: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("Список партий", "party_list", "📋"))
    if has_party:
        builder.row(btn("Моя партия", "party_my", "🏠"))
        builder.row(btn("Покинуть партию", "party_leave", "🚪"))
    else:
        builder.row(
            btn("Подать заявку на партию", "party_create", "✏️"),
            btn("Вступить в партию", "party_join", "🔗"),
        )
    builder.row(btn("Назад", "back_main", "🔙"))
    return builder.as_markup()


def back_party_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("Назад", "party_menu", "🔙"))
    return builder.as_markup()


def party_invite_confirm_kb(req_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("Подтвердить", f"pinv_yes_{req_id}", "✅"),
        btn("Отказаться", f"pinv_no_{req_id}", "❌"),
    )
    return builder.as_markup()


def party_admin_approve_kb(req_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("Разрешить", f"papp_yes_{req_id}", "✅"),
        btn("Запретить", f"papp_no_{req_id}", "❌"),
    )
    return builder.as_markup()


# ===================== ПАРЛАМЕНТ И ЗАКОНОПРОЕКТЫ =====================

def parliament_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("Активные голосования", "bills_active", "📢"))
    builder.row(btn("Архив Канцелярии", "bills_archive", "📋"))
    builder.row(btn("Выдвинуть законопроект", "bill_propose", "✏️"))
    builder.row(btn("Назад", "back_main", "🔙"))
    return builder.as_markup()


def bill_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("Резолюция ООН", "btype_un", "🌍"))
    builder.row(btn("Поправка в механики", "btype_mech", "🔧"))
    builder.row(btn("Трибунал", "btype_tribunal", "⚔️"))
    builder.row(btn("Опрос", "btype_poll", "📊"))
    builder.row(btn("Назад", "parl_menu", "🔙"))
    return builder.as_markup()


def bill_vote_kb(bill: dict) -> InlineKeyboardMarkup:
    bid = bill["id"]
    c_for = len(bill.get("votes_for", []))
    c_against = len(bill.get("votes_against", []))
    c_abstain = len(bill.get("votes_abstain", []))

    builder = InlineKeyboardBuilder()
    if bill.get("status") == "active":
        builder.row(
            btn(f"За ({c_for})", f"vote_{bid}_for", "✅"),
            btn(f"Против ({c_against})", f"vote_{bid}_against", "❌"),
        )
        builder.row(
            btn(f"Воздержаться ({c_abstain})", f"vote_{bid}_abstain", "🤝"),
            btn("Список голосов", f"votes_list_{bid}", "👥"),
        )
        builder.row(
            btn("Подвести итог", f"bill_finish_{bid}", "🎯"),
            btn("Вето", f"bill_veto_{bid}", "👑"),
        )
    else:
        builder.row(btn("Список голосов", f"votes_list_{bid}", "👥"))
    return builder.as_markup()


# ===================== АДМИН-ПАНЕЛЬ =====================

def admin_panel_kb(status: str = "on") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🔄 Синхронизировать страны", "admin_sync"))
    builder.row(btn("📋 Список пользователей", "admin_users"))
    builder.row(btn("📢 Рассылка", "admin_broadcast"))
    builder.row(btn("🔧 Управление пользователем", "admin_user_manage"))
    builder.row(btn("🤝 Управление партиями", "admin_parties"))
    builder.row(btn("👑 Законопроекты и Вето", "admin_bills"))
    builder.row(btn("🗳 Выборы и Вайпы", "admin_elections"))
    builder.row(btn("⚙️ Настройки лимитов", "admin_settings"))
    builder.row(btn("📊 Статистика", "admin_stats"))
    builder.row(btn("📜 Посмотреть логи", "admin_logs"))
    builder.row(btn("⚠️ Сбросить сезон", "admin_wipe"))

    if status == "on":
        builder.row(btn("🛑 Выключить бота", "admin_shutdown"))
    else:
        builder.row(btn("✅ Включить бота", "admin_start_bot"))

    return builder.as_markup()


def admin_settings_kb(st: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("-1", "set_pmin_mem_dec"),
        btn(f"Мин. в партии: {st['min_party_members']}", "noop"),
        btn("+1", "set_pmin_mem_inc"),
    )
    builder.row(
        btn("-1", "set_pmax_dec"),
        btn(f"Макс. в партии: {st['max_party_members']}", "noop"),
        btn("+1", "set_pmax_inc"),
    )
    builder.row(
        btn("-1", "set_pmin_dec"),
        btn(f"Постов для голоса: {st['min_posts_to_vote']}", "noop"),
        btn("+1", "set_pmin_inc"),
    )
    builder.row(
        btn("-1", "set_wipes_dec"),
        btn(f"Вайпов до выборов: {st['wipes_per_election']}", "noop"),
        btn("+1", "set_wipes_inc"),
    )
    builder.row(btn("🔙 В админ-панель", "back_admin"))
    return builder.as_markup()


def back_to_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(btn("🔙 В админ-панель", "back_admin"))
    return builder.as_markup()