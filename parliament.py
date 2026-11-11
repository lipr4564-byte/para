"""
Контроллер пользовательских сценариев Парламента, Партий и Выборов.
Не содержит прямых SQL-запросов и верстки: вызывает методы сервисного слоя (database.py) и шаблоны (Views).
"""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType

from config import GROUP_ID, NEWS_TOPIC_ID, REG_BOT_ID, CHANCELLERY_TOPIC_ID
from database import (
    ValidationError, Validator,
    get_all_settings, get_int_setting, is_owner, get_admin_ids,
    register_user_activity, get_user_data, get_all_users, find_user_by_query,
    parse_and_save_reg_text, get_user_slot, try_record_rp_post, can_user_vote,
    get_all_parties, get_party_by_id, get_user_party,
    create_pending_party, get_pending_party, confirm_pending_party_member,
    finalize_pending_party, join_party_by_code, leave_or_remove_from_party,
    create_bill, get_bill, get_all_bills, cast_bill_vote, set_bill_status,
    cast_election_vote, get_election_votes
)
from keyboards import (
    BILL_TYPES, Views, esc, _blockquote,
    main_menu_kb, back_main_kb, party_menu_kb, back_party_kb,
    party_invite_confirm_kb, party_admin_approve_kb,
    parliament_menu_kb, bill_type_kb, bill_vote_kb
)
from logger import (
    log_start, log_post_counted, log_party_created,
    log_bill_created, send_log, log
)
from premium_emoji import pe, btn

router = Router()


class ParlStates(StatesGroup):
    waiting_party_name = State()
    waiting_party_tag = State()
    waiting_party_flag = State()
    waiting_party_program = State()
    waiting_party_cofounders = State()
    waiting_join_code = State()
    waiting_bill_text = State()


async def check_member(bot: Bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return m.status in ("creator", "administrator", "member", "restricted")
    except Exception:
        return False


async def publish_to_chancellery(bot: Bot, bill: dict):
    party = await get_party_by_id(bill["party_id"]) if bill.get("party_id") else None
    text = Views.format_chancellery_decree(bill, party)
    topic_id = await get_int_setting("chancellery_topic_id") or CHANCELLERY_TOPIC_ID
    try:
        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=text,
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Ошибка публикации в Канцелярию ({topic_id}): {e}")


# ===================== МОНИТОРИНГ ГРУППЫ И НОВОСТНИКА (1376336) =====================

@router.message(F.chat.id == GROUP_ID)
async def group_monitor(message: Message, bot: Bot):
    user = message.from_user
    if not user or user.is_bot:
        return

    await register_user_activity(user.id, user.username or "", user.full_name or "")
    text = (message.text or message.caption or "").strip()

    if message.reply_to_message:
        rep = message.reply_to_message
        rep_text = rep.text or rep.caption or ""
        if (rep.from_user and rep.from_user.id == REG_BOT_ID) or "Занятые страны" in rep_text:
            count = await parse_and_save_reg_text(rep_text)
            if count > 0 and text.lower().startswith("!синк"):
                await message.reply(f"{pe('✅')} Синхронизировано позиций: <b>{count}</b>", parse_mode="HTML")
                return

    if message.message_thread_id == NEWS_TOPIC_ID:
        recorded = await try_record_rp_post(user.id, len(text))
        if recorded:
            new_posts, party_name, pts = recorded
            slot = await get_user_slot(user.id, user.username or "", user.full_name or "")
            slot_name = f"{slot['slot_flag']} {slot['slot_name']}" if slot else "Без позиции"
            await log_post_counted(
                bot, user.id, user.username or "", user.full_name or "",
                slot_name, new_posts, party_name, pts
            )


# ===================== СТАРТ И ГЛАВНОЕ МЕНЮ =====================

@router.message(Command("start"), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    await register_user_activity(user.id, user.username or "", user.full_name or "")

    admin_flag = await is_owner(user)
    if not admin_flag:
        if not await check_member(bot, user.id):
            await message.answer(
                f"{pe('⛔')} Сначала вступите в проект <b>Rise of Europe</b>!",
                parse_mode="HTML"
            )
            return

    await log_start(bot, user.id, user.username or "", user.full_name or "")
    slot = await get_user_slot(user.id, user.username or "", user.full_name or "")
    slot_text = f"{slot['slot_flag']} <b>{esc(slot['slot_name'])}</b>" if slot else "<b>не зарегистрирован</b>"
    st = await get_all_settings()

    await message.answer(
        f"{pe('🌍')} <b>Привет! Добро пожаловать в Парламент Rise of Europe!</b>\n\n"
        f"{pe('📍')} Твоя позиция: {slot_text}\n\n"
        f"Выбери нужный раздел ниже:",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin=admin_flag, election_active=st["election_active"])
    )


@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = callback.from_user
    slot = await get_user_slot(user.id, user.username or "", user.full_name or "")
    slot_text = f"{slot['slot_flag']} <b>{esc(slot['slot_name'])}</b>" if slot else "<b>не зарегистрирован</b>"
    st = await get_all_settings()
    admin_flag = await is_owner(user)

    await callback.message.edit_text(
        f"{pe('🌍')} <b>Парламент Rise of Europe</b>\n\n"
        f"{pe('📍')} Твоя позиция: {slot_text}\n\n"
        f"Выбери нужный раздел ниже:",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin=admin_flag, election_active=st["election_active"])
    )
    await callback.answer()


