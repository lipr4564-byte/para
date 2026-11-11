"""
Административный контроллер Парламента Rise of Europe
"""

import os
from datetime import datetime
from html import escape
from typing import Tuple

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType

from config import GROUP_ID, CHANCELLERY_TOPIC_ID
from database import (
    db_manager, get_all_settings, set_setting, is_owner,
    get_all_users, get_user_data, find_user_by_query,
    sync_slots_from_reg_file, parse_and_save_reg_text, get_user_slot,
    count_slots, bind_user_slot_manual,
    get_all_parties, get_party_by_id, delete_party_by_admin, add_party_points,
    set_party_chancellery_msg_id,
    get_all_bills, get_election_votes, start_elections_db, finish_elections_db,
    wipe_parliament_season
)
from parliament import sync_party_chancellery_post
from keyboards import admin_panel_kb, admin_settings_kb, back_to_admin_kb, _blockquote
from logger import log_broadcast, log
from premium_emoji import pe, btn

router = Router()


class AdminStates(StatesGroup):
    waiting_sync_text = State()
    waiting_broadcast = State()
    waiting_user_id = State()
    waiting_set_posts = State()
    waiting_bind_slot = State()
    waiting_wipe_confirm = State()


def esc(text: str) -> str:
    return escape(str(text))


async def _build_admin_header() -> Tuple[str, str]:
    await sync_slots_from_reg_file()
    st = await get_all_settings()
    users = await get_all_users()
    parties = await get_all_parties()
    bills = await get_all_bills()
    slots_c = await count_slots()

    status = st["bot_status"]
    status_text = "🟢 работает" if status == "on" else "🔴 техобслуживание"
    el_text = "🟢 идут выборы" if st["election_active"] else f"ожидание ({st['wipes_passed']}/{st['wipes_per_election']} вайпов)"

    text = (
        f"{pe('🔧')} <b>Панель администратора</b>\n\n"
        f"{pe('👥')} Пользователей в базе: <b>{len(users)}</b>\n"
        f"{pe('🏳️')} Занятых позиций: <b>{slots_c}</b>\n"
        f"{pe('🤝')} Зарегистрированных партий: <b>{len(parties)}</b>\n"
        f"{pe('📋')} Законопроектов: <b>{len(bills)}</b>\n"
        f"{pe('👑')} Выборы: <b>{el_text}</b>\n"
        f"🤖 Статус бота: <b>{status_text}</b>"
    )
    return text, status


@router.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
async def cmd_admin(message: Message, state: FSMContext):
    if not await is_owner(message.from_user):
        return
    await state.clear()
    text, status = await _build_admin_header()
    await message.answer(text, parse_mode="HTML", reply_markup=admin_panel_kb(status))


@router.callback_query(F.data == "back_admin")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    await state.clear()
    text, status = await _build_admin_header()
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_panel_kb(status))
    await callback.answer()


@router.callback_query(F.data == "admin_sync")
async def admin_sync(callback: CallbackQuery, state: FSMContext):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    file_count = await sync_slots_from_reg_file()
    note = f"Автоматически загружено из БД регистрации: <b>{file_count}</b> позиций.\n\n" if file_count else ""

    await state.set_state(AdminStates.waiting_sync_text)
    await callback.message.edit_text(
        f"{pe('🔄')} <b>Синхронизация позиций</b>\n\n"
        f"{note}"
        f"Перешли или скопируй сюда актуальное сообщение со списком стран от @RegistrationROEbot:",
        parse_mode="HTML",
        reply_markup=back_to_admin_kb()
    )
    await callback.answer()


@router.message(AdminStates.waiting_sync_text, F.chat.type == ChatType.PRIVATE)
async def handle_sync_text(message: Message, state: FSMContext):
    if not await is_owner(message.from_user):
        return

    text = message.text or message.caption or ""
    count = await parse_and_save_reg_text(text)
    if not count:
        await message.answer(
            f"{pe('❌')} Не удалось найти список стран в тексте.",
            parse_mode="HTML",
            reply_markup=back_to_admin_kb()
        )
        return

    await state.clear()
    _, status = await _build_admin_header()
    await message.answer(
        f"{pe('✅')} Синхронизировано позиций: <b>{count}</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_kb(status)
    )


