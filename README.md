# Polka RTC

Polka RTC — это Telegram-бот для управления отдельными клиентскими подключениями OlcRTC на VPS.

Репозиторий: `https://github.com/dagmagnat/polka-rtc`

## Что умеет бот

- создавать клиента;
- выдавать отдельную ссылку `olcrtc://...`;
- выдавать QR-код;
- создавать отдельный systemd-сервис на каждого клиента/устройство;
- выбирать провайдера:
  - `WB Stream`;
  - `Яндекс Телемост`;
- для `WB Stream` выбирать transport:
  - `datachannel — максимальная скорость`;
  - `vp8channel — высокая скорость`;
- для `WB Stream` выбирать получение ID:
  - автоматическая генерация;
  - ручной ввод;
- для `Яндекс Телемост` использовать ручной ввод ID/ссылки;
- добавлять клиенту дополнительные устройства;
- показывать список клиентов;
- показывать ссылку и QR повторно;
- запускать, останавливать и перезапускать устройство;
- показывать логи и диагностику;
- удалять устройство клиента;
- создавать бэкап и отправлять его в Telegram;
- показывать постоянные кнопки внизу чата.

## Быстрая установка на новый VPS

```bash
apt update && apt install -y git curl && rm -rf /root/polka-rtc && git clone https://github.com/dagmagnat/polka-rtc.git /root/polka-rtc && cd /root/polka-rtc && bash install.sh
```

## Обновление уже установленного бота

```bash
cd /root
rm -rf /root/polka-rtc
git clone https://github.com/dagmagnat/polka-rtc.git /root/polka-rtc
cd /root/polka-rtc
bash install.sh
```

Если установщик увидит существующий `/etc/polka-rtc-bot.env`, он предложит:

```text
1) Update bot files only
2) Full install / reconfigure
```

Для обычного обновления выбирайте:

```text
1
```

## Что спрашивает установщик при полной установке

```text
Telegram BOT_TOKEN from @BotFather:
Telegram ADMIN_IDS, comma-separated, e.g. 341361869:
Optional BOT_PROXY, leave empty if not needed:
DNS for OlcRTC [1.1.1.1:53]:
Install/update OlcRTC from source? [Y/n]:
```

## BOT_TOKEN

Токен берётся у `@BotFather`.

Если бот уже создан:

```text
@BotFather
/mybots
→ выбрать бота
→ API Token
```

Токен нельзя публиковать. Если токен попал в чужие руки, перевыпустите его через `@BotFather`.

## ADMIN_IDS

Один администратор:

```text
341361869
```

Несколько администраторов:

```text
341361869,123456789
```

Узнать свой Telegram ID можно через `@userinfobot` или `@RawDataBot`.

## BOT_PROXY

Обычно оставляется пустым.

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

## Проверка после установки

```bash
systemctl status polka-rtc-bot --no-pager
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

Постоянные кнопки снизу:

```text
➕ Создать клиента
📋 Список клиентов
💾 Создать бэкап
ℹ️ Помощь
```

Команды:

```text
/start
/create
/clients
/backup
/help
/cancel
```

## Создание WB Stream

Сценарий:

```text
➕ Создать клиента
→ WB Stream
→ datachannel или vp8channel
→ сгенерировать ID автоматически или ввести ID вручную
→ имя клиента
```

Если выбран ручной ID, вставьте ID WB Stream, например:

```text
019e20e6-9f02-77db-a198-2e97a3278d89
```

## Создание Яндекс Телемост

Сценарий:

```text
➕ Создать клиента
→ Яндекс Телемост
→ имя клиента
→ вставить ссылку или ID встречи
```

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

### Через nano

```bash
nano /etc/polka-rtc-bot.env
```

Замените:

```bash
BOT_TOKEN=старый_токен
```

на:

```bash
BOT_TOKEN=новый_токен
```

Перезапустите:

```bash
systemctl restart polka-rtc-bot
systemctl status polka-rtc-bot --no-pager
```

Проверка токена:

```bash
set -a
source /etc/polka-rtc-bot.env
set +a

curl -4 -m 20 "https://api.telegram.org/bot${BOT_TOKEN}/getMe"
```

### Одной командой

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

### Заменить ADMIN_IDS

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

### Добавить администратора, не удаляя старых

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

```bash
tar -xzf polka-rtc-backup-YYYY-MM-DD_HH-MM-SS.tar.gz -C /
systemctl daemon-reload
systemctl restart polka-rtc-bot
```

## Полезные команды

```bash
systemctl status polka-rtc-bot --no-pager
journalctl -fu polka-rtc-bot
systemctl restart polka-rtc-bot
systemctl list-units 'olcrtc-client@*' --no-pager
journalctl -u olcrtc-client@CLIENT_ID.service -n 100 --no-pager
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