@router.callback_query(F.data == "rules_info")
async def cb_rules_info(callback: CallbackQuery):
    await callback.message.edit_text(
        Views.RULES_TEXT,
        parse_mode="HTML",
        reply_markup=back_main_kb()
    )
    await callback.answer()


# ===================== ПРОФИЛЬ И РЕЙТИНГ =====================

@router.callback_query(F.data == "my_profile")
async def cb_my_profile(callback: CallbackQuery):
    user = callback.from_user
    u_data = await register_user_activity(user.id, user.username or "", user.full_name or "")
    slot = await get_user_slot(user.id, user.username or "", user.full_name or "")
    party = await get_user_party(user.id)

    slot_str = f"{slot['slot_flag']} {esc(slot['slot_name'])}" if slot else "нет"
    party_str = f"{party['flag']} {esc(party['name'])} [{esc(party['tag'])}]" if party else "нет"
    ok, reason, _ = await can_user_vote(user)
    status_str = f"{pe('✅')} Допущен к голосованиям" if ok else f"{pe('❌')} {esc(reason)}"

    await callback.message.edit_text(
        f"{pe('📍')} <b>Профиль игрока</b>\n\n"
        f"Игрок: <b>{esc(user.full_name)}</b>\n"
        f"Позиция: <b>{slot_str}</b>\n"
        f"Партия: <b>{party_str}</b>\n"
        f"РП-постов в новостнике: <b>{u_data.get('posts', 0)}</b>\n\n"
        f"Статус в Парламенте:\n{status_str}",
        parse_mode="HTML",
        reply_markup=back_main_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "top_stats")
async def cb_top_stats(callback: CallbackQuery):
    parties = await get_all_parties()
    p_lines = [
        f"{p['flag']} <b>{esc(p['name'])}</b> — <b>{p.get('points', 0)} ПВ</b> ({len(p.get('members', []))} уч.)"
        for p in parties[:10]
    ]
    p_block = "\n".join(p_lines) if p_lines else "Партий пока нет"

    users = await get_all_users()
    u_lines = []
    for u in [x for x in users if x.get("posts", 0) > 0][:10]:
        s = await get_user_slot(u["user_id"], u.get("username", ""), u.get("full_name", ""))
        label = f"{s['slot_flag']} {esc(s['slot_name'])}" if s else esc(u.get("full_name", "?"))
        u_lines.append(f"{label} — <b>{u['posts']}</b> постов")
    u_block = "\n".join(u_lines) if u_lines else "Постов пока нет"

    await callback.message.edit_text(
        f"{pe('📊')} <b>Рейтинг актива Rise of Europe</b>\n\n"
        f"<b>Партии по Политическому Весу:</b>\n{_blockquote(p_block)}\n\n"
        f"<b>Активные страны в новостнике:</b>\n{_blockquote(u_block)}",
        parse_mode="HTML",
        reply_markup=back_main_kb()
    )
    await callback.answer()


# ===================== ПАРТИИ (СОЗДАНИЕ ЧЕРЕЗ СОГЛАСИЕ И ОДОБРЕНИЕ АДМИНА) =====================

@router.callback_query(F.data == "party_menu")
async def cb_party_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    party = await get_user_party(callback.from_user.id)
    st = await get_all_settings()

    await callback.message.edit_text(
        f"{pe('🤝')} <b>Политические партии Rise of Europe</b>\n\n"
        f"Минимальная численность для регистрации: <b>{st['min_party_members']} чел.</b>\n"
        f"Максимальная численность партии: <b>{st['max_party_members']} чел.</b>\n\n"
        f"Регистрация партий осуществляется с согласия администрации проекта (@asdewrx / @Versaillee).",
        parse_mode="HTML",
        reply_markup=party_menu_kb(has_party=bool(party))
    )
    await callback.answer()