@router.message(Command("users"), F.chat.type == ChatType.PRIVATE)
async def cmd_users(message: Message):
    if not await is_owner(message.from_user):
        return
    await _send_users_file(message.answer_document)


@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    await _send_users_file(callback.message.answer_document)
    await callback.answer()


async def _send_users_file(send_doc_func):
    users = await get_all_users()
    parties_list = await get_all_parties()
    parties = {p["id"]: p for p in parties_list}

    lines = [
        "Rise of Europe — Депутаты и пользователи Парламента",
        f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "=" * 50, ""
    ]

    for u in users:
        slot = await get_user_slot(u["user_id"], u.get("username", ""), u.get("full_name", ""))
        slot_info = f"{slot['slot_flag']} {slot['slot_name']}" if slot else "нет"
        p = parties.get(u.get("party_id") or "")
        party_info = f"{p['name']} [{p['tag']}]" if p else "беспартийный"

        lines.extend([
            f"ID: {u['user_id']}",
            f"Имя: {u.get('full_name', 'нет')}",
            f"Юзернейм: @{u.get('username', 'нет')}",
            f"Позиция: {slot_info}",
            f"Партия: {party_info}",
            f"РП-постов: {u.get('posts', 0)}",
            "-" * 30
        ])

    content = "\n".join(lines)
    file = BufferedInputFile(content.encode("utf-8"), filename="parliament_users.txt")
    await send_doc_func(file, caption=f"👥 Пользователей в базе: {len(users)}")


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_broadcast)
    await callback.message.edit_text(
        f"{pe('📢')} <b>Рассылка</b>\n\nНапиши текст объявления для всех пользователей бота:",
        parse_mode="HTML",
        reply_markup=back_to_admin_kb()
    )
    await callback.answer()


@router.message(AdminStates.waiting_broadcast, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_broadcast(message: Message, state: FSMContext):
    if not await is_owner(message.from_user):
        return

    bot = message.bot
    text = message.text
    users = await get_all_users()
    sent, failed = 0, 0

    status_msg = await message.answer(f"📢 Рассылка начата... 0/{len(users)}")

    for user in users:
        try:
            await bot.send_message(
                chat_id=user["user_id"],
                text=f"📢 <b>Объявление Канцелярии Rise of Europe:</b>\n\n{esc(text)}",
                parse_mode="HTML"
            )
            sent += 1
        except Exception:
            failed += 1

        if (sent + failed) % 10 == 0:
            try:
                await status_msg.edit_text(f"📢 Рассылка... {sent + failed}/{len(users)}")
            except Exception:
                pass

    await log_broadcast(bot, message.from_user.id, text, sent)
    await status_msg.edit_text(
        f"{pe('✅')} Рассылка завершена!\n"
        f"{pe('📩')} Отправлено: <b>{sent}</b>\n"
        f"{pe('❌')} Не доставлено: <b>{failed}</b>",
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "admin_user_manage")
async def admin_user_manage(callback: CallbackQuery, state: FSMContext):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_user_id)
    await callback.message.edit_text(
        f"{pe('🔧')} <b>Управление пользователем</b>\n\n"
        f"Введи ID, @юзернейм или имя пользователя:",
        parse_mode="HTML",
        reply_markup=back_to_admin_kb()
    )
    await callback.answer()


