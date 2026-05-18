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

APP_VERSION = "original-olcrtc-refactor-bot-2026-05-18-1"

OLCRTC_BIN = os.getenv("OLCRTC_BIN", "/opt/olcrtc/bin/olcrtc")
DB_PATH = os.getenv("DB_PATH", "/var/lib/polka-rtc/polka.db")
DNS = os.getenv("DNS", "1.1.1.1:53")
VP8_FPS = os.getenv("VP8_FPS", "60")
VP8_BATCH = os.getenv("VP8_BATCH", "64")
BACKUP_DIR = os.getenv("BACKUP_DIR", "/var/backups/polka-rtc")
OLCRTC_GENERATION = os.getenv("OLCRTC_GENERATION", "legacy").strip().lower()
OLCRTC_URI_FORMAT = os.getenv("OLCRTC_URI_FORMAT", "legacy").strip().lower()

TELEMOST_STABLE_MODE = os.getenv("TELEMOST_STABLE_MODE", "1").strip() != "0"
TELEMOST_AUTO_RESTART_MINUTES = os.getenv("TELEMOST_AUTO_RESTART_MINUTES", "0").strip() or "0"
TELEMOST_LOG_STALL_MINUTES = os.getenv("TELEMOST_LOG_STALL_MINUTES", "0").strip() or "0"

CLIENT_ENV_DIR = Path("/etc/olcrtc/clients")

if BOT_PROXY:
    bot = Bot(BOT_TOKEN, session=AiohttpSession(proxy=BOT_PROXY))
else:
    bot = Bot(BOT_TOKEN)

dp = Dispatcher()


class CreateClient(StatesGroup):
    provider = State()
    wb_transport = State()
    wb_room_mode = State()
    name = State()
    room = State()


class AddDevice(StatesGroup):
    provider = State()
    wb_transport = State()
    wb_room_mode = State()
    room = State()


class EditRoom(StatesGroup):
    room = State()


PROVIDERS = {
    "jitsi": {
        "title": "Jitsi Meet",
        "short": "Jitsi",
        "carrier": "jitsi",
        "transport": "datachannel",
        "description": "рекомендуется авторами olcrtc для стабильного datachannel",
    },
    "telemost": {
        "title": "Яндекс Телемост",
        "short": "Telemost",
        "carrier": "telemost",
        "transport": "vp8channel",
        "description": "работает через vp8channel, но тяжелый трафик может перегружать канал",
    },
    "wbstream": {
        "title": "WB Stream",
        "short": "WB",
        "carrier": "wbstream",
        "description": "оставлен как информационный режим: сейчас часто возвращает 502/guest ограничения",
    },
}

WB_TRANSPORTS = {
    "vp8channel": {
        "title": "vp8channel — рекомендуется для WB Stream",
        "short": "vp8",
        "warning": "",
    },
    "datachannel": {
        "title": "datachannel — экспериментально, нужны права canPublishData",
        "short": "data",
        "warning": "⚠️ WB Stream + datachannel сейчас часто не работает в обычном guest-режиме, если участникам не выданы права canPublishData. Рекомендуется vp8channel.",
    },
}

WB_STREAM_DOWN_MESSAGE = (
    "🟣 WB Stream сейчас оставлен как информационный режим.\n\n"
    "По твоим тестам WB Stream возвращал 502 Bad Gateway и не запускался ни через datachannel, ни через vp8channel.\n"
    "В официальной матрице refactor/universal-carrier WB помечен рабочим не для datachannel, "
    "но guest-flow и ручные комнаты могут отличаться. Поэтому бот не выдаёт WB-ссылки по умолчанию.\n\n"
    "Основные рабочие режимы в этой сборке:\n"
    "🟢 Jitsi + datachannel — основной рекомендуемый режим olcrtc.\n"
    "🟡 Telemost + vp8channel — запасной режим."
)

WB_AUTO_ID_WARNING = (
    "⚠️ WB Stream сейчас может не создавать Room ID автоматически: "
    "WB отключал авто-создание комнат и гостевой доступ. "
    "Функция оставлена на случай, если её вернут. Надёжнее выбрать ручной ID."
)


BTN_CREATE = "➕ Создать клиента"
BTN_CLIENTS = "📋 Список клиентов"
BTN_BACKUP = "💾 Создать бэкап"
BTN_HELP = "ℹ️ Помощь"


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
                row["client_id"],
                row["display_name"],
                row["device_no"],
                row["provider"],
                row["carrier"],
                row["transport"],
                row["room_id"],
                row["auth_key"],
                row["uri"],
                row["client_id"],
                int(time.time()),
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