@router.callback_query(F.data == "party_list")
async def cb_party_list(callback: CallbackQuery):
    parties = await get_all_parties()
    if not parties:
        await callback.answer("Зарегистрированных партий пока нет!", show_alert=True)
        return

    blocks = []
    for p in parties:
        leader = await get_user_data(p["leader_id"]) or {}
        leader_name = f"@{leader['username']}" if leader.get("username") else esc(leader.get("full_name", "?"))
        m_list = []
        for mid in p.get("members", []):
            s = await get_user_slot(mid)
            if s:
                m_list.append(f"{s['slot_flag']} {esc(s['slot_name'])}")
            else:
                u = await get_user_data(mid) or {}
                m_list.append(esc(u.get("full_name", str(mid))))

        blocks.append(
            f"{p['flag']} <b>{esc(p['name'])}</b> [{esc(p['tag'])}]\n"
            f"Председатель: {leader_name}\n"
            f"Политический вес: <b>{p.get('points', 0)} ПВ</b> | Мандатов: <b>{p.get('seats', 0)}</b>\n"
            f"Программа: <i>{esc(p.get('program', ''))}</i>\n"
            f"Участники ({len(m_list)}): {', '.join(m_list)}"
        )

    await callback.message.edit_text(
        f"{pe('📋')} <b>Зарегистрированные партии:</b>\n\n" + "\n\n".join(blocks),
        parse_mode="HTML",
        reply_markup=back_party_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "party_create")