@router.message(AdminStates.waiting_user_id, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_user_manage_id(message: Message, state: FSMContext):
    if not await is_owner(message.from_user):
        return

    user_data = await find_user_by_query(message.text)
    if not user_data:
        await message.answer(
            f"{pe('❌')} Пользователь не найден в базе.",
            parse_mode="HTML",
            reply_markup=back_to_admin_kb()
        )
        return

    await state.update_data(manage_user_id=user_data["user_id"])
    await _show_user_manage_card(message.answer, user_data["user_id"])


async def _show_user_manage_card(send_func, user_id: int):
    u = await get_user_data(user_id) or {}
    slot = await get_user_slot(user_id, u.get("username", ""), u.get("full_name", ""))
    slot_info = f"{slot['slot_flag']} {slot['slot_name']}" if slot else "не зарегистрирован"
    p = await get_party_by_id(u["party_id"]) if u.get("party_id") else None
    party_info = f"{p['flag']} {p['name']}" if p else "нет"
    is_banned = bool(u.get("banned"))
    is_immune = bool(u.get("immune"))

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить количество постов", callback_data=f"umng_posts_{user_id}")],
            [InlineKeyboardButton(text="🏳️ Привязать позицию вручную", callback_data=f"umng_slot_{user_id}")],
            [InlineKeyboardButton(
                text="🔓 Снять иммунитет к постам" if is_immune else "👑 Дать иммунитет к постам",
                callback_data=f"umng_imm_{user_id}"
            )],
            [InlineKeyboardButton(
                text="🔓 Разбанить в Парламенте" if is_banned else "🚫 Забанить в Парламенте",
                callback_data=f"umng_ban_{user_id}"
            )],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_admin")]
        ]
    )

    await send_func(
        f"{pe('👤')} <b>Информация о пользователе</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Имя: <b>{esc(u.get('full_name', str(user_id)))}</b>\n"
        f"Юзернейм: @{u.get('username') or 'нет'}\n"
        f"Позиция: <b>{esc(slot_info)}</b>\n"
        f"Партия: <b>{esc(party_info)}</b>\n"
        f"РП-постов: <b>{u.get('posts', 0)}</b>\n"
        f"Иммунитет к цензу: <b>{'да' if is_immune else 'нет'}</b>\n"
        f"Статус: <b>{'🚫 Забанен' if is_banned else '🟢 Активен'}</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("umng_"))
async def handle_umng_callbacks(callback: CallbackQuery, state: FSMContext):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    _, act, uid_str = callback.data.split("_")
    uid = int(uid_str)

    if act == "posts":
        await state.update_data(manage_user_id=uid)
        await state.set_state(AdminStates.waiting_set_posts)
        await callback.message.edit_text(
            f"✏️ Введи новое количество РП-постов для пользователя <code>{uid}</code>:",
            parse_mode="HTML",
            reply_markup=back_to_admin_kb()
        )
        await callback.answer()
        return

    if act == "slot":
        await state.update_data(manage_user_id=uid)
        await state.set_state(AdminStates.waiting_bind_slot)
        await callback.message.edit_text(
            f"🏳️ Введи флаг и название позиции для игрока <code>{uid}</code> (например: <code>🇺🇸 США</code>):",
            parse_mode="HTML",
            reply_markup=back_to_admin_kb()
        )
        await callback.answer()
        return

    if act == "imm":
        async with db_manager.transaction() as conn:
            await conn.execute("UPDATE users SET immune = CASE WHEN immune = 1 THEN 0 ELSE 1 END WHERE user_id = ?;", (uid,))
        await _show_user_manage_card(callback.message.edit_text, uid)
        await callback.answer("✅ Обновлено")
        return

    if act == "ban":
        async with db_manager.transaction() as conn:
            await conn.execute("UPDATE users SET banned = CASE WHEN banned = 1 THEN 0 ELSE 1 END WHERE user_id = ?;", (uid,))
        await _show_user_manage_card(callback.message.edit_text, uid)
        await callback.answer("✅ Обновлено")


@router.message(AdminStates.waiting_set_posts, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_set_posts(message: Message, state: FSMContext):
    if not await is_owner(message.from_user):
        return
    if not message.text.strip().isdigit():
        await message.answer("❌ Введи целое неотрицательное число.")
        return

    data = await state.get_data()
    uid = data["manage_user_id"]
    async with db_manager.transaction() as conn:
        await conn.execute("UPDATE users SET posts = ? WHERE user_id = ?;", (int(message.text.strip()), uid))

    await state.clear()
    await _show_user_manage_card(message.answer, uid)


@router.message(AdminStates.waiting_bind_slot, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_bind_slot(message: Message, state: FSMContext):
    if not await is_owner(message.from_user):
        return

    data = await state.get_data()
    uid = data["manage_user_id"]
    raw = message.text.strip()
    parts = raw.split(" ", 1)
    flag, sname = (parts[0], parts[1]) if len(parts) == 2 and not parts[0][0].isalnum() else ("🏳️", raw)

    await bind_user_slot_manual(uid, flag, sname)
    await state.clear()
    await _show_user_manage_card(message.answer, uid)


@router.callback_query(F.data == "admin_parties")
async def admin_parties(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    parties = await get_all_parties()
    if not parties:
        await callback.answer("Зарегистрированных партий нет!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for p in parties:
        builder.row(
            btn(f"{p['flag']} {p['name']} ({p.get('points', 0)} ПВ)", f"adm_padd_{p['id']}"),
            btn("Лишить регистрации", f"adm_pdel_{p['id']}", "🗑️")
        )
    builder.row(btn("🔙 В админ-панель", "back_admin"))

    await callback.message.edit_text(
        f"{pe('🤝')} <b>Управление партиями</b>\n\n"
        f"Нажми на название партии для начисления <b>+50 ПВ</b> или лиши партию регистрации (Статья 7.2):",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_padd_"))
async def adm_party_add_pts(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        return
    pid = callback.data[len("adm_padd_"):]
    p = await add_party_points(pid, 50)
    if p:
        await callback.answer(f"✅ Начислено +50 ПВ партии {p['name']}!", show_alert=True)
    await admin_parties(callback)


@router.callback_query(F.data.startswith("adm_pdel_"))
async def adm_party_delete(callback: CallbackQuery, bot: Bot):
    if not await is_owner(callback.from_user):
        return
    pid = callback.data[len("adm_pdel_"):]
    p = await delete_party_by_admin(pid)
    if p:
        st = await get_all_settings()
        topic_id = st["chancellery_topic_id"] or CHANCELLERY_TOPIC_ID
        try:
            await bot.send_message(
                chat_id=GROUP_ID,
                message_thread_id=topic_id,
                text=(
                    f"{pe('👑')} <b>КАНЦЕЛЯРИЯ RISE OF EUROPE</b>\n"
                    f"─────────────────────\n"
                    f"Политическая партия <b>{p['flag']} {esc(p['name'])}</b> [{esc(p['tag'])}] "
                    f"лишена государственной регистрации решением администрации проекта (Статья 7.2)."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass
        await callback.answer(f"🗑️ Партия {p['name']} лишена регистрации!", show_alert=True)
    await admin_parties(callback)


@router.callback_query(F.data == "admin_bills")
async def admin_bills(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    bills = await get_all_bills()
    if not bills:
        await callback.answer("Законопроектов пока нет!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for b in bills[-10:]:
        builder.row(
            btn(f"#{b['id']} [{b['status']}] {b['text'][:25]}", f"bopen_{b['id']}"),
            btn("Вето", f"bill_veto_{b['id']}", "👑")
        )
    builder.row(btn("🔙 В админ-панель", "back_admin"))

    await callback.message.edit_text(
        f"{pe('👑')} <b>Управление законопроектами</b>\n\nВыбери законопроект для просмотра или наложения Вето:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_elections")
async def admin_elections(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    st = await get_all_settings()
    votes = await get_election_votes()
    active = st["election_active"]
    wipes = st["wipes_passed"]
    target_wipes = st["wipes_per_election"]

    builder = InlineKeyboardBuilder()
    builder.row(btn("➕ Засчитать вайп (+1)", "el_wipe_inc"))
    if not active:
        builder.row(btn("🟢 Начать выборы в Парламент", "el_start"))
    else:
        builder.row(btn("🛑 Завершить выборы и выдать мандаты", "el_finish"))
    builder.row(btn("🔙 В админ-панель", "back_admin"))

    await callback.message.edit_text(
        f"{pe('👑')} <b>Избирательный процесс (Статья 4 и 6)</b>\n\n"
        f"Пройдено вайпов с прошлых выборов: <b>{wipes} из {target_wipes}</b>\n"
        f"Статус выборов: <b>{'🟢 Идёт голосование' if active else '⚪️ Не проводятся'}</b>\n"
        f"Проголосовало избирателей: <b>{len(votes)}</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "el_wipe_inc")
async def el_wipe_inc(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        return
    st = await get_all_settings()
    wipes = st["wipes_passed"] + 1
    target = st["wipes_per_election"]
    await set_setting("wipes_passed", wipes)

    if wipes >= target:
        await callback.answer(f"🔔 Прошло {wipes} вайпов! Пора начинать выборы в Парламент!", show_alert=True)
    else:
        await callback.answer(f"✅ Засчитан вайп ({wipes}/{target})")
    await admin_elections(callback)


@router.callback_query(F.data == "el_start")
async def el_start(callback: CallbackQuery, bot: Bot):
    if not await is_owner(callback.from_user):
        return

    st = await get_all_settings()
    parties = await get_all_parties()
    valid = [p for p in parties if len(p.get("members", [])) >= st["min_party_members"]]
    if not valid:
        await callback.answer("❌ Нет зарегистрированных партий с нужным минимумом участников!", show_alert=True)
        return

    await start_elections_db()
    p_lines = [f"{p['flag']} <b>{esc(p['name'])}</b> [{esc(p['tag'])}]" for p in valid]
    topic_id = st["chancellery_topic_id"] or CHANCELLERY_TOPIC_ID

    try:
        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=(
                f"{pe('👑')} <b>КАНЦЕЛЯРИЯ RISE OF EUROPE</b>\n"
                f"{pe('📢')} <b>Объявлены всеобщие выборы в Парламент!</b>\n"
                f"─────────────────────\n"
                f"<b>Партии в избирательном бюллетене:</b>\n"
                f"{_blockquote(chr(10).join(p_lines))}\n\n"
                f"Для голосования перейдите в бота Парламента и откройте раздел «Выборы в Парламент»."
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Ошибка публикации старта выборов: {e}")

    await callback.answer("🟢 Выборы официально запущены!", show_alert=True)
    await admin_elections(callback)


@router.callback_query(F.data == "el_finish")
async def el_finish(callback: CallbackQuery, bot: Bot):
    if not await is_owner(callback.from_user):
        return

    total_votes, results = await finish_elections_db()
    res_lines = [
        f"{p['flag']} <b>{esc(p['name'])}</b> [{esc(p['tag'])}] — <b>{v_c}</b> гол. ({pct}%) | Мандатов: <b>{seats}</b>"
        for v_c, pct, seats, p in results
    ]

    st = await get_all_settings()
    topic_id = st["chancellery_topic_id"] or CHANCELLERY_TOPIC_ID
    try:
        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=topic_id,
            text=(
                f"{pe('👑')} <b>КАНЦЕЛЯРИЯ RISE OF EUROPE</b>\n"
                f"{pe('📊')} <b>Официальные итоги выборов в Парламент</b>\n"
                f"─────────────────────\n"
                f"Всего проголосовало активных стран: <b>{total_votes}</b>\n\n"
                f"<b>Распределение мандатов:</b>\n"
                f"{_blockquote(chr(10).join(res_lines) if res_lines else 'Нет данных')}\n\n"
                f"{pe('✅')} <b>Новый созыв Парламента вступил в полномочия.</b>"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Ошибка публикации итогов выборов: {e}")

    await callback.answer("✅ Выборы завершены, итоги опубликованы в Канцелярии!", show_alert=True)
    await admin_elections(callback)


@router.callback_query(F.data == "admin_settings")
async def admin_settings(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    st = await get_all_settings()
    await callback.message.edit_text(
        f"{pe('🔧')} <b>Настройки регламента и лимитов</b>\n\n"
        f"Используй кнопки ниже для изменения численности партий, ценза постов и цикла выборов:",
        parse_mode="HTML",
        reply_markup=admin_settings_kb(st)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_"))
async def handle_settings_change(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        return

    st = await get_all_settings()
    act = callback.data

    if act == "set_pmin_mem_dec":
        await set_setting("min_party_members", max(2, st["min_party_members"] - 1))
    elif act == "set_pmin_mem_inc":
        await set_setting("min_party_members", min(st["max_party_members"], st["min_party_members"] + 1))
    elif act == "set_pmax_dec":
        await set_setting("max_party_members", max(st["min_party_members"], st["max_party_members"] - 1))
    elif act == "set_pmax_inc":
        await set_setting("max_party_members", min(20, st["max_party_members"] + 1))
    elif act == "set_pmin_dec":
        await set_setting("min_posts_to_vote", max(0, st["min_posts_to_vote"] - 1))
    elif act == "set_pmin_inc":
        await set_setting("min_posts_to_vote", min(20, st["min_posts_to_vote"] + 1))
    elif act == "set_wipes_dec":
        await set_setting("wipes_per_election", max(1, st["wipes_per_election"] - 1))
    elif act == "set_wipes_inc":
        await set_setting("wipes_per_election", min(15, st["wipes_per_election"] + 1))

    await admin_settings(callback)


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    users = await get_all_users()
    parties = await get_all_parties()
    bills = await get_all_bills()
    total_posts = sum(u.get("posts", 0) for u in users)
    passed = sum(1 for b in bills if b.get("status") == "passed")
    vetoed = sum(1 for b in bills if b.get("status") == "vetoed")

    await callback.message.edit_text(
        f"{pe('📊')} <b>Статистика Парламента Rise of Europe</b>\n\n"
        f"👥 Всего пользователей: <b>{len(users)}</b>\n"
        f"✍️ Засчитано РП-постов в новостнике: <b>{total_posts}</b>\n"
        f"🤝 Активных партий: <b>{len(parties)}</b>\n"
        f"📋 Всего законопроектов: <b>{len(bills)}</b>\n"
        f"✅ Принято законов: <b>{passed}</b>\n"
        f"👑 Наложено Вето: <b>{vetoed}</b>",
        parse_mode="HTML",
        reply_markup=back_to_admin_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_logs")
async def admin_logs(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    log_file = "data/bot.log"
    if not os.path.exists(log_file):
        await callback.message.answer("❌ Лог-файл не найден.", reply_markup=back_to_admin_kb())
        return

    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()[-50:]

    content = "".join(lines)[-4000:]
    file = BufferedInputFile(content.encode("utf-8"), filename="parliament_bot.log")
    await callback.message.answer_document(
        file,
        caption=f"📜 Последние 50 строк лога ({datetime.now().strftime('%d.%m.%Y %H:%M')})",
        reply_markup=back_to_admin_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_wipe")
async def admin_wipe(callback: CallbackQuery, state: FSMContext):
    if not await is_owner(callback.from_user):
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_wipe_confirm)
    await callback.message.edit_text(
        f"⚠️ <b>СБРОС СЕЗОНА ПАРЛАМЕНТА</b>\n\n"
        f"❗ Это действие:\n"
        f"▪️ Удалит все партии и законопроекты\n"
        f"▪️ Обнулит счётчики РП-постов у всех игроков\n\n"
        f"Для подтверждения напиши точно:\n<code>СБРОС</code>",
        parse_mode="HTML",
        reply_markup=back_to_admin_kb()
    )
    await callback.answer()


@router.message(AdminStates.waiting_wipe_confirm, F.chat.type == ChatType.PRIVATE, F.text)
async def handle_wipe_confirm(message: Message, state: FSMContext):
    if not await is_owner(message.from_user):
        return

    if message.text.strip() != "СБРОС":
        await message.answer(
            f"❌ Неверное слово. Напиши точно: <code>СБРОС</code>",
            parse_mode="HTML",
            reply_markup=back_to_admin_kb()
        )
        return

    p_count, b_count = await wipe_parliament_season()
    await state.clear()
    _, status = await _build_admin_header()
    await message.answer(
        f"✅ <b>Сезон Парламента сброшен!</b>\n\n"
        f"🗑️ Удалено партий: <b>{p_count}</b>\n"
        f"🗑️ Удалено законопроектов: <b>{b_count}</b>\n"
        f"🔄 Счётчики постов обнулены.",
        parse_mode="HTML",
        reply_markup=admin_panel_kb(status)
    )


@router.callback_query(F.data == "admin_shutdown")
async def admin_shutdown(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        return
    await set_setting("bot_status", "off")
    await callback.message.edit_text(
        f"🛑 <b>Бот переведён в режим техобслуживания.</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_kb("off")
    )
    await callback.answer("Бот выключен")


@router.callback_query(F.data == "admin_start_bot")
async def admin_start_bot(callback: CallbackQuery):
    if not await is_owner(callback.from_user):
        return
    await set_setting("bot_status", "on")
    await callback.message.edit_text(
        f"✅ <b>Бот снова включён и принимает команды!</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_kb("on")
    )
    await callback.answer("Бот включён")


# ===================== БЫСТРЫЕ КОМАНДЫ В ГРУППЕ =====================

@router.message(F.chat.id == GROUP_ID, F.text.startswith("!"))
async def group_admin_commands(message: Message, bot: Bot):
    if not await is_owner(message.from_user):
        return

    text = message.text.strip()
    cmd = text.lower()

    # !синк (в ответ на список стран)
    if cmd.startswith("!синк"):
        if message.reply_to_message:
            rep_text = message.reply_to_message.text or message.reply_to_message.caption or ""
            count = await parse_and_save_reg_text(rep_text)
            if count > 0:
                await message.reply(f"{pe('✅')} Синхронизировано позиций: <b>{count}</b>", parse_mode="HTML")
                return
        f_count = await sync_slots_from_reg_file()
        if f_count > 0:
            await message.reply(f"{pe('✅')} Синхронизировано из файла БД: <b>{f_count}</b> позиций", parse_mode="HTML")
        else:
            await message.reply("❌ Ответьте (reply) командой <code>!синк</code> на сообщение со списком стран от @RegistrationROEbot!", parse_mode="HTML")
        return

    # !партия (в ответ на сообщение о регистрации партии в Канцелярии)
    if cmd.startswith("!партия"):
        if not message.reply_to_message:
            await message.reply("❌ Ответьте (reply) командой <code>!партия КОД</code> на сообщение о регистрации партии в Канцелярии!", parse_mode="HTML")
            return

        rep = message.reply_to_message
        rep_text = (rep.text or rep.caption or "").lower()
        parts = text.split(maxsplit=1)
        query = parts[1].strip().lower() if len(parts) > 1 else ""

        parties = await get_all_parties()
        matched_party = None

        for p in parties:
            if query:
                if p["id"].lower() == query or p["tag"].lower() == query or query in p["name"].lower():
                    matched_party = p
                    break
            else:
                if p["name"].lower() in rep_text or f"[{p['tag'].lower()}]" in rep_text:
                    matched_party = p
                    break

        if not matched_party:
            await message.reply("❌ Партия не найдена. Укажите код или тег партии: <code>!партия КОД</code>", parse_mode="HTML")
            return

        updated_party = await set_party_chancellery_msg_id(matched_party["id"], rep.message_id)
        if updated_party:
            await sync_party_chancellery_post(bot, updated_party)
            await message.reply(
                f"{pe('✅')} Сообщение привязано к партии <b>{esc(updated_party['name'])}</b> [{esc(updated_party['tag'])}] и обновлено!",
                parse_mode="HTML"
            )
        return

    # !чсп
    if cmd.startswith("!чсп") and message.reply_to_message:
        target = message.reply_to_message.from_user
        if target:
            async with db_manager.transaction() as conn:
                await conn.execute("UPDATE users SET banned = CASE WHEN banned = 1 THEN 0 ELSE 1 END WHERE user_id = ?;", (target.id,))
            u = await get_user_data(target.id) or {}
            st = "забанен в Парламенте" if u.get("banned") else "разбанен в Парламенте"
            await message.reply(f"⚖️ <b>{esc(target.full_name)}</b>: <b>{st}</b>.", parse_mode="HTML")

    # !иммун
    elif cmd.startswith("!иммун") and message.reply_to_message:
        target = message.reply_to_message.from_user
        if target:
            async with db_manager.transaction() as conn:
                await conn.execute("UPDATE users SET immune = CASE WHEN immune = 1 THEN 0 ELSE 1 END WHERE user_id = ?;", (target.id,))
            u = await get_user_data(target.id) or {}
            st = "выдан" if u.get("immune") else "снят"
            await message.reply(f"👑 Иммунитет к цензу постов для <b>{esc(target.full_name)}</b>: <b>{st}</b>.", parse_mode="HTML")

    # !пв
    elif cmd.startswith("!пв") and message.reply_to_message:
        parts = text.split()
        if len(parts) >= 2:
            try:
                delta = int(parts[1])
                target = message.reply_to_message.from_user
                u = await get_user_data(target.id) or {}
                pid = u.get("party_id")
                if pid:
                    p = await add_party_points(pid, delta)
                    if p:
                        await message.reply(
                            f"💎 Партии <b>{esc(p['name'])}</b> изменены очки: <b>{delta:+} ПВ</b> "
                            f"(Баланс: <b>{p['points']} ПВ</b>)",
                            parse_mode="HTML"
                        )
            except ValueError:
                pass