def db_update_room(client_id: str, room_id: str, uri: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE clients SET room_id = ?, uri = ? WHERE client_id = ?",
            (room_id, uri, client_id),
        )
        conn.commit()


def next_device_no(display_name: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(device_no), 0) + 1 FROM clients WHERE display_name = ?",
            (display_name,),
        ).fetchone()
        return int(row[0] or 1)


def stats() -> dict:
    rows = db_all()
    active = 0
    by_provider = {}
    by_transport = {}

    for row in rows:
        if is_active(row["client_id"]):
            active += 1

        provider = row["provider"] or row["carrier"]
        by_provider[provider] = by_provider.get(provider, 0) + 1

        transport = row["transport"]
        by_transport[transport] = by_transport.get(transport, 0) + 1

    return {
        "total": len(rows),
        "active": active,
        "stopped": len(rows) - active,
        "by_provider": by_provider,
        "by_transport": by_transport,
    }


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


def extract_room_id(text: str, carrier: str = "") -> str:
    value = (text or "").strip()

    # Jitsi works best with the full meeting URL, for example:
    # https://meet.cryptopro.ru/myroom or https://meet.jit.si/myroom
    if carrier == "jitsi":
        return value

    digit = re.findall(r"\d{6,}", value)
    if digit:
        return digit[0]

    uuid_like = re.findall(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        value,
    )
    if uuid_like:
        return uuid_like[0]

    found = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9-]{5,}", value)
    bad = {
        "https", "http", "telemost", "yandex", "wbstream", "stream", "wb", "ru",
        "com", "www", "join", "meeting", "room",
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
    if OLCRTC_URI_FORMAT == "refactor":
        payload = ""
        if transport == "vp8channel":
            payload = f"<vp8-fps={VP8_FPS}&vp8-batch={VP8_BATCH}>"
        return f"olcrtc://{carrier}?{transport}{payload}@{room_id}#{auth_key}$PolkaRTC"
    return f"olcrtc://{carrier}?{transport}@{room_id}#{auth_key}%{client_id}$PolkaRTC"


def client_yaml_path(client_id: str) -> Path:
    return CLIENT_ENV_DIR / f"{client_id}.yaml"


def make_server_yaml(row: dict) -> str:
    transport = row["transport"]
    vp8_block = ""
    if transport == "vp8channel":
        vp8_block = f"""
vp8:
  fps: {int(VP8_FPS)}
  batch_size: {int(VP8_BATCH)}
"""
    return f"""mode: srv
link: direct

auth:
  provider: {row["carrier"]}

room:
  id: "{row["room_id"]}"

crypto:
  key: "{row["auth_key"]}"

net:
  transport: {transport}
  dns: "{DNS}"

liveness:
  interval: 10s
  timeout: 5s
  failures: 3

socks:
  proxy_addr: ""
  proxy_port: 0
{vp8_block}
data: data
debug: false
"""


def write_env(row: dict) -> None:
    CLIENT_ENV_DIR.mkdir(parents=True, exist_ok=True)
    env_path = CLIENT_ENV_DIR / f"{row['client_id']}.env"
    yaml_path = client_yaml_path(row["client_id"])

    lines = [
        f"CARRIER={row['carrier']}",
        f"TRANSPORT={row['transport']}",
        f"ROOM_ID={row['room_id']}",
        f"CLIENT_ID={row['client_id']}",
        f"AUTH_KEY={row['auth_key']}",
        f"DNS={DNS}",
        f"OLCRTC_GENERATION={OLCRTC_GENERATION}",
        f"CONFIG_FILE={yaml_path}",
    ]

    if row["carrier"] == "telemost":
        lines.append(f"TELEMOST_STABLE_MODE={'1' if TELEMOST_STABLE_MODE else '0'}")
        lines.append(f"TELEMOST_AUTO_RESTART_MINUTES={TELEMOST_AUTO_RESTART_MINUTES}")
        lines.append(f"TELEMOST_LOG_STALL_MINUTES={TELEMOST_LOG_STALL_MINUTES}")

    if row["transport"] == "vp8channel":
        lines.append(f"VP8_FPS={VP8_FPS}")
        lines.append(f"VP8_BATCH={VP8_BATCH}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)

    yaml_path.write_text(make_server_yaml(row), encoding="utf-8")
    yaml_path.chmod(0o600)


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


def reset_failed_service(client_id: str) -> None:
    subprocess.run(["systemctl", "reset-failed", service_name(client_id)], text=True)


def stable_restart_service(client_id: str) -> None:
    reset_failed_service(client_id)
    restart_service(client_id)


def is_enabled(client_id: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-enabled", service_name(client_id)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip() == "enabled"


def service_main_pid(client_id: str) -> str:
    result = subprocess.run(
        ["systemctl", "show", service_name(client_id), "-p", "MainPID", "--value"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def service_uptime_text(client_id: str) -> str:
    pid = service_main_pid(client_id)
    if not pid or pid == "0":
        return "нет активного процесса"

    result = subprocess.run(
        ["ps", "-o", "etimes=", "-p", pid],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        seconds = int(result.stdout.strip())
    except Exception:
        return "неизвестно"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours} ч {minutes} мин"


def watchdog_status_text() -> str:
    timer_result = subprocess.run(
        ["systemctl", "is-active", "polka-rtc-watchdog.timer"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    timer = timer_result.stdout.strip() or "unknown"

    service_result = subprocess.run(
        ["systemctl", "is-active", "polka-rtc-watchdog.service"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    service = service_result.stdout.strip() or "unknown"

    return f"timer={timer}, service={service}"


def is_active(client_id: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", service_name(client_id)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip() == "active"


def get_logs(client_id: str, lines: int = 80) -> str:
    result = subprocess.run(
        ["journalctl", "-u", service_name(client_id), "-n", str(lines), "--no-pager"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    text = result.stdout.strip() or result.stderr.strip()
    return text[-3500:] if text else "Логов пока нет."


def get_service_status(client_id: str) -> str:
    result = subprocess.run(
        ["systemctl", "status", service_name(client_id), "--no-pager", "-l"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    return result.stdout.strip()[-3500:] or "нет вывода"


def get_env_safe(client_id: str) -> str:
    env_path = CLIENT_ENV_DIR / f"{client_id}.env"
    if not env_path.exists():
        return "env-файл не найден."

    safe_lines = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("AUTH_KEY="):
            safe_lines.append("AUTH_KEY=***hidden***")
        else:
            safe_lines.append(line)

    yaml_path = client_yaml_path(client_id)
    if yaml_path.exists():
        safe_lines.append("")
        safe_lines.append("YAML_CONFIG=present")

    return "\n".join(safe_lines)


def create_backup() -> str:
    result = run_cmd(["/usr/local/bin/polka-rtc-backup"], timeout=120)
    path = result.stdout.strip().splitlines()[-1]
    if not Path(path).exists():
        raise RuntimeError(f"backup file not found: {path}")
    return path


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
            [InlineKeyboardButton(text="🟢 Jitsi Meet — datachannel", callback_data=f"{prefix}:jitsi")],
            [InlineKeyboardButton(text="🟡 Яндекс Телемост — vp8channel", callback_data=f"{prefix}:telemost")],
            [InlineKeyboardButton(text="🟣 WB Stream — информация", callback_data="wb_info")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu")],
        ]
    )


def wb_transport_kb(prefix: str = "wbtransport") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎥 vp8channel — рекомендуется", callback_data=f"{prefix}:vp8channel")],
            [InlineKeyboardButton(text="⚠️ datachannel — экспериментально", callback_data=f"{prefix}:datachannel")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="create")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
        ]
    )


def wb_room_mode_kb(prefix: str = "wbroom") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ввести ID вручную — рекомендуется", callback_data=f"{prefix}:manual")],
            [InlineKeyboardButton(text="🤖 Авто-ID — может не работать", callback_data=f"{prefix}:auto")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="create")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
        ]
    )


def clients_inline_kb() -> InlineKeyboardMarkup | None:
    rows = db_all()
    if not rows:
        return None

    buttons = []
    for row in rows:
        active = is_active(row["client_id"])
        status = "🟢" if active else "🔴"
        provider_key = row["provider"] or row["carrier"]

        if row["carrier"] == "wbstream":
            provider_title = f"WB {WB_TRANSPORTS.get(row['transport'], {}).get('short', row['transport'])}"
        else:
            provider_title = PROVIDERS.get(provider_key, {}).get("short", provider_key)

        label = f"{status} {row['display_name']}-{row['device_no']} | {provider_title}"
        buttons.append([
            InlineKeyboardButton(
                text=label[:60],
                callback_data=f"client:{row['client_id']}",
            )
        ])

    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def client_kb(client_id: str) -> InlineKeyboardMarkup:
    active = is_active(client_id)

    start_stop_row = (
        [InlineKeyboardButton(text="⏸ Остановить", callback_data=f"stop:{client_id}")]
        if active
        else [InlineKeyboardButton(text="▶️ Запустить", callback_data=f"startsvc:{client_id}")]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Ссылка", callback_data=f"link:{client_id}")],
            [InlineKeyboardButton(text="📷 QR", callback_data=f"qr:{client_id}")],
            [InlineKeyboardButton(text="➕ Добавить устройство", callback_data=f"add:{client_id}")],
            [InlineKeyboardButton(text="🔁 Сменить Room ID", callback_data=f"editroom:{client_id}")],
            [InlineKeyboardButton(text="🔄 Перезапустить", callback_data=f"restart:{client_id}")],
            [InlineKeyboardButton(text="♻️ Reset failed + restart", callback_data=f"stable_restart:{client_id}")],
            start_stop_row,
            [InlineKeyboardButton(text="🧪 Диагностика", callback_data=f"diag:{client_id}")],
            [InlineKeyboardButton(text="📜 Логи", callback_data=f"logs:{client_id}")],
            [InlineKeyboardButton(text="🔎 Статус systemd", callback_data=f"svcstatus:{client_id}")],
            [InlineKeyboardButton(text="🗑 Удалить устройство", callback_data=f"del:{client_id}")],
            [InlineKeyboardButton(text="📋 Список клиентов", callback_data="list")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
        ]
    )


def confirm_delete_kb(client_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delok:{client_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"client:{client_id}")],
        ]
    )


def help_text() -> str:
    return (
        "Как работает Polka RTC:\n\n"
        "• Одна ссылка рассчитана на одно устройство/одно подключение.\n"
        "• Не передавайте одну ссылку двум людям: одновременно она может работать только у одного или конфликтовать.\n"
        "• Если одному клиенту нужно несколько устройств — создайте ему несколько отдельных ссылок.\n\n"
        "Рабочий основной режим:\n"
        "1. Яндекс Телемост\n"
        "   Используется telemost + vp8channel. Нужно заранее создать встречу и вставить ID/ссылку.\n\n"
        "WB Stream:\n"
        "2. Сейчас временно отключён для создания клиентов: по тестам возвращает 502 Bad Gateway.\n"
        "3. Кнопка WB оставлена только как информационная, если метод позже восстановится.\n\n"
        "Рекомендуемый сценарий сейчас: Telemost + отдельная ссылка на каждого клиента/устройство.\n\n"
        "Стабильность Telemost:\n"
        "• systemd автоматически перезапускает упавшие подключения;\n"
        "• watchdog перезапускает только failed/inactive enabled сервисы;\n"
        "• active-сессии не перезапускаются автоматически;\n"
        "• кнопка ♻️ Stable restart вручную сбрасывает Telemost-подключение;\n"
        "• если клиент после Stop/Start не возвращается, нажмите ♻️ Stable restart и затем Start в приложении."
    )


def dashboard_text() -> str:
    data = stats()
    by_provider = data["by_provider"]
    by_transport = data["by_transport"]

    wb_count = by_provider.get("wbstream", 0)
    telemost_count = by_provider.get("telemost", 0)

    data_count = by_transport.get("datachannel", 0)
    vp8_count = by_transport.get("vp8channel", 0)

    return (
        "Polka RTC\n\n"
        "📊 Дашборд\n"
        f"Версия: {APP_VERSION}\n"
        f"Всего устройств: {data['total']}\n"
        f"🟢 Работают: {data['active']}\n"
        f"🔴 Остановлены: {data['stopped']}\n\n"
        "Провайдеры:\n"
        f"🟣 WB Stream: {wb_count} — инфо/выключено\n"
        f"🟡 Яндекс Телемост: {telemost_count}\n\n"
        "Транспорты:\n"
        f"⚡ datachannel: {data_count}\n"
        f"🎥 vp8channel: {vp8_count}\n\n"
        f"Режим olcrtc: {OLCRTC_GENERATION}\n"
        f"Telemost safe watchdog: {'on' if TELEMOST_STABLE_MODE else 'off'} / active-сессии не трогаем\n"
        f"Watchdog: {watchdog_status_text()}\n"
        "Правило: 1 ссылка = 1 устройство."
    )


async def send_main_menu(message: Message) -> None:
    await message.answer(dashboard_text(), reply_markup=main_kb())


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


async def ask_room_id(message: Message, carrier: str) -> None:
    if carrier == "jitsi":
        await message.answer(
            "Отправьте ссылку Jitsi-комнаты.\n\n"
            "Рекомендуемый пример:\n"
            "<code>https://meet.cryptopro.ru/polka-room-001</code>\n\n"
            "Можно использовать и другой Jitsi Meet, например meet.jit.si. "
            "Для каждого клиента лучше создавать отдельную комнату/ссылку.",
            parse_mode="HTML",
        )
    elif carrier == "wbstream":
        await message.answer(WB_STREAM_DOWN_MESSAGE)
    else:
        await message.answer(
            "Отправьте ID/ссылку Яндекс Телемоста.\n\n"
            "Например:\n"
            "<code>https://telemost.yandex.ru/j/220722504595729</code>\n\n"
            "Каждому человеку/устройству лучше выдавать отдельную ссылку Polka RTC.",
            parse_mode="HTML",
        )


async def create_device(
    message: Message,
    display_name: str,
    provider_key: str,
    transport: str,
    room_mode: str,
    room_id: str | None = None,
) -> None:
    provider = PROVIDERS[provider_key]
    carrier = provider["carrier"]

    device_no = next_device_no(display_name)
    client_id = make_client_id(display_name, device_no)

    if room_mode == "manual":
        if not room_id:
            raise RuntimeError("Не указан Room ID")
    elif room_mode == "auto":
        if carrier == "wbstream":
            await message.answer(WB_AUTO_ID_WARNING)
        room_id = generate_room_id(carrier)
    else:
        raise RuntimeError(f"Неизвестный режим Room ID: {room_mode}")

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
        f"Готово.\n"
        f"Клиент: <b>{display_name}</b>\n"
        f"Устройство: <b>{device_no}</b>\n"
        f"Провайдер: <b>{provider['title']}</b>\n"
        f"Transport: <b>{transport}</b>\n"
        f"Room ID: <code>{room_id}</code>\n\n"
        "Важно: эта ссылка рассчитана на одно устройство. Для второго человека или второго устройства создайте новую ссылку.",
        parse_mode="HTML",
    )
    await send_uri(message, client_id, uri)
    await send_qr(message, client_id, uri)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await send_main_menu(message)


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
    await message.answer("Выберите провайдера:", reply_markup=provider_kb("provider"))


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
    await callback.message.answer("Выберите провайдера:", reply_markup=provider_kb("provider"))
    await callback.answer()


@dp.callback_query(F.data == "wb_info")
async def wb_info(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.answer(WB_STREAM_DOWN_MESSAGE, reply_markup=provider_kb("provider"))
    await callback.answer()


@dp.callback_query(F.data.startswith("provider:"))
async def choose_provider(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    provider_key = callback.data.split(":", 1)[1]
    if provider_key not in PROVIDERS:
        await callback.answer("Неизвестный провайдер", show_alert=True)
        return

    if provider_key == "wbstream":
        await state.clear()
        await callback.message.answer(WB_STREAM_DOWN_MESSAGE, reply_markup=provider_kb("provider"))
        await callback.answer()
        return

    provider = PROVIDERS[provider_key]
    transport = provider.get("transport", "vp8channel")

    await state.update_data(provider=provider_key)
    await state.update_data(transport=transport, room_mode="manual")
    await state.set_state(CreateClient.name)

    if provider_key == "jitsi":
        text = (
            "Jitsi Meet — рекомендуемый оригинальный режим olcrtc\n"
            "Carrier: jitsi\n"
            "Transport: datachannel\n\n"
            "Введите имя клиента."
        )
    else:
        text = (
            "Яндекс Телемост — запасной режим\n"
            "Carrier: telemost\n"
            "Transport: vp8channel\n\n"
            "Введите имя клиента."
        )

    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data.startswith("wbtransport:"))
async def choose_wb_transport(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    transport = callback.data.split(":", 1)[1]
    if transport not in WB_TRANSPORTS:
        await callback.answer("Неизвестный transport", show_alert=True)
        return

    await state.update_data(transport=transport)
    await state.set_state(CreateClient.wb_room_mode)

    warning = WB_TRANSPORTS.get(transport, {}).get("warning", "")
    text = f"WB Stream\nTransport: {transport}\n\n"
    if warning:
        text += warning + "\n\n"
    text += "Как получить ID звонка?"

    await callback.message.answer(
        text,
        reply_markup=wb_room_mode_kb("wbroom"),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("wbroom:"))
async def choose_wb_room_mode(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    room_mode = callback.data.split(":", 1)[1]
    if room_mode not in {"auto", "manual"}:
        await callback.answer("Неизвестный режим ID", show_alert=True)
        return

    await state.update_data(room_mode=room_mode)
    await state.set_state(CreateClient.name)

    mode_text = "автоматический ID" if room_mode == "auto" else "ручной ID"
    text = f"WB Stream\nРежим: {mode_text}\n\n"
    if room_mode == "auto":
        text += WB_AUTO_ID_WARNING + "\n\n"
    text += "Введите имя клиента."
    await callback.message.answer(text)
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

    if data["room_mode"] == "manual":
        await state.set_state(CreateClient.room)
        await ask_room_id(message, PROVIDERS[data["provider"]]["carrier"])
        return

    try:
        await create_device(
            message,
            name,
            data["provider"],
            data["transport"],
            data["room_mode"],
        )
        await state.clear()
        await send_main_menu(message)
    except Exception as e:
        await state.clear()
        await message.answer(f"Ошибка создания:\n\n<code>{str(e)}</code>", parse_mode="HTML")


@dp.message(CreateClient.room)
async def create_room(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    room_id = extract_room_id(message.text, PROVIDERS[data["provider"]]["carrier"])

    if not room_id:
        await message.answer("Не нашёл ID. Отправьте ссылку или ID ещё раз.")
        return

    try:
        await create_device(
            message,
            data["name"],
            data["provider"],
            data["transport"],
            data["room_mode"],
            room_id,
        )
        await state.clear()
        await send_main_menu(message)
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
        f"Провайдер: {provider_title}\n"
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
        f"Добавить устройство для: <b>{row['display_name']}</b>\n\nВыберите провайдера:",
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
        await callback.answer("Неизвестный провайдер", show_alert=True)
        return

    if provider_key == "wbstream":
        await state.clear()
        await callback.message.answer(WB_STREAM_DOWN_MESSAGE, reply_markup=provider_kb("addprovider"))
        await callback.answer()
        return

    provider = PROVIDERS[provider_key]
    await state.update_data(provider=provider_key)
    await state.update_data(transport=provider.get("transport", "vp8channel"), room_mode="manual")
    await state.set_state(AddDevice.room)
    await ask_room_id(callback.message, provider["carrier"])

    await callback.answer()


@dp.callback_query(F.data.startswith("addwbtransport:"))
async def add_wb_transport(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    transport = callback.data.split(":", 1)[1]
    if transport not in WB_TRANSPORTS:
        await callback.answer("Неизвестный transport", show_alert=True)
        return

    await state.update_data(transport=transport)
    await state.set_state(AddDevice.wb_room_mode)

    warning = WB_TRANSPORTS.get(transport, {}).get("warning", "")
    text = f"WB Stream\nTransport: {transport}\n\n"
    if warning:
        text += warning + "\n\n"
    text += "Как получить ID звонка?"

    await callback.message.answer(
        text,
        reply_markup=wb_room_mode_kb("addwbroom"),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("addwbroom:"))
async def add_wb_room_mode(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    room_mode = callback.data.split(":", 1)[1]
    if room_mode not in {"auto", "manual"}:
        await callback.answer("Неизвестный режим ID", show_alert=True)
        return

    await state.update_data(room_mode=room_mode)
    data = await state.get_data()

    if room_mode == "manual":
        await state.set_state(AddDevice.room)
        await ask_room_id(callback.message, "wbstream")
    else:
        await callback.message.answer(WB_AUTO_ID_WARNING)
        try:
            await create_device(
                callback.message,
                data["display_name"],
                data["provider"],
                data["transport"],
                data["room_mode"],
            )
            await state.clear()
            await send_main_menu(callback.message)
        except Exception as e:
            await state.clear()
            await callback.message.answer(f"Ошибка создания:\n\n<code>{str(e)}</code>", parse_mode="HTML")

    await callback.answer()


@dp.message(AddDevice.room)
async def add_room(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    room_id = extract_room_id(message.text, PROVIDERS[data["provider"]]["carrier"])

    if not room_id:
        await message.answer("Не нашёл ID. Отправьте ссылку или ID ещё раз.")
        return

    try:
        await create_device(
            message,
            data["display_name"],
            data["provider"],
            data["transport"],
            data["room_mode"],
            room_id,
        )
        await state.clear()
        await send_main_menu(message)
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


@dp.callback_query(F.data.startswith("editroom:"))
async def edit_room_start(callback: CallbackQuery, state: FSMContext) -> None:
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
    await state.update_data(edit_client_id=client_id)
    await state.set_state(EditRoom.room)
    await callback.message.answer(
        f"🔁 Смена Room ID для <code>{client_id}</code>\n\n"
        f"Текущий Room ID:\n<code>{row['room_id']}</code>\n\n"
        "Отправьте новый ID/ссылку комнаты.",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(EditRoom.room)
async def edit_room_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    client_id = data.get("edit_client_id")
    row = db_get(client_id)

    if not row:
        await state.clear()
        await message.answer("Клиент не найден.")
        return

    new_room_id = extract_room_id(message.text, row["carrier"])

    if not new_room_id:
        await message.answer("Не нашёл ID/ссылку. Отправьте ещё раз.")
        return

    updated = dict(row)
    updated["room_id"] = new_room_id
    updated["uri"] = make_uri(row["carrier"], row["transport"], new_room_id, row["auth_key"], row["client_id"])

    write_env(updated)
    db_update_room(row["client_id"], new_room_id, updated["uri"])

    try:
        stable_restart_service(row["client_id"])
        restart_note = "Сервис перезапущен."
    except Exception as e:
        restart_note = f"Не удалось перезапустить автоматически: {e}"

    await state.clear()
    await message.answer(
        f"Room ID обновлён для <code>{row['client_id']}</code>\n"
        f"Новый Room ID:\n<code>{new_room_id}</code>\n\n"
        f"{restart_note}",
        parse_mode="HTML",
    )
    await send_uri(message, row["client_id"], updated["uri"])


@dp.callback_query(F.data.startswith("svcstatus:"))
async def service_status(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    client_id = callback.data.split(":", 1)[1]
    try:
        status = get_service_status(client_id)
    except Exception as e:
        status = str(e)

    await callback.message.answer(
        f"Статус systemd {client_id}:\n\n<code>{status}</code>",
        parse_mode="HTML",
    )
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


@dp.callback_query(F.data.startswith("stable_restart:"))
async def stable_restart_client(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    client_id = callback.data.split(":", 1)[1]

    try:
        stable_restart_service(client_id)
        await callback.message.answer(
            f"Stable restart выполнен: {client_id}\n"
            "Если Telemost подвисал, подождите 10–20 секунд, затем в приложении клиента нажмите Stop → Start."
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка stable restart:\n\n<code>{str(e)}</code>", parse_mode="HTML")

    await callback.answer()


@dp.callback_query(F.data.startswith("stop:"))
async def stop_client(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    client_id = callback.data.split(":", 1)[1]
    stop_service(client_id)

    await callback.message.answer(f"Остановлен: {client_id}")
    await callback.answer()


@dp.callback_query(F.data.startswith("startsvc:"))
async def start_client(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    client_id = callback.data.split(":", 1)[1]

    try:
        start_service(client_id)
        await callback.message.answer(f"Запущен: {client_id}")
    except Exception as e:
        await callback.message.answer(f"Ошибка запуска:\n\n<code>{str(e)}</code>", parse_mode="HTML")

    await callback.answer()


@dp.callback_query(F.data.startswith("diag:"))
async def diagnostics(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    client_id = callback.data.split(":", 1)[1]
    active = is_active(client_id)
    env_safe = get_env_safe(client_id)
    logs = get_logs(client_id, lines=40)

    await callback.message.answer(
        f"Диагностика {client_id}\n\n"
        f"Статус: {'active' if active else 'inactive'}\n"
        f"Enabled: {'yes' if is_enabled(client_id) else 'no'}\n"
        f"Uptime: {service_uptime_text(client_id)}\n"
        f"Watchdog: {watchdog_status_text()}\n\n"
        f"ENV:\n<code>{env_safe}</code>\n\n"
        f"LOGS:\n<code>{logs}</code>",
        parse_mode="HTML",
    )
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

    await send_main_menu(callback.message)
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
