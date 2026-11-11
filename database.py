"""
Слой хранения данных (Repository) и доменной логики (Service).
Использует aiosqlite в режиме WAL с контролем транзакций, индексацией и версионированием схемы.
"""

import asyncio
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Dict, List, Tuple

import aiosqlite
from config import CFG


# ===================== ДОМЕННАЯ ВАЛИДАЦИЯ =====================

class ValidationError(Exception):
    """Ошибка валидации входных данных"""
    pass


class Validator:
    TAG_REGEX = re.compile(r"^[A-ZА-ЯЁ0-9\-]{2,8}$")

    @classmethod
    def validate_party_name(cls, name: str) -> str:
        clean = (name or "").strip()
        if not (3 <= len(clean) <= 60):
            raise ValidationError("Название партии должно быть от 3 до 60 символов.")
        return clean

    @classmethod
    def validate_party_tag(cls, tag: str) -> str:
        clean = (tag or "").strip().upper()
        if not cls.TAG_REGEX.match(clean):
            raise ValidationError("Тег партии должен содержать от 2 до 8 букв или цифр без пробелов.")
        return clean

    @classmethod
    def validate_party_flag(cls, flag: str) -> str:
        clean = (flag or "").strip()
        if not (1 <= len(clean) <= 4):
            raise ValidationError("Отправьте ровно один эмодзи или флаг.")
        return clean

    @classmethod
    def validate_program(cls, program: str) -> str:
        clean = (program or "").strip()
        if not (20 <= len(clean) <= 800):
            raise ValidationError("Программа партии должна содержать от 20 до 800 символов (Статья 3).")
        return clean

    @classmethod
    def validate_bill_text(cls, text: str) -> str:
        clean = (text or "").strip()
        if not (20 <= len(clean) <= 2000):
            raise ValidationError("Текст законопроекта должен содержать от 20 до 2000 символов.")
        return clean


# ===================== СХЕМА БД И МИГРАЦИИ =====================

