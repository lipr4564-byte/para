"""
Слой представления (Presentation Layer):
Отвечает исключительно за построение инлайн-клавиатур и форматирование HTML-шаблонов.
"""

from html import escape
from typing import Optional
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from premium_emoji import btn, pe


def esc(text: str) -> str:
    return escape(str(text))


def _blockquote(content: str) -> str:
    return f"<blockquote>{content}</blockquote>"


BILL_TYPES = {
    "un": {"name": "Резолюция ООН", "cost": 20, "majority": 51},
    "mech": {"name": "Поправка в механики", "cost": 40, "majority": 65},
    "tribunal": {"name": "Трибунал", "cost": 80, "majority": 75},
    "poll": {"name": "Опрос", "cost": 10, "majority": 51},
}


# ===================== ШАБЛОНЫ СООБЩЕНИЙ (VIEWS) =====================

class Views:
    RULES_TEXT = (
        f"{pe('🌍')} <b>Положение о партиях и избирательном процессе Rise Of Europe</b>\n"
        f"<i>Авторство: @Versaillee</i>\n\n"
        f"<b>Статья 1. Регистрация политических партий</b>\n"
        f"{_blockquote('1.1. Создание и регистрация политической партии осуществляются исключительно с согласия администрации проекта (@asdewrx / @Versaillee).\n1.2. Для подачи заявки на регистрацию необходимо обратиться к ответственному представителю администрации: @asdewrx / @Versaillee; отказ можно получить без причины.')}\n\n"
        f"<b>Статья 2. Руководство партии</b>\n"
        f"{_blockquote('2.1. Каждая зарегистрированная партия обязана иметь избранного или назначенного председателя (главу партии).\n2.2. Глава партии несёт ответственность за её внутреннюю организацию, представительство и соблюдение установленных правил.')}\n\n"
        f"<b>Статья 3. Программа</b>\n"
        f"{_blockquote('3.1. Каждая партия обязана иметь собственную программу развития.\n3.2. Программа должна содержать основные взгляды, цели, принципы и предполагаемые направления деятельности партии.')}\n\n"
        f"<b>Статья 4. Избирательный процесс</b>\n"
        f"{_blockquote('4.1. Все зарегистрированные партии имеют право принимать участие в проводимых на территории проекта выборах.\n4.2. Выборы проводятся с целью определения политического представительства партий и формирования органов власти.\n4.3. Порядок проведения выборов, условия участия и подсчёт голосов определяются администрацией проекта.')}\n\n"
        f"<b>Статья 5. Минимальная численность партии</b>\n"
        f"{_blockquote('5.1. Для официальной регистрации партия обязана иметь установленное минимальное количество участников.\n5.2. Конкретная минимальная численность определяется администрацией проекта и является обязательным условием сохранения регистрации.')}\n\n"
        f"<b>Статья 6. Периодичность выборов</b>\n"
        f"{_blockquote('6.1. Очередные выборы проводятся по истечении установленного количества вайпов.\n6.2. Количество вайпов между избирательными циклами определяется администрацией проекта.')}\n\n"
        f"<b>Статья 7. Дополнительные положения</b>\n"
        f"{_blockquote('7.1. Администрация оставляет за собой право отказать в регистрации партии в случае несоответствия установленным требованиям.\n7.2. Партия может быть лишена регистрации в случае длительного бездействия, фактического прекращения существования или систематического нарушения правил проекта.\n7.3. Администрация оставляет за собой право вносить изменения и дополнения в настоящий регламент.\n7.4. Все спорные вопросы подлежат рассмотрению администрацией проекта.')}"
    )

    @staticmethod
    def format_bill(bill: dict, party: Optional[dict]) -> str:
        btype = BILL_TYPES.get(bill["category"], BILL_TYPES["poll"])
        party_title = f"{party['flag']} {esc(party['name'])}" if party else "Внепартийный"

        c_for = len(bill.get("votes_for", []))
        c_against = len(bill.get("votes_against", []))
        c_abstain = len(bill.get("votes_abstain", []))
        total = c_for + c_against
        pct = round((c_for / total) * 100, 1) if total > 0 else 0.0

        status_map = {
            "active": f"{pe('📢')} <b>Статус:</b> Идёт голосование",
            "passed": f"{pe('✅')} <b>Статус:</b> Принят ({pct}%)",
            "rejected": f"{pe('❌')} <b>Статус:</b> Отклонён ({pct}%)",
            "vetoed": f"{pe('⛔')} <b>Статус:</b> Наложено Вето Владельца",
        }

        return (
            f"{pe('📋')} <b>Законопроект #{bill['id']}</b>\n"
            f"─────────────────────\n"
            f"Тип: <b>{btype['name']}</b>\n"
            f"Партия: <b>{party_title}</b>\n"
            f"Автор: <b>{esc(bill.get('author_name', '?'))}</b>\n\n"
            f"<b>Содержание:</b>\n"
            f"{_blockquote(esc(bill.get('text', '')))}\n\n"
            f"<b>Голоса:</b>\n"
            f"{_blockquote(f'За: {c_for} ({pct}%)\nПротив: {c_against}\nВоздержались: {c_abstain}')}\n\n"
            f"{status_map.get(bill.get('status', 'active'), '')}"
        )

    @staticmethod
    def format_chancellery_decree(bill: dict, party: Optional[dict]) -> str:
        btype = BILL_TYPES.get(bill["category"], BILL_TYPES["poll"])
        party_title = f"{party['flag']} {esc(party['name'])}" if party else "Парламент"
        c_for = len(bill.get("votes_for", []))
        c_against = len(bill.get("votes_against", []))
        c_abstain = len(bill.get("votes_abstain", []))

        return (
            f"{pe('👑')} <b>КАНЦЕЛЯРИЯ RISE OF EUROPE</b>\n"
            f"{pe('📋')} <b>Постановление Парламента #{bill['id']}</b>\n"
            f"─────────────────────\n"
            f"Категория: <b>{btype['name']}</b>\n"
            f"Инициатор: <b>{party_title}</b>\n"
            f"Представитель: <b>{esc(bill.get('author_name', '?'))}</b>\n\n"
            f"<b>Текст принятого акта:</b>\n"
            f"{_blockquote(esc(bill.get('text', '')))}\n\n"
            f"<b>Результаты голосования:</b>\n"
            f"{_blockquote(f'За: {c_for} | Против: {c_against} | Воздержались: {c_abstain}')}\n\n"
            f"{pe('✅')} <b>Утверждено и вступило в законную силу.</b>"
        )


# ===================== КЛАВИАТУРЫ =====================

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


def my_party_kb(can_edit: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_edit:
        builder.row(btn("Изменить программу", "party_edit_program", "✏️"))
    builder.row(btn("Назад", "party_menu", "🔙"))
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


def admin_panel_kb(bot_status: str = "on") -> InlineKeyboardMarkup:
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

    if bot_status == "on":
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