async def cb_party_create(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    if await get_user_party(user.id):
        await callback.answer("Ты уже состоишь в партии!", show_alert=True)
        return

    slot = await get_user_slot(user.id, user.username or "", user.full_name or "")
    if not slot and not await is_owner(user):
        await callback.answer("⛔ Подать заявку могут только игроки, занявшие позицию!", show_alert=True)
        return

    await state.set_state(ParlStates.waiting_party_name)
    await callback.message.edit_text(
        f"{pe('✏️')} <b>Регистрация политической партии</b>\n\n"
        f"Напиши полное название партии:",
        parse_mode="HTML",
        reply_markup=back_party_kb()
    )
    await callback.answer()


@router.message(ParlStates.waiting_party_name, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_party_name(message: Message, state: FSMContext):
    try:
        name = Validator.validate_party_name(message.text)
    except ValidationError as e:
        await message.answer(f"{pe('❌')} {e}", parse_mode="HTML")
        return

    await state.update_data(name=name)
    await state.set_state(ParlStates.waiting_party_tag)
    await message.answer(
        f"{pe('✏️')} Напиши краткую аббревиатуру (тег) партии:",
        parse_mode="HTML"
    )


@router.message(ParlStates.waiting_party_tag, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_party_tag(message: Message, state: FSMContext):
    try:
        tag = Validator.validate_party_tag(message.text)
    except ValidationError as e:
        await message.answer(f"{pe('❌')} {e}", parse_mode="HTML")
        return

    await state.update_data(tag=tag)
    await state.set_state(ParlStates.waiting_party_flag)
    await message.answer(
        f"{pe('🏳️')} Отправь один эмодзи или флаг для символики партии:",
        parse_mode="HTML"
    )


@router.message(ParlStates.waiting_party_flag, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_party_flag(message: Message, state: FSMContext):
    try:
        flag = Validator.validate_party_flag(message.text)
    except ValidationError as e:
        await message.answer(f"{pe('❌')} {e}", parse_mode="HTML")
        return

    await state.update_data(flag=flag)
    await state.set_state(ParlStates.waiting_party_program)
    await message.answer(
        f"{pe('📋')} <b>Программа партии (Статья 3)</b>\n\n"
        f"Опиши основные взгляды, цели, принципы и направления деятельности партии:",
        parse_mode="HTML"
    )


@router.message(ParlStates.waiting_party_program, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_party_program(message: Message, state: FSMContext):
    try:
        program = Validator.validate_program(message.text)
    except ValidationError as e:
        await message.answer(f"{pe('❌')} {e}", parse_mode="HTML")
        return

    min_mem = await get_int_setting("min_party_members")
    needed = max(1, min_mem - 1)
    await state.update_data(program=program)
    await state.set_state(ParlStates.waiting_party_cofounders)

    await message.answer(
        f"{pe('👥')} <b>Состав партии (Статья 5)</b>\n\n"
        f"Для регистрации партии необходимо минимум <b>{min_mem}</b> участника (включая тебя как главу партии).\n\n"
        f"Отправь через пробел <b>@юзернеймы</b> или <b>ID</b> минимум <b>{needed}</b> игроков, с которыми ты создаёшь партию.\n"
        f"<i>Важно: каждый из них должен хотя бы раз нажать /start в этом боте, чтобы бот прислал им запрос на подтверждение!</i>",
        parse_mode="HTML",
        reply_markup=back_party_kb()
    )


@router.message(ParlStates.waiting_party_cofounders, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_party_cofounders(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    st = await get_all_settings()
    min_mem = st["min_party_members"]
    max_mem = st["max_party_members"]
    needed = max(1, min_mem - 1)

    raw_tokens = message.text.replace(",", " ").split()
    found_users = []
    seen_ids = set()
    not_found = []

    for tok in raw_tokens:
        u_info = await find_user_by_query(tok)
        if not u_info:
            not_found.append(tok)
        elif u_info["user_id"] != user.id and u_info["user_id"] not in seen_ids:
            if u_info.get("party_id"):
                await message.answer(
                    f"{pe('❌')} Игрок <b>{esc(u_info.get('full_name'))}</b> уже состоит в другой партии!",
                    parse_mode="HTML"
                )
                return
            seen_ids.add(u_info["user_id"])
            found_users.append(u_info)

    if not_found:
        await message.answer(
            f"{pe('❓')} Не нашёл в базе бота: <code>{esc(', '.join(not_found))}</code>.\n"
            f"Попроси их нажать /start в этом боте и отправь список снова.",
            parse_mode="HTML"
        )
        return

    if len(found_users) < needed:
        await message.answer(
            f"{pe('⚠️')} Нужно указать минимум <b>{needed}</b> сооснователей (ты указал {len(found_users)}).",
            parse_mode="HTML"
        )
        return

    if len(found_users) + 1 > max_mem:
        await message.answer(
            f"{pe('⚠️')} Превышен максимальный размер партии ({max_mem} чел.).",
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    req_id = await create_pending_party(
        leader=user,
        name=data["name"],
        tag=data["tag"],
        flag=data["flag"],
        program=data["program"],
        invited_ids=[u["user_id"] for u in found_users]
    )
    await state.clear()

    sent_count = 0
    for u in found_users:
        try:
            await bot.send_message(
                chat_id=u["user_id"],
                text=(
                    f"{pe('🤝')} <b>Приглашение в политическую партию</b>\n\n"
                    f"Глава партии <b>{esc(user.full_name)}</b> (@{user.username or 'нет'}) указал тебя сооснователем партии:\n"
                    f"Партия: <b>{data['flag']} {esc(data['name'])}</b> [{esc(data['tag'])}]\n\n"
                    f"<b>Программа партии:</b>\n{_blockquote(esc(data['program']))}\n\n"
                    f"Ты подтверждаешь своё вступление в эту партию?"
                ),
                parse_mode="HTML",
                reply_markup=party_invite_confirm_kb(req_id)
            )
            sent_count += 1
        except Exception:
            pass

    await message.answer(
        f"{pe('📩')} <b>Запросы отправлены сооснователям ({sent_count} чел.)!</b>\n\n"
        f"Как только минимум <b>{min_mem}</b> участников подтвердят участие, "
        f"заявка автоматически отправится на утверждение администрации (@asdewrx / @Versaillee).",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin=await is_owner(user), election_active=st["election_active"])
    )


@router.callback_query(F.data.startswith("pinv_"))
async def cb_party_invite_response(callback: CallbackQuery, bot: Bot):
    _, action, req_id = callback.data.split("_")
    user = callback.from_user

    req = await get_pending_party(req_id)
    if not req:
        await callback.answer("❌ Заявка не найдена или уже закрыта.", show_alert=True)
        return

    if user.id not in req["invited_ids"]:
        await callback.answer("⛔ Это приглашение не для тебя.", show_alert=True)
        return

    if action == "no":
        await callback.message.edit_text(
            callback.message.text + f"\n\n{pe('❌')} <b>Ты отклонил приглашение в партию.</b>",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                req["leader_id"],
                f"{pe('❌')} Игрок <b>{esc(user.full_name)}</b> отклонил приглашение в партию <b>{esc(req['name'])}</b>.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await callback.answer("Отклонено")
        return

    req, should_send_admin = await confirm_pending_party_member(req_id, user.id)
    if not req:
        return

    await callback.message.edit_text(
        callback.message.text + f"\n\n{pe('✅')} <b>Ты подтвердил участие в партии!</b>",
        parse_mode="HTML"
    )
    await callback.answer("✅ Подтверждено!")

    min_mem = await get_int_setting("min_party_members")
    curr_count = len(req["confirmed_ids"])

    try:
        await bot.send_message(
            req["leader_id"],
            f"{pe('✅')} Игрок <b>{esc(user.full_name)}</b> подтвердил участие в партии <b>{esc(req['name'])}</b> "
            f"(Подтвердили: <b>{curr_count}/{min_mem}</b>).",
            parse_mode="HTML"
        )
    except Exception:
        pass

    if should_send_admin:
        member_lines = []
        for mid in req["confirmed_ids"]:
            u = await get_user_data(mid) or {}
            s = await get_user_slot(mid)
            s_txt = f"{s['slot_flag']} {s['slot_name']}" if s else "Без страны"
            uname_txt = f"@{u['username']}" if u.get("username") else f"ID: {mid}"
            member_lines.append(f"• <code>{esc(u.get('full_name', str(mid)))}</code> ({uname_txt}) — {esc(s_txt)}")

        admin_msg = (
            f"🏛 <b>Заявка на регистрацию партии</b>\n\n"
            f"Глава партии: <code>{esc(req['leader_name'])}</code> | @{req['leader_username'] or 'нет'} | ID: <code>{req['leader_id']}</code>\n"
            f"Название: <b>{req['flag']} {esc(req['name'])}</b> [{esc(req['tag'])}]\n\n"
            f"<b>Программа партии:</b>\n{_blockquote(esc(req['program']))}\n\n"
            f"<b>Подтверждённый состав ({curr_count} чел.):</b>\n" + "\n".join(member_lines) + "\n\n"
            f"Зарегистрировать партию?"
        )

        for adm_id in await get_admin_ids():
            try:
                await bot.send_message(
                    chat_id=adm_id,
                    text=admin_msg,
                    parse_mode="HTML",
                    reply_markup=party_admin_approve_kb(req_id)
                )
            except Exception as e:
                log.error(f"Не удалось отправить заявку на партию админу {adm_id}: {e}")


# ===================== ОДОБРЕНИЕ / ОТКЛОНЕНИЕ ПАРТИИ АДМИНИСТРАЦИЕЙ =====================

@router.callback_query(F.data.startswith("papp_"))
async def cb_party_admin_decision(callback: CallbackQuery, bot: Bot):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Только для администрации (@asdewrx / @Versaillee)!", show_alert=True)
        return

    _, decision, req_id = callback.data.split("_")
    approve = decision == "yes"
    req = await finalize_pending_party(req_id, approve=approve)

    if not req:
        await callback.answer("❌ Заявка уже рассмотрена или устарела.", show_alert=True)
        return

    if not approve:
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ <b>Отказано в регистрации</b>",
            parse_mode="HTML"
        )
        for uid in req["confirmed_ids"]:
            try:
                await bot.send_message(
                    uid,
                    f"{pe('❌')} <b>Администрация отклонила заявку на регистрацию партии «{esc(req['name'])}».</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        await callback.answer("❌ Отклонено")
        return

    pid = req["party_id"]
    await log_party_created(bot, req["leader_id"], req["leader_username"], req["leader_name"], req["name"], req["tag"])

    for uid in req["confirmed_ids"]:
        try:
            await bot.send_message(
                uid,
                f"{pe('✅')} <b>Партия {req['flag']} «{esc(req['name'])}» официально зарегистрирована администрацией!</b>\n\n"
                f"Код приглашения новых участников: <code>{pid}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    topic_id = await get_int_setting("chancellery_topic_id") or CHANCELLERY_TOPIC_ID
    try:
        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=(
                f"{pe('👑')} <b>КАНЦЕЛЯРИЯ RISE OF EUROPE</b>\n"
                f"{pe('🤝')} <b>Регистрация политической партии</b>\n"
                f"─────────────────────\n"
                f"Партия: <b>{req['flag']} {esc(req['name'])}</b> [{esc(req['tag'])}]\n"
                f"Председатель: <b>{esc(req['leader_name'])}</b> (@{req['leader_username'] or 'нет'})\n"
                f"Численность состава: <b>{len(req['confirmed_ids'])} чел.</b>\n\n"
                f"<b>Программа партии:</b>\n{_blockquote(esc(req['program']))}\n\n"
                f"{pe('✅')} <b>Зарегистрирована в соответствии с Положением о партиях ROE.</b>"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await callback.message.edit_text(
        callback.message.text + "\n\n✅ <b>Партия зарегистрирована</b>",
        parse_mode="HTML"
    )
    await callback.answer("✅ Одобрено!")


# ===================== МОЯ ПАРТИЯ, ВСТУПЛЕНИЕ И ВЫХОД =====================

@router.callback_query(F.data == "party_my")
async def cb_party_my(callback: CallbackQuery):
    party = await get_user_party(callback.from_user.id)
    if not party:
        await callback.answer("Ты не состоишь в партии!", show_alert=True)
        return

    max_mem = await get_int_setting("max_party_members")
    m_lines = []
    for mid in party["members"]:
        u = await get_user_data(mid) or {}
        s = await get_user_slot(mid)
        s_str = f"{s['slot_flag']} {esc(s['slot_name'])}" if s else "Без страны"
        role = "👑 Председатель" if mid == party["leader_id"] else "👤 Участник"
        m_lines.append(f"{role}: <b>{esc(u.get('full_name', str(mid)))}</b> ({s_str})")

    await callback.message.edit_text(
        f"{party['flag']} <b>{esc(party['name'])} [{esc(party['tag'])}]</b>\n"
        f"─────────────────────\n"
        f"Код приглашения: <code>{party['id']}</code>\n"
        f"Политический вес: <b>{party.get('points', 0)} ПВ</b>\n"
        f"Мандатов в Парламенте: <b>{party.get('seats', 0)}</b>\n\n"
        f"<b>Программа партии:</b>\n{_blockquote(esc(party.get('program', '')))}\n\n"
        f"<b>Состав ({len(party['members'])}/{max_mem}):</b>\n"
        f"{_blockquote(chr(10).join(m_lines))}",
        parse_mode="HTML",
        reply_markup=back_party_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "party_join")
async def cb_party_join(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    if await get_user_party(user.id):
        await callback.answer("Ты уже в партии!", show_alert=True)
        return
    if not await get_user_slot(user.id, user.username or "", user.full_name or "") and not await is_owner(user):
        await callback.answer("⛔ Вступить в партию могут только зарегистрированные на позициях игроки!", show_alert=True)
        return

    await state.set_state(ParlStates.waiting_join_code)
    await callback.message.edit_text(
        f"{pe('🔗')} Введи код приглашения партии:",
        parse_mode="HTML",
        reply_markup=back_party_kb()
    )
    await callback.answer()


@router.message(ParlStates.waiting_join_code, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_party_join_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    ok, err_msg, party = await join_party_by_code(message.from_user.id, code)
    if not ok:
        await message.answer(f"{pe('❌')} {esc(err_msg)}", parse_mode="HTML")
        return

    await state.clear()
    await message.answer(
        f"{pe('✅')} Ты вступил в партию <b>{party['flag']} {esc(party['name'])}</b>!",
        parse_mode="HTML",
        reply_markup=party_menu_kb(has_party=True)
    )


@router.callback_query(F.data == "party_leave")
async def cb_party_leave(callback: CallbackQuery, state: FSMContext):
    await leave_or_remove_from_party(callback.from_user.id)
    await callback.answer("Ты покинул партию.", show_alert=True)
    await cb_party_menu(callback, state)


# ===================== ЗАКОНОПРОЕКТЫ И ГОЛОСОВАНИЯ =====================

@router.callback_query(F.data == "parl_menu")
async def cb_parl_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    bills = await get_all_bills()
    active_c = sum(1 for b in bills if b.get("status") == "active")

    await callback.message.edit_text(
        f"{pe('📋')} <b>Парламент Rise of Europe</b>\n\n"
        f"Активных голосований: <b>{active_c}</b>\n"
        f"Всего законопроектов в базе: <b>{len(bills)}</b>",
        parse_mode="HTML",
        reply_markup=parliament_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "bills_active")
async def cb_bills_active(callback: CallbackQuery):
    bills = await get_all_bills()
    active = [b for b in bills if b.get("status") == "active"]
    if not active:
        await callback.answer("Активных голосований сейчас нет!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for b in active[-10:]:
        builder.row(btn(f"#{b['id']} {b['text'][:35]}", f"bopen_{b['id']}", "📢"))
    builder.row(btn("Назад", "parl_menu", "🔙"))

    await callback.message.edit_text(
        f"{pe('📢')} <b>Активные голосования:</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "bills_archive")
async def cb_bills_archive(callback: CallbackQuery):
    bills = await get_all_bills()
    closed = [b for b in bills if b.get("status") != "active"]
    if not closed:
        await callback.answer("Архив пуст!", show_alert=True)
        return

    lines = []
    for b in closed[-15:]:
        st = "✅ Принят" if b["status"] == "passed" else ("👑 Вето" if b["status"] == "vetoed" else "❌ Отклонён")
        lines.append(f"<b>#{b['id']}</b> ({st}) — {esc(b['text'][:55])}...")

    await callback.message.edit_text(
        f"{pe('📋')} <b>Архив Канцелярии:</b>\n\n{_blockquote(chr(10).join(lines))}",
        parse_mode="HTML",
        reply_markup=parliament_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bopen_"))
async def cb_bill_open(callback: CallbackQuery):
    bid = callback.data[len("bopen_"):]
    bill = await get_bill(bid)
    if not bill:
        await callback.answer("Законопроект не найден!", show_alert=True)
        return

    party = await get_party_by_id(bill["party_id"]) if bill.get("party_id") else None
    await callback.message.edit_text(
        Views.format_bill(bill, party),
        parse_mode="HTML",
        reply_markup=bill_vote_kb(bill)
    )
    await callback.answer()


@router.callback_query(F.data == "bill_propose")
async def cb_bill_propose(callback: CallbackQuery):
    user = callback.from_user
    ok, reason, _ = await can_user_vote(user)
    if not ok:
        await callback.answer(reason, show_alert=True)
        return

    party = await get_user_party(user.id)
    admin_flag = await is_owner(user)
    if not party and not admin_flag:
        await callback.answer("⛔ Выдвигать законопроекты могут только зарегистрированные партии!", show_alert=True)
        return

    if party and not admin_flag:
        min_mem = await get_int_setting("min_party_members")
        if len(party.get("members", [])) < min_mem:
            await callback.answer(
                f"⛔ В вашей партии меньше {min_mem} участников (Статья 5)!",
                show_alert=True
            )
            return

    await callback.message.edit_text(
        f"{pe('✏️')} <b>Выдвижение законопроекта</b>\n\n"
        f"Выбери тип документа:",
        parse_mode="HTML",
        reply_markup=bill_type_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("btype_"))
async def cb_bill_type_select(callback: CallbackQuery, state: FSMContext):
    bkey = callback.data[len("btype_"):]
    binfo = BILL_TYPES.get(bkey)
    if not binfo:
        return

    user = callback.from_user
    party = await get_user_party(user.id)
    if not await is_owner(user):
        if not party or party.get("points", 0) < binfo["cost"]:
            await callback.answer(
                f"⛔ Недостаточно очков у партии! Требуется: {binfo['cost']} ПВ.",
                show_alert=True
            )
            return

    await state.update_data(bill_type=bkey)
    await state.set_state(ParlStates.waiting_bill_text)

    await callback.message.edit_text(
        f"{pe('✏️')} <b>{binfo['name']}</b>\n"
        f"Стоимость выдвижения: <b>{binfo['cost']} ПВ</b>\n"
        f"Порог принятия: <b>{binfo['majority']}%</b>\n\n"
        f"Напиши полный текст законопроекта и обоснование:",
        parse_mode="HTML",
        reply_markup=back_main_kb()
    )
    await callback.answer()


@router.message(ParlStates.waiting_bill_text, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_bill_text(message: Message, state: FSMContext, bot: Bot):
    try:
        text = Validator.validate_bill_text(message.text)
    except ValidationError as e:
        await message.answer(f"{pe('❌')} {e}", parse_mode="HTML")
        return

    data = await state.get_data()
    bkey = data["bill_type"]
    binfo = BILL_TYPES[bkey]
    user = message.from_user
    admin_flag = await is_owner(user)

    u_data = await get_user_data(user.id) or {}
    pid = u_data.get("party_id")
    slot = await get_user_slot(user.id, user.username or "", user.full_name or "")
    slot_str = f"{slot['slot_flag']} {slot['slot_name']}" if slot else "Администрация"

    try:
        bill = await create_bill(
            party_id=pid,
            author_id=user.id,
            author_name=user.full_name or str(user.id),
            author_slot=slot_str,
            category=bkey,
            text=text,
            cost=binfo["cost"],
            is_admin=admin_flag
        )
    except ValidationError as e:
        await message.answer(f"{pe('❌')} {e}", parse_mode="HTML")
        await state.clear()
        return

    await state.clear()
    bid = bill["id"]
    await log_bill_created(bot, user.id, user.username or "", user.full_name or "", bid, binfo["name"])

    party = await get_party_by_id(pid) if pid else None
    topic_id = await get_int_setting("chancellery_topic_id") or CHANCELLERY_TOPIC_ID
    try:
        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=Views.format_bill(bill, party),
            parse_mode="HTML",
            reply_markup=bill_vote_kb(bill)
        )
    except Exception as e:
        log.error(f"Ошибка отправки голосования в тему: {e}")

    st = await get_all_settings()
    await message.answer(
        f"{pe('✅')} <b>Законопроект #{bid} выставлен на голосование!</b>",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin=admin_flag, election_active=st["election_active"])
    )


# ===================== ГОЛОСОВАНИЕ ПО ЗАКОНОПРОЕКТУ =====================

@router.callback_query(F.data.startswith("vote_"))
async def cb_vote(callback: CallbackQuery):
    _, bid, vtype = callback.data.split("_")
    user = callback.from_user

    ok, reason, _ = await can_user_vote(user)
    if not ok:
        await callback.answer(reason, show_alert=True)
        return

    bill = await cast_bill_vote(bid, user.id, vtype)
    if not bill:
        await callback.answer("⛔ Голосование уже закрыто!", show_alert=True)
        return

    party = await get_party_by_id(bill["party_id"]) if bill.get("party_id") else None
    try:
        await callback.message.edit_text(
            Views.format_bill(bill, party),
            parse_mode="HTML",
            reply_markup=bill_vote_kb(bill)
        )
    except Exception:
        pass

    await callback.answer("✅ Твой голос учтён!")


@router.callback_query(F.data.startswith("votes_list_"))
async def cb_votes_list(callback: CallbackQuery):
    bid = callback.data[len("votes_list_"):]
    bill = await get_bill(bid)
    if not bill:
        return

    async def _fmt(uid_list):
        items = []
        for u_id in uid_list:
            s = await get_user_slot(u_id)
            if s:
                items.append(f"{s['slot_flag']} {s['slot_name']}")
            else:
                u = await get_user_data(u_id) or {}
                items.append(u.get("full_name", str(u_id)))
        return ", ".join(items) if items else "нет"

    info = (
        f"Голоса #{bid}:\n"
        f"✅ За: {await _fmt(bill['votes_for'])}\n"
        f"❌ Против: {await _fmt(bill['votes_against'])}\n"
        f"🤝 Воздержались: {await _fmt(bill['votes_abstain'])}"
    )
    if len(info) > 195:
        await callback.message.answer(f"<b>{esc(info)}</b>", parse_mode="HTML")
        await callback.answer()
    else:
        await callback.answer(info, show_alert=True)


@router.callback_query(F.data.startswith("bill_veto_"))
async def cb_bill_veto(callback: CallbackQuery, bot: Bot):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Только для администрации (@asdewrx / @Versaillee)!", show_alert=True)
        return

    bid = callback.data[len("bill_veto_"):]
    bill = await set_bill_status(bid, "vetoed")
    if not bill:
        return

    party = await get_party_by_id(bill["party_id"]) if bill.get("party_id") else None
    try:
        await callback.message.edit_text(
            Views.format_bill(bill, party),
            parse_mode="HTML",
            reply_markup=bill_vote_kb(bill)
        )
    except Exception:
        pass

    await send_log(bot, f"👑 Наложено <b>ВЕТО</b> на законопроект #{bid}")
    await callback.answer("👑 Наложено Вето!", show_alert=True)


@router.callback_query(F.data.startswith("bill_finish_"))
async def cb_bill_finish(callback: CallbackQuery, bot: Bot):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Подвести итог голосования может только администрация!", show_alert=True)
        return

    bid = callback.data[len("bill_finish_"):]
    bill = await get_bill(bid)
    if not bill or bill.get("status") != "active":
        return

    binfo = BILL_TYPES.get(bill["category"], BILL_TYPES["poll"])
    c_for = len(bill.get("votes_for", []))
    c_against = len(bill.get("votes_against", []))
    total = c_for + c_against
    pct = (c_for / total * 100) if total > 0 else 0

    new_status = "passed" if (total > 0 and pct >= binfo["majority"]) else "rejected"
    bill = await set_bill_status(bid, new_status)

    if new_status == "passed":
        await publish_to_chancellery(bot, bill)

    party = await get_party_by_id(bill["party_id"]) if bill.get("party_id") else None
    try:
        await callback.message.edit_text(
            Views.format_bill(bill, party),
            parse_mode="HTML",
            reply_markup=bill_vote_kb(bill)
        )
    except Exception:
        pass

    await callback.answer("✅ Итоги подведены!", show_alert=True)


# ===================== ВЫБОРЫ В ПАРЛАМЕНТ (СТАТЬЯ 4 И 6) =====================

@router.callback_query(F.data == "election_menu")
async def cb_election_menu(callback: CallbackQuery):
    st = await get_all_settings()
    if not st["election_active"]:
        await callback.answer("Сейчас выборы не проводятся!", show_alert=True)
        return

    parties = await get_all_parties()
    min_mem = st["min_party_members"]
    valid_parties = [p for p in parties if len(p.get("members", [])) >= min_mem]

    if not valid_parties:
        await callback.answer("Нет партий, допущенных к выборам!", show_alert=True)
        return

    votes = await get_election_votes()
    builder = InlineKeyboardBuilder()
    lines = []
    for p in valid_parties:
        v_count = sum(1 for v in votes.values() if v == p["id"])
        lines.append(f"{p['flag']} <b>{esc(p['name'])}</b> [{esc(p['tag'])}] — Голосов: <b>{v_count}</b>")
        builder.row(btn(f"{p['flag']} {p['name']} ({v_count})", f"elvote_{p['id']}"))

    builder.row(btn("Назад", "back_main", "🔙"))

    await callback.message.edit_text(
        f"{pe('👑')} <b>Всеобщие выборы в Парламент Rise of Europe</b>\n\n"
        f"Отдай свой голос за одну из зарегистрированных партий:\n\n"
        f"{_blockquote(chr(10).join(lines))}",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("elvote_"))
async def cb_election_vote(callback: CallbackQuery):
    pid = callback.data[len("elvote_"):]
    user = callback.from_user

    ok, reason, _ = await can_user_vote(user)
    if not ok:
        await callback.answer(reason, show_alert=True)
        return

    party = await get_party_by_id(pid)
    if not party:
        return

    casted = await cast_election_vote(user.id, pid)
    if not casted:
        await callback.answer("Выборы уже завершены!", show_alert=True)
        return

    await callback.answer(f"✅ Твой голос за партию «{party['name']}» учтён!", show_alert=True)
    await cb_election_menu(callback)