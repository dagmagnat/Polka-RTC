import asyncio
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

import qrcode
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_PROXY = os.getenv("BOT_PROXY", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

OLCRTC_BIN = os.getenv("OLCRTC_BIN", "/opt/olcrtc/bin/olcrtc")
DB_PATH = os.getenv("DB_PATH", "/var/lib/polka-rtc/polka.db")
DNS = os.getenv("DNS", "1.1.1.1:53")
VP8_FPS = os.getenv("VP8_FPS", "60")
VP8_BATCH = os.getenv("VP8_BATCH", "64")
BACKUP_DIR = os.getenv("BACKUP_DIR", "/var/backups/polka-rtc")

CLIENT_ENV_DIR = Path("/etc/olcrtc/clients")

if BOT_PROXY:
    bot = Bot(BOT_TOKEN, session=AiohttpSession(proxy=BOT_PROXY))
else:
    bot = Bot(BOT_TOKEN)

dp = Dispatcher()


class CreateClient(StatesGroup):
    provider = State()
    name = State()
    room = State()


class AddDevice(StatesGroup):
    provider = State()
    room = State()


PROVIDERS = {
    "wbstream_auto": {
        "title": "WB Stream — авто ID",
        "short": "WB auto",
        "carrier": "wbstream",
        "transport": "datachannel",
        "needs_room_input": False,
        "auto_room": True,
    },
    "wbstream_manual": {
        "title": "WB Stream — ручной ID",
        "short": "WB manual",
        "carrier": "wbstream",
        "transport": "datachannel",
        "needs_room_input": True,
        "auto_room": False,
    },
    "telemost": {
        "title": "Яндекс Телемост",
        "short": "Telemost",
        "carrier": "telemost",
        "transport": "vp8channel",
        "needs_room_input": True,
        "auto_room": False,
    },
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def run_cmd(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=True,
    )


def setup_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                device_no INTEGER NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                carrier TEXT NOT NULL,
                transport TEXT NOT NULL,
                room_id TEXT NOT NULL,
                auth_key TEXT NOT NULL,
                uri TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(clients)").fetchall()}
        if "provider" not in columns:
            conn.execute("ALTER TABLE clients ADD COLUMN provider TEXT NOT NULL DEFAULT ''")
        conn.commit()


def db_save(row: dict) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO clients
            (client_id, display_name, device_no, provider, carrier, transport, room_id, auth_key, uri, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                (SELECT created_at FROM clients WHERE client_id = ?),
                ?
            ))
            """,
            (
                row["client_id"], row["display_name"], row["device_no"], row["provider"],
                row["carrier"], row["transport"], row["room_id"], row["auth_key"], row["uri"],
                row["client_id"], int(time.time()),
            ),
        )
        conn.commit()


def db_all():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM clients ORDER BY lower(display_name), device_no, created_at"
        ).fetchall()


def db_get(client_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()


def db_delete(client_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM clients WHERE client_id = ?", (client_id,))
        conn.commit()


def next_device_no(display_name: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(device_no), 0) + 1 FROM clients WHERE display_name = ?",
            (display_name,),
        ).fetchone()
        return int(row[0] or 1)


def slugify(text: str) -> str:
    ru = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    text = text.lower().strip()
    text = "".join(ru.get(ch, ch) for ch in text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text or "client")[:28]


def make_client_id(name: str, device_no: int) -> str:
    return f"{slugify(name)}-{device_no:02d}-{secrets.token_hex(3)}"


def make_key() -> str:
    return secrets.token_hex(32)


def extract_room_id(text: str) -> str:
    digit = re.findall(r"\d{6,}", text)
    if digit:
        return digit[0]

    uuid_like = re.findall(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        text,
    )
    if uuid_like:
        return uuid_like[0]

    found = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9-]{5,}", text)
    bad = {
        "https", "http", "telemost", "yandex", "wbstream", "stream", "wb", "ru",
        "com", "www", "join", "meeting",
    }
    for item in found:
        item = item.strip().strip("/")
        if item.lower() not in bad:
            return item
    return ""


def generate_room_id(carrier: str) -> str:
    result = run_cmd(
        [
            OLCRTC_BIN,
            "-mode", "gen",
            "-carrier", carrier,
            "-dns", DNS,
            "-amount", "1",
            "-data", "data",
        ],
        timeout=180,
    )
    lines = [x.strip() for x in result.stdout.splitlines() if x.strip()]
    if not lines:
        raise RuntimeError(f"olcrtc не вернул Room ID. STDERR:\n{result.stderr}")
    return lines[-1]


def make_uri(carrier: str, transport: str, room_id: str, auth_key: str, client_id: str) -> str:
    return f"olcrtc://{carrier}?{transport}@{room_id}#{auth_key}%{client_id}$PolkaRTC"


def write_env(row: dict) -> None:
    CLIENT_ENV_DIR.mkdir(parents=True, exist_ok=True)
    env_path = CLIENT_ENV_DIR / f"{row['client_id']}.env"

    lines = [
        f"CARRIER={row['carrier']}",
        f"TRANSPORT={row['transport']}",
        f"ROOM_ID={row['room_id']}",
        f"CLIENT_ID={row['client_id']}",
        f"AUTH_KEY={row['auth_key']}",
        f"DNS={DNS}",
    ]

    if row["transport"] == "vp8channel":
        lines.append(f"VP8_FPS={VP8_FPS}")
        lines.append(f"VP8_BATCH={VP8_BATCH}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)


def service_name(client_id: str) -> str:
    return f"olcrtc-client@{client_id}.service"


def start_service(client_id: str) -> None:
    run_cmd(["systemctl", "daemon-reload"], timeout=60)
    run_cmd(["systemctl", "enable", "--now", service_name(client_id)], timeout=60)


def stop_service(client_id: str) -> None:
    subprocess.run(["systemctl", "stop", service_name(client_id)], text=True)
    subprocess.run(["systemctl", "disable", service_name(client_id)], text=True)


def restart_service(client_id: str) -> None:
    run_cmd(["systemctl", "restart", service_name(client_id)], timeout=60)


def is_active(client_id: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", service_name(client_id)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.strip() == "active"


def get_logs(client_id: str) -> str:
    result = subprocess.run(
        ["journalctl", "-u", service_name(client_id), "-n", "80", "--no-pager"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    text = result.stdout.strip() or result.stderr.strip()
    return text[-3500:] if text else "Логов пока нет."


def create_backup() -> str:
    result = run_cmd(["/usr/local/bin/polka-rtc-backup"], timeout=120)
    path = result.stdout.strip().splitlines()[-1]
    if not Path(path).exists():
        raise RuntimeError(f"backup file not found: {path}")
    return path


def clients_inline_kb() -> InlineKeyboardMarkup | None:
    rows = db_all()
    if not rows:
        return None

    buttons = []
    for row in rows:
        active = is_active(row["client_id"])
        status = "🟢" if active else "🔴"
        provider_key = row["provider"] or row["carrier"]
        provider_title = PROVIDERS.get(provider_key, {}).get("short", provider_key)
        label = f"{status} {row['display_name']}-{row['device_no']} | {provider_title}"
        buttons.append([
            InlineKeyboardButton(
                text=label[:60],
                callback_data=f"client:{row['client_id']}",
            )
        ])

    buttons.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def help_text() -> str:
    return (
        "Режимы создания:\n\n"
        "1. WB Stream — авто ID\n"
        "   Бот запускает olcrtc -mode gen и сам получает Room ID.\n\n"
        "2. WB Stream — ручной ID\n"
        "   Вы заранее создаёте/берёте Room ID и вставляете его в бота.\n\n"
        "3. Яндекс Телемост\n"
        "   Вы заранее создаёте встречу и вставляете ID/ссылку.\n\n"
        "Одно устройство = одна отдельная ссылка и один QR.\n"
        "Если авто WB не подключается, используйте WB Stream — ручной ID."
    )


BTN_CREATE = "➕ Создать клиента"
BTN_CLIENTS = "📋 Список клиентов"
BTN_BACKUP = "💾 Создать бэкап"
BTN_HELP = "ℹ️ Помощь"


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE)],
            [KeyboardButton(text=BTN_CLIENTS)],
            [KeyboardButton(text=BTN_BACKUP)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите действие",
    )


def provider_kb(prefix: str = "provider") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟣 WB Stream — авто ID", callback_data=f"{prefix}:wbstream_auto")],
            [InlineKeyboardButton(text="✍️ WB Stream — ручной ID", callback_data=f"{prefix}:wbstream_manual")],
            [InlineKeyboardButton(text="🟡 Яндекс Телемост", callback_data=f"{prefix}:telemost")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu")],
        ]
    )


def client_kb(client_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Ссылка", callback_data=f"link:{client_id}")],
            [InlineKeyboardButton(text="📷 QR", callback_data=f"qr:{client_id}")],
            [InlineKeyboardButton(text="➕ Добавить устройство", callback_data=f"add:{client_id}")],
            [InlineKeyboardButton(text="🔄 Перезапустить", callback_data=f"restart:{client_id}")],
            [InlineKeyboardButton(text="📜 Логи", callback_data=f"logs:{client_id}")],
            [InlineKeyboardButton(text="🗑 Удалить устройство", callback_data=f"del:{client_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="list")],
        ]
    )


def confirm_delete_kb(client_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delok:{client_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"client:{client_id}")],
        ]
    )


async def send_uri(message: Message, client_id: str, uri: str) -> None:
    await message.answer(
        f"Клиент: <b>{client_id}</b>\n\nСсылка:\n<code>{uri}</code>",
        parse_mode="HTML",
    )


async def send_qr(message: Message, client_id: str, uri: str) -> None:
    img = qrcode.make(uri)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    img.save(tmp.name)
    try:
        await message.answer_photo(FSInputFile(tmp.name), caption=f"QR для {client_id}")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


async def create_device(message: Message, display_name: str, provider_key: str, room_id: str | None = None) -> None:
    provider = PROVIDERS[provider_key]
    carrier = provider["carrier"]
    transport = provider["transport"]
    device_no = next_device_no(display_name)
    client_id = make_client_id(display_name, device_no)

    if provider["needs_room_input"]:
        if not room_id:
            raise RuntimeError("Не указан Room ID")
    else:
        room_id = generate_room_id(carrier)

    auth_key = make_key()
    uri = make_uri(carrier, transport, room_id, auth_key, client_id)

    row = {
        "client_id": client_id,
        "display_name": display_name,
        "device_no": device_no,
        "provider": provider_key,
        "carrier": carrier,
        "transport": transport,
        "room_id": room_id,
        "auth_key": auth_key,
        "uri": uri,
    }

    write_env(row)
    start_service(client_id)
    db_save(row)

    await message.answer(
        f"Готово.\nКлиент: <b>{display_name}</b>\nУстройство: <b>{device_no}</b>\n"
        f"Провайдер: <b>{provider['title']}</b>\nRoom ID: <code>{room_id}</code>",
        parse_mode="HTML",
    )
    await send_uri(message, client_id, uri)
    await send_qr(message, client_id, uri)


async def ask_room_id(message: Message, provider_key: str) -> None:
    provider = PROVIDERS[provider_key]
    if provider["carrier"] == "wbstream":
        await message.answer(
            "Отправьте ID WB Stream.\n\n"
            "Можно вставить только ID, например:\n"
            "<code>019e20e6-9f02-77db-a198-2e97a3278d89</code>\n\n"
            "Или вставить ссылку/текст, если ID в нём присутствует.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "Отправьте ID/ссылку Яндекс Телемоста.\n\n"
            "Например:\n"
            "<code>https://telemost.yandex.ru/j/220722504595729</code>",
            parse_mode="HTML",
        )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await message.answer("Polka RTC\n\nВыберите действие:", reply_markup=main_kb())


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("Отменено.", reply_markup=main_kb())


@dp.message(Command("create"))
@dp.message(F.text == BTN_CREATE)
async def cmd_create(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await state.clear()
    await state.set_state(CreateClient.provider)
    await message.answer("Выберите режим:", reply_markup=provider_kb("provider"))


@dp.message(Command("clients"))
@dp.message(F.text == BTN_CLIENTS)
async def cmd_clients(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await state.clear()
    keyboard = clients_inline_kb()

    if keyboard is None:
        await message.answer("Клиентов пока нет.", reply_markup=main_kb())
        return

    await message.answer("Клиенты:", reply_markup=keyboard)


@dp.message(Command("backup"))
@dp.message(F.text == BTN_BACKUP)
async def cmd_backup(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await state.clear()
    await message.answer("Создаю бэкап...")

    try:
        path = create_backup()
        await message.answer_document(
            FSInputFile(path),
            caption=f"Бэкап Polka RTC\n{Path(path).name}",
        )
    except Exception as e:
        await message.answer(
            f"Ошибка бэкапа:\n\n<code>{str(e)}</code>",
            parse_mode="HTML",
        )


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def cmd_help(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await state.clear()
    await message.answer(help_text(), reply_markup=main_kb())


@dp.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.answer(help_text(), reply_markup=main_kb())
    await callback.answer()


@dp.callback_query(F.data == "create")
async def create_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await state.set_state(CreateClient.provider)
    await callback.message.answer("Выберите режим:", reply_markup=provider_kb("provider"))
    await callback.answer()


@dp.callback_query(F.data.startswith("provider:"))
async def choose_provider(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    provider_key = callback.data.split(":", 1)[1]
    if provider_key not in PROVIDERS:
        await callback.answer("Неизвестный режим", show_alert=True)
        return
    await state.update_data(provider=provider_key)
    await state.set_state(CreateClient.name)
    provider = PROVIDERS[provider_key]
    await callback.message.answer(
        f"Режим: {provider['title']}\n"
        f"Carrier: {provider['carrier']}\n"
        f"Transport: {provider['transport']}\n\n"
        "Введите имя клиента."
    )
    await callback.answer()


@dp.message(CreateClient.name)
async def create_name(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Имя слишком короткое. Введите ещё раз.")
        return
    await state.update_data(name=name)
    data = await state.get_data()
    provider = PROVIDERS[data["provider"]]
    if provider["needs_room_input"]:
        await state.set_state(CreateClient.room)
        await ask_room_id(message, data["provider"])
    else:
        try:
            await create_device(message, name, data["provider"])
            await state.clear()
            await message.answer("Меню:", reply_markup=main_kb())
        except Exception as e:
            await state.clear()
            await message.answer(f"Ошибка создания:\n\n<code>{str(e)}</code>", parse_mode="HTML")


@dp.message(CreateClient.room)
async def create_room(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    room_id = extract_room_id(message.text)
    if not room_id:
        await message.answer("Не нашёл ID. Отправьте ссылку или ID ещё раз.")
        return
    try:
        await create_device(message, data["name"], data["provider"], room_id)
        await state.clear()
        await message.answer("Меню:", reply_markup=main_kb())
    except Exception as e:
        await state.clear()
        await message.answer(f"Ошибка создания:\n\n<code>{str(e)}</code>", parse_mode="HTML")


@dp.callback_query(F.data == "list")
async def list_clients(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    keyboard = clients_inline_kb()
    if keyboard is None:
        await callback.message.answer("Клиентов пока нет.", reply_markup=main_kb())
        await callback.answer()
        return

    await callback.message.answer("Клиенты:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("client:"))
async def client_info(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    client_id = callback.data.split(":", 1)[1]
    row = db_get(client_id)
    if not row:
        await callback.message.answer("Клиент не найден.", reply_markup=main_kb())
        await callback.answer()
        return
    active = is_active(client_id)
    provider_key = row["provider"] or row["carrier"]
    provider_title = PROVIDERS.get(provider_key, {}).get("title", provider_key)
    await callback.message.answer(
        f"Клиент: <b>{row['display_name']}</b>\n"
        f"Устройство: {row['device_no']}\n"
        f"ID: <code>{row['client_id']}</code>\n"
        f"Статус: {'🟢 работает' if active else '🔴 не работает'}\n"
        f"Режим: {provider_title}\n"
        f"Carrier: {row['carrier']}\n"
        f"Transport: {row['transport']}\n"
        f"Room ID: <code>{row['room_id']}</code>",
        parse_mode="HTML",
        reply_markup=client_kb(client_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("add:"))
async def add_device_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    client_id = callback.data.split(":", 1)[1]
    row = db_get(client_id)
    if not row:
        await callback.message.answer("Клиент не найден.")
        await callback.answer()
        return
    await state.clear()
    await state.update_data(display_name=row["display_name"])
    await state.set_state(AddDevice.provider)
    await callback.message.answer(
        f"Добавить устройство для: <b>{row['display_name']}</b>\n\nВыберите режим:",
        parse_mode="HTML",
        reply_markup=provider_kb("addprovider"),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("addprovider:"))
async def add_provider(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    provider_key = callback.data.split(":", 1)[1]
    if provider_key not in PROVIDERS:
        await callback.answer("Неизвестный режим", show_alert=True)
        return
    await state.update_data(provider=provider_key)
    data = await state.get_data()
    provider = PROVIDERS[provider_key]
    if provider["needs_room_input"]:
        await state.set_state(AddDevice.room)
        await ask_room_id(callback.message, provider_key)
    else:
        try:
            await create_device(callback.message, data["display_name"], provider_key)
            await state.clear()
            await callback.message.answer("Меню:", reply_markup=main_kb())
        except Exception as e:
            await state.clear()
            await callback.message.answer(f"Ошибка создания:\n\n<code>{str(e)}</code>", parse_mode="HTML")
    await callback.answer()


@dp.message(AddDevice.room)
async def add_room(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    room_id = extract_room_id(message.text)
    if not room_id:
        await message.answer("Не нашёл ID. Отправьте ссылку или ID ещё раз.")
        return
    try:
        await create_device(message, data["display_name"], data["provider"], room_id)
        await state.clear()
        await message.answer("Меню:", reply_markup=main_kb())
    except Exception as e:
        await state.clear()
        await message.answer(f"Ошибка создания:\n\n<code>{str(e)}</code>", parse_mode="HTML")


@dp.callback_query(F.data.startswith("link:"))
async def show_link(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    row = db_get(callback.data.split(":", 1)[1])
    if row:
        await send_uri(callback.message, row["client_id"], row["uri"])
    else:
        await callback.message.answer("Клиент не найден.")
    await callback.answer()


@dp.callback_query(F.data.startswith("qr:"))
async def show_qr(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    row = db_get(callback.data.split(":", 1)[1])
    if row:
        await send_qr(callback.message, row["client_id"], row["uri"])
    else:
        await callback.message.answer("Клиент не найден.")
    await callback.answer()


@dp.callback_query(F.data.startswith("restart:"))
async def restart_client(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    client_id = callback.data.split(":", 1)[1]
    try:
        restart_service(client_id)
        await callback.message.answer(f"Перезапущен: {client_id}")
    except Exception as e:
        await callback.message.answer(f"Ошибка перезапуска:\n\n<code>{str(e)}</code>", parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("logs:"))
async def show_logs(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    client_id = callback.data.split(":", 1)[1]
    text = get_logs(client_id)
    await callback.message.answer(f"Логи {client_id}:\n\n<code>{text}</code>", parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("del:"))
async def delete_ask(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    client_id = callback.data.split(":", 1)[1]
    await callback.message.answer(
        f"Удалить устройство?\n\n<code>{client_id}</code>",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(client_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delok:"))
async def delete_ok(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    client_id = callback.data.split(":", 1)[1]
    try:
        stop_service(client_id)
        env_path = CLIENT_ENV_DIR / f"{client_id}.env"
        if env_path.exists():
            env_path.unlink()
        db_delete(client_id)
        await callback.message.answer(f"Удалено: {client_id}", reply_markup=main_kb())
    except Exception as e:
        await callback.message.answer(f"Ошибка удаления:\n\n<code>{str(e)}</code>", parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "backup")
async def backup_cb(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.answer("Создаю бэкап...")
    try:
        path = create_backup()
        await callback.message.answer_document(
            FSInputFile(path),
            caption=f"Бэкап Polka RTC\n{Path(path).name}",
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка бэкапа:\n\n<code>{str(e)}</code>", parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.answer("Меню:", reply_markup=main_kb())
    await callback.answer()


async def main() -> None:
    setup_db()

    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть меню"),
        BotCommand(command="create", description="Создать клиента"),
        BotCommand(command="clients", description="Список клиентов"),
        BotCommand(command="backup", description="Создать бэкап"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="cancel", description="Отменить действие"),
    ])

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
