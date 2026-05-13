# Polka RTC

Polka RTC — это Telegram-бот для управления отдельными клиентскими подключениями OlcRTC на VPS.

Репозиторий: `https://github.com/dagmagnat/polka-rtc`

## Что умеет бот

- создавать клиента;
- выдавать отдельную ссылку `olcrtc://...`;
- выдавать QR-код;
- создавать отдельный systemd-сервис на каждого клиента/устройство;
- выбирать режим подключения:
  - `WB Stream — авто ID`;
  - `WB Stream — ручной ID`;
  - `Яндекс Телемост`;
- добавлять клиенту дополнительные устройства;
- показывать список клиентов;
- показывать ссылку и QR повторно;
- перезапускать клиента;
- удалять устройство клиента;
- показывать логи устройства;
- создавать бэкап и отправлять его в Telegram;
- показывать постоянные кнопки внизу чата:
  - `➕ Создать клиента`;
  - `📋 Список клиентов`;
  - `💾 Создать бэкап`;
  - `ℹ️ Помощь`.

## Быстрая установка на новый VPS

```bash
apt update && apt install -y git curl && rm -rf /root/polka-rtc && git clone https://github.com/dagmagnat/polka-rtc.git /root/polka-rtc && cd /root/polka-rtc && bash install.sh
```

Установщик спросит:

```text
Telegram BOT_TOKEN from @BotFather:
Telegram ADMIN_IDS, comma-separated, e.g. 341361869:
Optional BOT_PROXY, leave empty if not needed:
DNS for OlcRTC [1.1.1.1:53]:
Install/update OlcRTC from source? [Y/n]:
```

## Что вводить при установке

### BOT_TOKEN

Токен берётся у `@BotFather`.

Если бот ещё не создан:

```text
@BotFather
/newbot
```

Если бот уже создан:

```text
@BotFather
/mybots
→ выбрать бота
→ API Token
```

Пример токена:

```text
1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Токен нельзя публиковать. Если токен попал в чужие руки, перевыпустите его через `@BotFather`.

### ADMIN_IDS

Это Telegram ID администратора, которому разрешено управлять ботом.

Один администратор:

```text
341361869
```

Несколько администраторов:

```text
341361869,123456789
```

Узнать свой Telegram ID можно через `@userinfobot` или `@RawDataBot`.

### BOT_PROXY

Обычно оставляется пустым. Просто нажмите Enter.

Прокси нужен только если VPS не открывает Telegram API.

Проверка Telegram API:

```bash
curl -4 -m 15 https://api.telegram.org -I
```

Если команда даёт `timeout`, можно указать прокси:

```text
socks5://user:password@1.2.3.4:1080
```

или:

```text
http://user:password@1.2.3.4:8080
```

### DNS

Можно нажать Enter. По умолчанию:

```text
1.1.1.1:53
```

### Install/update OlcRTC from source?

Если на сервере ещё нет OlcRTC:

```text
Y
```

Если OlcRTC уже установлен и работает:

```text
n
```

## Проверка после установки

Статус бота:

```bash
systemctl status polka-rtc-bot --no-pager
```

Логи бота:

```bash
journalctl -fu polka-rtc-bot
```

Проверка OlcRTC:

```bash
/opt/olcrtc/bin/olcrtc -h | head
```

Проверка генерации WB Stream ID:

```bash
/opt/olcrtc/bin/olcrtc -mode gen -carrier wbstream -dns 1.1.1.1:53 -amount 1 -data data
```

Список клиентских сервисов:

```bash
systemctl list-units 'olcrtc-client@*' --no-pager
```

## Как пользоваться ботом

Откройте своего Telegram-бота и отправьте:

```text
/start
```

Бот покажет постоянные кнопки снизу:

```text
➕ Создать клиента
📋 Список клиентов
💾 Создать бэкап
ℹ️ Помощь
```

Дополнительно доступны команды:

```text
/start
/create
/clients
/backup
/help
/cancel
```

## Режимы создания

### WB Stream — авто ID

Бот сам запускает:

```bash
olcrtc -mode gen -carrier wbstream
```

и получает Room ID автоматически.

Используется:

```text
carrier = wbstream
transport = datachannel
```

### WB Stream — ручной ID

Вы сами вводите ID WB Stream.

Этот режим нужен, если автоматическая генерация WB Stream ID создаёт ID, но подключение не работает.

Пример ID:

```text
019e20e6-9f02-77db-a198-2e97a3278d89
```

### Яндекс Телемост

Вы заранее создаёте встречу Яндекс Телемост и вставляете в бота ссылку или ID.

Пример:

```text
https://telemost.yandex.ru/j/220722504595729
```

Используется:

```text
carrier = telemost
transport = vp8channel
```

## Логика клиентов и устройств

По умолчанию создание клиента создаёт:

```text
1 клиент = 1 устройство = 1 ссылка = 1 QR
```

Если клиенту нужно второе устройство:

```text
📋 Список клиентов
→ выбрать клиента
→ ➕ Добавить устройство
```

Для каждого устройства создаётся отдельная ссылка.

## Где хранятся файлы

Бот:

```text
/opt/polka-rtc-bot/
```

Настройки бота:

```text
/etc/polka-rtc-bot.env
```

База клиентов:

```text
/var/lib/polka-rtc/polka.db
```

Конфиги клиентов:

```text
/etc/olcrtc/clients/
```

Бэкапы:

```text
/var/backups/polka-rtc/
```

Бинарник OlcRTC:

```text
/opt/olcrtc/bin/olcrtc
```

## Как заменить Telegram API token бота

### Способ 1 — через nano

```bash
nano /etc/polka-rtc-bot.env
```

Найдите строку:

```bash
BOT_TOKEN=старый_токен
```

Замените на:

```bash
BOT_TOKEN=новый_токен
```

Сохраните файл:

```text
Ctrl + O
Enter
Ctrl + X
```

Перезапустите бота:

```bash
systemctl restart polka-rtc-bot
systemctl status polka-rtc-bot --no-pager
```

Проверить токен:

```bash
set -a
source /etc/polka-rtc-bot.env
set +a

curl -4 -m 20 "https://api.telegram.org/bot${BOT_TOKEN}/getMe"
```

### Способ 2 — одной командой

```bash
read -rp "Введите новый BOT_TOKEN: " NEW_TOKEN
python3 - <<PY
from pathlib import Path

env = Path("/etc/polka-rtc-bot.env")
text = env.read_text()
new_token = """$NEW_TOKEN""".strip()

lines = []
found = False

for line in text.splitlines():
    if line.startswith("BOT_TOKEN="):
        lines.append(f"BOT_TOKEN={new_token}")
        found = True
    else:
        lines.append(line)

if not found:
    lines.insert(0, f"BOT_TOKEN={new_token}")

env.write_text("\\n".join(lines) + "\\n")
PY

chmod 600 /etc/polka-rtc-bot.env
systemctl restart polka-rtc-bot
systemctl status polka-rtc-bot --no-pager
```

## Как заменить или добавить администратора

### Способ 1 — через nano

```bash
nano /etc/polka-rtc-bot.env
```

Найдите строку:

```bash
ADMIN_IDS=старый_id
```

Один администратор:

```bash
ADMIN_IDS=341361869
```

Несколько администраторов:

```bash
ADMIN_IDS=341361869,123456789
```

Сохраните и перезапустите:

```bash
systemctl restart polka-rtc-bot
systemctl status polka-rtc-bot --no-pager
```

### Способ 2 — заменить ADMIN_IDS одной командой

```bash
read -rp "Введите новый ADMIN_IDS: " NEW_ADMIN_IDS
python3 - <<PY
from pathlib import Path