MIGRATIONS: Dict[int, List[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            full_name TEXT NOT NULL DEFAULT '',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            posts INTEGER NOT NULL DEFAULT 0,
            last_post_ts INTEGER NOT NULL DEFAULT 0,
            party_id TEXT DEFAULT NULL,
            immune INTEGER NOT NULL DEFAULT 0,
            banned INTEGER NOT NULL DEFAULT 0
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(LOWER(username));
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_users_fullname ON users(LOWER(full_name));
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_users_party ON users(party_id);
        """,
        """
        CREATE TABLE IF NOT EXISTS slots (
            slot_name TEXT PRIMARY KEY,
            slot_flag TEXT NOT NULL DEFAULT '🏳️',
            slot_type TEXT NOT NULL DEFAULT 'country',
            user_id INTEGER DEFAULT NULL,
            username TEXT NOT NULL DEFAULT '',
            full_name TEXT NOT NULL DEFAULT ''
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_slots_userid ON slots(user_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_slots_username ON slots(LOWER(username));
        """,
        """
        CREATE TABLE IF NOT EXISTS parties (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            tag TEXT NOT NULL,
            flag TEXT NOT NULL,
            program TEXT NOT NULL,
            leader_id INTEGER NOT NULL,
            points INTEGER NOT NULL DEFAULT 30,
            seats INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS party_members (
            party_id TEXT NOT NULL,
            user_id INTEGER NOT NULL UNIQUE,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (party_id, user_id),
            FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS pending_parties (
            req_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tag TEXT NOT NULL,
            flag TEXT NOT NULL,
            program TEXT NOT NULL,
            leader_id INTEGER NOT NULL,
            leader_name TEXT NOT NULL,
            leader_username TEXT NOT NULL,
            invited_json TEXT NOT NULL,
            confirmed_json TEXT NOT NULL,
            sent_to_admin INTEGER NOT NULL DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id TEXT DEFAULT NULL,
            author_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            author_slot TEXT NOT NULL,
            category TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status);
        """,
        """
        CREATE TABLE IF NOT EXISTS bill_votes (
            bill_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            vote_type TEXT NOT NULL CHECK(vote_type IN ('for', 'against', 'abstain')),
            PRIMARY KEY (bill_id, user_id),
            FOREIGN KEY (bill_id) REFERENCES bills(id) ON DELETE CASCADE
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_bill_votes_bill ON bill_votes(bill_id);
        """,
        """
        CREATE TABLE IF NOT EXISTS election_votes (
            user_id INTEGER PRIMARY KEY,
            party_id TEXT NOT NULL,
            FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE CASCADE
        );
        """
    ]
}

DEFAULT_SETTINGS = {
    "bot_status": "on",
    "owner_id": str(CFG.owner_id),
    "co_admin_id": "0",
    "min_party_members": "3",
    "max_party_members": "6",
    "min_posts_to_vote": "1",
    "min_post_length": "150",
    "points_per_post": "10",
    "post_cooldown": "600",
    "wipes_per_election": "3",
    "wipes_passed": "0",
    "election_active": "0",
    "chancellery_topic_id": str(CFG.chancellery_topic_id),
}


# ===================== МЕНЕДЖЕР ПОДКЛЮЧЕНИЯ И ТРАНЗАКЦИЙ =====================

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()

    async def connect(self):
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path, timeout=10.0)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode = WAL;")
            await self._conn.execute("PRAGMA synchronous = NORMAL;")
            await self._conn.execute("PRAGMA foreign_keys = ON;")
            await self._conn.execute("PRAGMA busy_timeout = 5000;")
            await self._run_migrations()
            await self._init_defaults()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    @asynccontextmanager
    async def transaction(self):
        """Атомарная транзакция с защитой от гонок (race conditions)"""
        await self.connect()
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE;")
            try:
                yield self._conn
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise

    @property
    def conn(self) -> aiosqlite.Connection:
        return self._conn

    async def _run_migrations(self):
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);"
        )
        async with self._conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations;") as cur:
            row = await cur.fetchone()
            current_ver = row[0] if row else 0

        for ver in sorted(MIGRATIONS.keys()):
            if ver > current_ver:
                for sql in MIGRATIONS[ver]:
                    await self._conn.execute(sql)
                await self._conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                    (ver, datetime.now().isoformat())
                )
        await self._conn.commit()

    async def _init_defaults(self):
        async with self.transaction() as conn:
            for k, v in DEFAULT_SETTINGS.items():
                await conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?);",
                    (k, v)
                )


db_manager = DatabaseManager(CFG.sqlite_path)


async def init_db():
    await db_manager.connect()


async def close_db():
    await db_manager.close()


# ===================== РЕПОЗИТОРИЙ И СЕРВИСНЫЙ СЛОЙ =====================

async def get_setting(key: str) -> str:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT value FROM settings WHERE key = ?;", (key,)) as cur:
        row = await cur.fetchone()
        return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


async def get_int_setting(key: str) -> int:
    val = await get_setting(key)
    return int(val) if val.lstrip("-").isdigit() else int(DEFAULT_SETTINGS.get(key, "0"))


async def set_setting(key: str, value) -> None:
    async with db_manager.transaction() as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
            (key, str(value))
        )


async def get_all_settings() -> dict:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT key, value FROM settings;") as cur:
        rows = await cur.fetchall()
    res = dict(DEFAULT_SETTINGS)
    for r in rows:
        res[r["key"]] = r["value"]
    return {
        "bot_status": res["bot_status"],
        "min_party_members": int(res["min_party_members"]),
        "max_party_members": int(res["max_party_members"]),
        "min_posts_to_vote": int(res["min_posts_to_vote"]),
        "min_post_length": int(res["min_post_length"]),
        "points_per_post": int(res["points_per_post"]),
        "post_cooldown": int(res["post_cooldown"]),
        "wipes_per_election": int(res["wipes_per_election"]),
        "wipes_passed": int(res["wipes_passed"]),
        "election_active": res["election_active"] == "1",
        "chancellery_topic_id": int(res["chancellery_topic_id"]),
    }


async def is_owner(user) -> bool:
    if not user:
        return False
    uname = (user.username or "").lower()
    if uname == CFG.owner_username.lower():
        await set_setting("owner_id", user.id)
        return True
    if uname == CFG.co_admin_username.lower():
        await set_setting("co_admin_id", user.id)
        return True
    owner_id = await get_int_setting("owner_id")
    co_id = await get_int_setting("co_admin_id")
    return user.id in (owner_id, co_id) and user.id != 0


async def get_admin_ids() -> List[int]:
    owner_id = await get_int_setting("owner_id")
    co_id = await get_int_setting("co_admin_id")
    return [uid for uid in {owner_id, co_id} if uid > 0]


# ===================== ПОЛЬЗОВАТЕЛИ И СИНХРОНИЗАЦИЯ СТРАН =====================

async def register_user_activity(user_id: int, username: str, full_name: str) -> dict:
    now = datetime.now().isoformat()
    uname = (username or "").strip()
    fname = (full_name or str(user_id)).strip()

    async with db_manager.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO users (user_id, username, full_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = CASE WHEN excluded.username != '' THEN excluded.username ELSE users.username END,
                full_name = CASE WHEN excluded.full_name != '' THEN excluded.full_name ELSE users.full_name END,
                last_seen = excluded.last_seen;
            """,
            (user_id, uname, fname, now, now)
        )
        # Авто-привязка ID к распарсенному слоту по юзернейму или имени
        if uname:
            await conn.execute(
                "UPDATE slots SET user_id = ?, full_name = ? WHERE LOWER(username) = LOWER(?);",
                (user_id, fname, uname)
            )
        if fname:
            await conn.execute(
                "UPDATE slots SET user_id = ?, username = ? WHERE user_id IS NULL AND LOWER(full_name) = LOWER(?);",
                (user_id, uname, fname)
            )

    return await get_user_data(user_id)


async def get_user_data(user_id: int) -> Optional[dict]:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM users WHERE user_id = ?;", (user_id,)) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_users() -> List[dict]:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM users ORDER BY posts DESC;") as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def find_user_by_query(query: str) -> Optional[dict]:
    await db_manager.connect()
    q = query.strip().lstrip("@")
    if q.isdigit():
        u = await get_user_data(int(q))
        if u:
            return u
    async with db_manager.conn.execute(
        "SELECT * FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(full_name) = LOWER(?) LIMIT 1;",
        (q, q)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def sync_slots_from_reg_file() -> int:
    if not CFG.reg_bot_db_path or not os.path.exists(CFG.reg_bot_db_path):
        return 0
    try:
        with open(CFG.reg_bot_db_path, "r", encoding="utf-8", errors="replace") as f:
            reg_db = json.load(f)
    except Exception:
        return 0

    regs = reg_db.get("registrations")
    if not isinstance(regs, dict):
        return 0

    async with db_manager.transaction() as conn:
        await conn.execute("DELETE FROM slots;")
        for r in regs.values():
            await conn.execute(
                """
                INSERT OR REPLACE INTO slots (slot_name, slot_flag, slot_type, user_id, username, full_name)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    r.get("slot_name", "?"),
                    r.get("slot_flag", "🏳️"),
                    r.get("slot_type", "country"),
                    r.get("user_id"),
                    r.get("username", ""),
                    r.get("full_name", "")
                )
            )
    return len(regs)


async def parse_and_save_reg_text(text: str) -> int:
    if not text or "Занятые страны" not in text:
        return 0

    parsed_rows = []
    in_section = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(h in line for h in ("Занятые страны", "Занятые МО/Вице", "Занятые ЧВК", "Занятые террористические")):
            in_section = True
            continue
        if "Основные лица проекта" in line:
            break
        if not in_section or line.lower().startswith("свободн") or "─────" in line:
            continue

        sep = " — " if " — " in line else (" - " if " - " in line else None)
        if not sep:
            continue

        left_part, mention = [x.strip() for x in line.split(sep, 1)]
        parts = left_part.split(" ", 1)
        if len(parts) == 2 and not parts[0][0].isalnum():
            flag, slot_name = parts[0].strip(), parts[1].strip()
        else:
            flag, slot_name = "🏳️", left_part

        uid = None
        uname, fname = "", ""
        if mention.startswith("@"):
            uname = mention.lstrip("@").strip()
        elif mention.startswith("Пользователь #"):
            num = mention.replace("Пользователь #", "").strip()
            if num.isdigit():
                uid = int(num)
        else:
            fname = mention

        parsed_rows.append((slot_name, flag, uid, uname, fname))

    if not parsed_rows:
        return 0

    async with db_manager.transaction() as conn:
        await conn.execute("DELETE FROM slots;")
        for slot_name, flag, uid, uname, fname in parsed_rows:
            if not uid:
                async with conn.execute(
                    "SELECT user_id, username, full_name FROM users WHERE (username != '' AND LOWER(username) = LOWER(?)) OR (full_name != '' AND LOWER(full_name) = LOWER(?)) LIMIT 1;",
                    (uname or "^$", fname or "^$")
                ) as cur:
                    u_row = await cur.fetchone()
                    if u_row:
                        uid = u_row["user_id"]
                        uname = uname or u_row["username"]
                        fname = fname or u_row["full_name"]

            await conn.execute(
                "INSERT OR REPLACE INTO slots (slot_name, slot_flag, slot_type, user_id, username, full_name) VALUES (?, ?, 'country', ?, ?, ?);",
                (slot_name, flag, uid, uname, fname)
            )
    return len(parsed_rows)


async def get_user_slot(user_id: int, username: str = "", full_name: str = "") -> Optional[dict]:
    await sync_slots_from_reg_file()
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM slots WHERE user_id = ? LIMIT 1;", (user_id,)) as cur:
        row = await cur.fetchone()
        if row:
            return dict(row)

    if username or full_name:
        async with db_manager.transaction() as conn:
            if username:
                await conn.execute(
                    "UPDATE slots SET user_id = ? WHERE LOWER(username) = LOWER(?);",
                    (user_id, username)
                )
            if full_name:
                await conn.execute(
                    "UPDATE slots SET user_id = ? WHERE user_id IS NULL AND LOWER(full_name) = LOWER(?);",
                    (user_id, full_name)
                )
        async with db_manager.conn.execute("SELECT * FROM slots WHERE user_id = ? LIMIT 1;", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
    return None


async def count_slots() -> int:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT COUNT(*) FROM slots;") as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


async def bind_user_slot_manual(user_id: int, flag: str, slot_name: str):
    u = await get_user_data(user_id) or {}
    async with db_manager.transaction() as conn:
        await conn.execute("DELETE FROM slots WHERE user_id = ?;", (user_id,))
        await conn.execute(
            "INSERT OR REPLACE INTO slots (slot_name, slot_flag, slot_type, user_id, username, full_name) VALUES (?, ?, 'country', ?, ?, ?);",
            (slot_name, flag, user_id, u.get("username", ""), u.get("full_name", str(user_id)))
        )


async def try_record_rp_post(user_id: int, text_len: int) -> Optional[Tuple[int, Optional[str], int]]:
    """Атомарно проверяет длину и кулдаун поста, начисляет +1 пост игроку и ПВ его партии."""
    st = await get_all_settings()
    if text_len < st["min_post_length"]:
        return None

    now_ts = int(datetime.now().timestamp())
    async with db_manager.transaction() as conn:
        async with conn.execute("SELECT posts, last_post_ts, party_id FROM users WHERE user_id = ?;", (user_id,)) as cur:
            u = await cur.fetchone()
        if not u or (now_ts - u["last_post_ts"] < st["post_cooldown"]):
            return None

        new_posts = u["posts"] + 1
        await conn.execute(
            "UPDATE users SET posts = ?, last_post_ts = ? WHERE user_id = ?;",
            (new_posts, now_ts, user_id)
        )

        party_name = None
        pts = 0
        pid = u["party_id"]
        if pid:
            async with conn.execute("SELECT name FROM parties WHERE id = ?;", (pid,)) as pcur:
                prow = await pcur.fetchone()
            if prow:
                pts = st["points_per_post"]
                party_name = prow["name"]
                await conn.execute("UPDATE parties SET points = points + ? WHERE id = ?;", (pts, pid))

        return new_posts, party_name, pts


async def can_user_vote(user) -> Tuple[bool, str, Optional[dict]]:
    u_data = await register_user_activity(user.id, user.username or "", user.full_name or "")
    if await is_owner(user):
        slot = await get_user_slot(user.id, user.username or "", user.full_name or "") or {
            "slot_flag": "👑", "slot_name": "Администрация"
        }
        return True, "", slot

    if u_data.get("banned"):
        return False, "⛔ Вы заблокированы в Парламенте!", None

    slot = await get_user_slot(user.id, user.username or "", user.full_name or "")
    if not slot:
        return False, "⛔ Голосовать могут только игроки на занятых странах и позициях!", None

    min_posts = await get_int_setting("min_posts_to_vote")
    if not u_data.get("immune") and u_data.get("posts", 0) < min_posts:
        return False, f"⛔ Для голосования нужно минимум {min_posts} РП-пост в новостнике!", slot

    return True, "", slot


# ===================== ПАРТИИ И ЗАЯВКИ НА РЕГИСТРАЦИЮ =====================

async def _hydrate_party(conn: aiosqlite.Connection, row: aiosqlite.Row) -> dict:
    p = dict(row)
    async with conn.execute("SELECT user_id FROM party_members WHERE party_id = ? ORDER BY joined_at;", (p["id"],)) as mcur:
        mrows = await mcur.fetchall()
    p["members"] = [r["user_id"] for r in mrows]
    return p


async def get_all_parties() -> List[dict]:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM parties ORDER BY points DESC;") as cur:
        rows = await cur.fetchall()
    return [await _hydrate_party(db_manager.conn, r) for r in rows]


async def get_party_by_id(party_id: str) -> Optional[dict]:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM parties WHERE id = ?;", (party_id.upper(),)) as cur:
        row = await cur.fetchone()
    return await _hydrate_party(db_manager.conn, row) if row else None


async def get_user_party(user_id: int) -> Optional[dict]:
    u = await get_user_data(user_id)
    if not u or not u.get("party_id"):
        return None
    return await get_party_by_id(u["party_id"])


async def create_pending_party(leader, name: str, tag: str, flag: str, program: str, invited_ids: List[int]) -> str:
    req_id = uuid.uuid4().hex[:8]
    async with db_manager.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO pending_parties (req_id, name, tag, flag, program, leader_id, leader_name, leader_username, invited_json, confirmed_json, sent_to_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0);
            """,
            (
                req_id, name, tag, flag, program,
                leader.id, leader.full_name or str(leader.id), leader.username or "",
                json.dumps(invited_ids), json.dumps([leader.id])
            )
        )
    return req_id


async def get_pending_party(req_id: str) -> Optional[dict]:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM pending_parties WHERE req_id = ?;", (req_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["invited_ids"] = json.loads(d["invited_json"])
    d["confirmed_ids"] = json.loads(d["confirmed_json"])
    return d


async def confirm_pending_party_member(req_id: str, user_id: int) -> Tuple[Optional[dict], bool]:
    """Добавляет подтверждение участника. Возвращает (заявка, нужно_ли_отправить_админу)"""
    min_mem = await get_int_setting("min_party_members")
    async with db_manager.transaction() as conn:
        async with conn.execute("SELECT * FROM pending_parties WHERE req_id = ?;", (req_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None, False

        d = dict(row)
        confirmed = json.loads(d["confirmed_json"])
        if user_id not in confirmed:
            confirmed.append(user_id)

        should_send = len(confirmed) >= min_mem and d["sent_to_admin"] == 0
        new_sent = 1 if should_send else d["sent_to_admin"]

        await conn.execute(
            "UPDATE pending_parties SET confirmed_json = ?, sent_to_admin = ? WHERE req_id = ?;",
            (json.dumps(confirmed), new_sent, req_id)
        )
        d["invited_ids"] = json.loads(d["invited_json"])
        d["confirmed_ids"] = confirmed
        return d, should_send


async def finalize_pending_party(req_id: str, approve: bool) -> Optional[dict]:
    req = await get_pending_party(req_id)
    if not req:
        return None

    async with db_manager.transaction() as conn:
        await conn.execute("DELETE FROM pending_parties WHERE req_id = ?;", (req_id,))
        if not approve:
            return req

        pid = uuid.uuid4().hex[:6].upper()
        now = datetime.now().isoformat()
        await conn.execute(
            """
            INSERT INTO parties (id, name, tag, flag, program, leader_id, points, seats, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 30, 0, ?);
            """,
            (pid, req["name"], req["tag"], req["flag"], req["program"], req["leader_id"], now)
        )
        for uid in req["confirmed_ids"]:
            await conn.execute(
                "INSERT OR IGNORE INTO party_members (party_id, user_id, joined_at) VALUES (?, ?, ?);",
                (pid, uid, now)
            )
            await conn.execute("UPDATE users SET party_id = ? WHERE user_id = ?;", (pid, uid))

        req["party_id"] = pid
        return req


async def join_party_by_code(user_id: int, code: str) -> Tuple[bool, str, Optional[dict]]:
    max_mem = await get_int_setting("max_party_members")
    party = await get_party_by_id(code)
    if not party:
        return False, "Партия с таким кодом не найдена.", None
    if len(party["members"]) >= max_mem:
        return False, f"В партии достигнут лимит участников ({max_mem}).", None

    now = datetime.now().isoformat()
    async with db_manager.transaction() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO party_members (party_id, user_id, joined_at) VALUES (?, ?, ?);",
            (party["id"], user_id, now)
        )
        await conn.execute("UPDATE users SET party_id = ? WHERE user_id = ?;", (party["id"], user_id))
    return True, "OK", await get_party_by_id(code)


async def leave_or_remove_from_party(user_id: int) -> Optional[str]:
    u = await get_user_data(user_id)
    if not u or not u.get("party_id"):
        return None
    pid = u["party_id"]
    party = await get_party_by_id(pid)
    if not party:
        return None

    async with db_manager.transaction() as conn:
        await conn.execute("DELETE FROM party_members WHERE party_id = ? AND user_id = ?;", (pid, user_id))
        await conn.execute("UPDATE users SET party_id = NULL WHERE user_id = ?;", (user_id,))
        async with conn.execute("SELECT user_id FROM party_members WHERE party_id = ? ORDER BY joined_at;", (pid,)) as cur:
            rem = [r["user_id"] for r in await cur.fetchall()]
        if not rem:
            await conn.execute("DELETE FROM parties WHERE id = ?;", (pid,))
        elif party["leader_id"] == user_id:
            await conn.execute("UPDATE parties SET leader_id = ? WHERE id = ?;", (rem[0], pid))

    return party["name"]


async def delete_party_by_admin(party_id: str) -> Optional[dict]:
    party = await get_party_by_id(party_id)
    if not party:
        return None
    async with db_manager.transaction() as conn:
        await conn.execute("UPDATE users SET party_id = NULL WHERE party_id = ?;", (party_id,))
        await conn.execute("DELETE FROM parties WHERE id = ?;", (party_id,))
    return party


async def add_party_points(party_id: str, delta: int) -> Optional[dict]:
    async with db_manager.transaction() as conn:
        await conn.execute(
            "UPDATE parties SET points = MAX(0, points + ?) WHERE id = ?;",
            (delta, party_id)
        )
    return await get_party_by_id(party_id)


# ===================== ЗАКОНОПРОЕКТЫ И ТРАНЗАКЦИОННОЕ ГОЛОСОВАНИЕ =====================

async def _hydrate_bill(conn: aiosqlite.Connection, row: aiosqlite.Row) -> dict:
    b = dict(row)
    b["id"] = str(b["id"])
    async with conn.execute("SELECT user_id, vote_type FROM bill_votes WHERE bill_id = ?;", (row["id"],)) as vcur:
        vrows = await vcur.fetchall()
    b["votes_for"] = [r["user_id"] for r in vrows if r["vote_type"] == "for"]
    b["votes_against"] = [r["user_id"] for r in vrows if r["vote_type"] == "against"]
    b["votes_abstain"] = [r["user_id"] for r in vrows if r["vote_type"] == "abstain"]
    return b


async def create_bill(
    party_id: Optional[str],
    author_id: int,
    author_name: str,
    author_slot: str,
    category: str,
    text: str,
    cost: int,
    is_admin: bool
) -> dict:
    now = datetime.now().isoformat()
    async with db_manager.transaction() as conn:
        if party_id and not is_admin:
            async with conn.execute("SELECT points FROM parties WHERE id = ?;", (party_id,)) as cur:
                prow = await cur.fetchone()
            if not prow or prow["points"] < cost:
                raise ValidationError(f"Недостаточно ПВ у партии (требуется {cost} ПВ).")
            await conn.execute("UPDATE parties SET points = points - ? WHERE id = ?;", (cost, party_id))

        cur = await conn.execute(
            """
            INSERT INTO bills (party_id, author_id, author_name, author_slot, category, text, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?);
            """,
            (party_id, author_id, author_name, author_slot, category, text, now)
        )
        bid = cur.lastrowid
        async with conn.execute("SELECT * FROM bills WHERE id = ?;", (bid,)) as bcur:
            brow = await bcur.fetchone()
        return await _hydrate_bill(conn, brow)


async def get_bill(bill_id: str) -> Optional[dict]:
    if not str(bill_id).isdigit():
        return None
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM bills WHERE id = ?;", (int(bill_id),)) as cur:
        row = await cur.fetchone()
    return await _hydrate_bill(db_manager.conn, row) if row else None


async def get_all_bills() -> List[dict]:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT * FROM bills ORDER BY id ASC;") as cur:
        rows = await cur.fetchall()
    return [await _hydrate_bill(db_manager.conn, r) for r in rows]


async def cast_bill_vote(bill_id: str, user_id: int, vote_type: str) -> Optional[dict]:
    """Транзакционная запись голоса без возможности гонки данных"""
    if not str(bill_id).isdigit():
        return None
    bid = int(bill_id)
    async with db_manager.transaction() as conn:
        async with conn.execute("SELECT * FROM bills WHERE id = ? AND status = 'active';", (bid,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None

        await conn.execute(
            """
            INSERT INTO bill_votes (bill_id, user_id, vote_type)
            VALUES (?, ?, ?)
            ON CONFLICT(bill_id, user_id) DO UPDATE SET vote_type = excluded.vote_type;
            """,
            (bid, user_id, vote_type)
        )
        return await _hydrate_bill(conn, row)


async def set_bill_status(bill_id: str, status: str) -> Optional[dict]:
    if not str(bill_id).isdigit():
        return None
    bid = int(bill_id)
    async with db_manager.transaction() as conn:
        await conn.execute("UPDATE bills SET status = ? WHERE id = ?;", (status, bid))
        async with conn.execute("SELECT * FROM bills WHERE id = ?;", (bid,)) as cur:
            row = await cur.fetchone()
        return await _hydrate_bill(conn, row) if row else None


# ===================== ВЫБОРЫ И СБРОС СЕЗОНА =====================

async def cast_election_vote(user_id: int, party_id: str) -> bool:
    if await get_setting("election_active") != "1":
        return False
    async with db_manager.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO election_votes (user_id, party_id) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET party_id = excluded.party_id;
            """,
            (user_id, party_id)
        )
    return True


async def get_election_votes() -> Dict[int, str]:
    await db_manager.connect()
    async with db_manager.conn.execute("SELECT user_id, party_id FROM election_votes;") as cur:
        rows = await cur.fetchall()
    return {r["user_id"]: r["party_id"] for r in rows}


async def start_elections_db():
    async with db_manager.transaction() as conn:
        await conn.execute("DELETE FROM election_votes;")
        await conn.execute("UPDATE settings SET value = '1' WHERE key = 'election_active';")


async def finish_elections_db() -> Tuple[int, List[Tuple[int, float, int, dict]]]:
    votes = await get_election_votes()
    parties = await get_all_parties()
    total_votes = len(votes)
    total_seats = 100
    results = []

    async with db_manager.transaction() as conn:
        for p in parties:
            v_c = sum(1 for v in votes.values() if v == p["id"])
            pct = round((v_c / total_votes) * 100, 1) if total_votes > 0 else 0.0
            seats = round((v_c / total_votes) * total_seats) if total_votes > 0 else 0
            await conn.execute("UPDATE parties SET seats = ? WHERE id = ?;", (seats, p["id"]))
            p["seats"] = seats
            results.append((v_c, pct, seats, p))

        await conn.execute("UPDATE settings SET value = '0' WHERE key = 'election_active';")
        await conn.execute("UPDATE settings SET value = '0' WHERE key = 'wipes_passed';")

    results.sort(key=lambda x: x[0], reverse=True)
    return total_votes, results


async def wipe_parliament_season() -> Tuple[int, int]:
    parties = await get_all_parties()
    bills = await get_all_bills()
    async with db_manager.transaction() as conn:
        await conn.execute("DELETE FROM election_votes;")
        await conn.execute("DELETE FROM bill_votes;")
        await conn.execute("DELETE FROM bills;")
        await conn.execute("DELETE FROM party_members;")
        await conn.execute("DELETE FROM parties;")
        await conn.execute("DELETE FROM pending_parties;")
        await conn.execute("UPDATE users SET posts = 0, party_id = NULL, last_post_ts = 0;")
    return len(parties), len(bills)