env = Path("/etc/polka-rtc-bot.env")
text = env.read_text()
new_admin_ids = """$NEW_ADMIN_IDS""".strip()

lines = []
found = False

for line in text.splitlines():
    if line.startswith("ADMIN_IDS="):
        lines.append(f"ADMIN_IDS={new_admin_ids}")
        found = True
    else:
        lines.append(line)

if not found:
    lines.insert(1, f"ADMIN_IDS={new_admin_ids}")

env.write_text("\\n".join(lines) + "\\n")
PY

chmod 600 /etc/polka-rtc-bot.env
systemctl restart polka-rtc-bot
systemctl status polka-rtc-bot --no-pager
```

### Способ 3 — добавить администратора, не удаляя старых

```bash
read -rp "Введите Telegram ID нового администратора: " NEW_ADMIN_ID
python3 - <<PY
from pathlib import Path

env = Path("/etc/polka-rtc-bot.env")
text = env.read_text()
new_id = """$NEW_ADMIN_ID""".strip()

lines = []
found = False

for line in text.splitlines():
    if line.startswith("ADMIN_IDS="):
        current = line.split("=", 1)[1].strip()
        ids = [x.strip() for x in current.split(",") if x.strip()]
        if new_id not in ids:
            ids.append(new_id)
        lines.append("ADMIN_IDS=" + ",".join(ids))
        found = True
    else:
        lines.append(line)

if not found:
    lines.insert(1, f"ADMIN_IDS={new_id}")

env.write_text("\\n".join(lines) + "\\n")
PY

chmod 600 /etc/polka-rtc-bot.env
systemctl restart polka-rtc-bot
systemctl status polka-rtc-bot --no-pager
```

## Бэкап

Создать бэкап через Telegram:

```text
💾 Создать бэкап
```

Создать бэкап через консоль:

```bash
polka-rtc-backup
```

Посмотреть бэкапы:

```bash
ls -lah /var/backups/polka-rtc/
```

## Восстановление из бэкапа

Скопируйте архив бэкапа на новый сервер и выполните:

```bash
tar -xzf polka-rtc-backup-YYYY-MM-DD_HH-MM-SS.tar.gz -C /
systemctl daemon-reload
systemctl restart polka-rtc-bot
```

Проверка:

```bash
systemctl status polka-rtc-bot --no-pager
systemctl list-units 'olcrtc-client@*' --no-pager
```

## Обновление проекта на сервере

```bash
cd /root
rm -rf /root/polka-rtc
git clone https://github.com/dagmagnat/polka-rtc.git /root/polka-rtc
cd /root/polka-rtc
bash install.sh
```

Если OlcRTC уже установлен, на вопрос:

```text
Install/update OlcRTC from source? [Y/n]:
```

можно ответить:

```text
n
```

## Полезные команды

Статус бота:

```bash
systemctl status polka-rtc-bot --no-pager
```

Логи бота:

```bash
journalctl -fu polka-rtc-bot
```

Перезапуск бота:

```bash
systemctl restart polka-rtc-bot
```

Список клиентов:

```bash
systemctl list-units 'olcrtc-client@*' --no-pager
```

Логи конкретного клиента:

```bash
journalctl -u olcrtc-client@CLIENT_ID.service -n 100 --no-pager
```

Остановить конкретного клиента:

```bash
systemctl stop olcrtc-client@CLIENT_ID.service
```

## Важно про безопасность

Не публикуйте:

```text
BOT_TOKEN
/etc/polka-rtc-bot.env
бэкапы
auth_key клиентов
olcrtc:// ссылки клиентов
```

Если Telegram BOT_TOKEN был случайно опубликован:

```text
@BotFather
→ /mybots
→ выбрать бота
→ API Token
→ Revoke current token
```

После этого вставьте новый токен в:

```text
/etc/polka-rtc-bot.env
```

и перезапустите бота.
