# Polka RTC Bot — original olcrtc manager

Версия сборки: `original-olcrtc-refactor-bot-2026-05-18-1`

Эта сборка **не патчит OlcBox/Android-клиент** и не меняет исходники olcrtc. Бот только:

- собирает оригинальный `openlibrecommunity/olcrtc`;
- создаёт YAML/env для каждого клиента;
- запускает отдельный `systemd`-сервис на клиента;
- выдаёт ссылку/QR для OlcBox;
- даёт управление через Telegram.

По умолчанию установщик собирает официальный upstream:

```text
https://github.com/openlibrecommunity/olcrtc.git
branch: refactor/universal-carrier
```

## Режимы

### Jitsi + datachannel

Основной рекомендуемый режим по официальной матрице `olcrtc`.

В боте: `Создать клиента` → `Jitsi Meet — datachannel`.

Для Room ID лучше вставлять полную ссылку комнаты, например:

```text
https://meet.cryptopro.ru/polka-room-001
```

### Telemost + vp8channel

Запасной режим. Работает, но тяжёлый поток может перегружать канал.

В боте: `Создать клиента` → `Яндекс Телемост — vp8channel`.

### WB Stream

Оставлен как информационный пункт. Создание WB-клиентов выключено по умолчанию, потому что в твоих тестах WB возвращал `502 Bad Gateway`.

## Быстрая установка

```bash
apt update && apt install -y git curl ca-certificates
bash <(curl -fsSL https://raw.githubusercontent.com/dagmagnat/polka-rtc/main/install.sh)
```

## Обновление установленного бота

```bash
apt update && apt install -y git curl ca-certificates
bash <(curl -fsSL https://raw.githubusercontent.com/dagmagnat/polka-rtc/main/install.sh) --update
```

Важно: `--update` обновляет бота и systemd-файлы. Если нужно заново собрать оригинальный `olcrtc`, запустите установщик без `--update` и выберите полную установку/переконфигурацию.

## Сборка другой ветки olcrtc

Можно указать переменные:

```bash
OLCRTC_BRANCH=refactor/universal-carrier \
OLCRTC_REPO_URL=https://github.com/openlibrecommunity/olcrtc.git \
bash <(curl -fsSL https://raw.githubusercontent.com/dagmagnat/polka-rtc/main/install.sh)
```

## Возможности бота

В карточке клиента доступны:

```text
🔗 Ссылка
📷 QR
➕ Добавить устройство
🔁 Сменить Room ID
🔄 Перезапустить
♻️ Reset failed + restart
▶️ Запустить / ⏹ Остановить
🧪 Диагностика
📜 Логи
🔎 Статус systemd
🗑 Удалить устройство
```

## Проверка версии

```bash
grep -E 'APP_VERSION|original-olcrtc' /opt/polka-rtc-bot/bot.py
systemctl status polka-rtc-bot --no-pager
journalctl -u polka-rtc-bot -n 100 --no-pager
```

В дашборде бота должна быть версия:

```text
original-olcrtc-refactor-bot-2026-05-18-1
```

## Замена токена бота и админов

```bash
nano /etc/polka-rtc-bot.env
```

Измените:

```env
BOT_TOKEN=токен_бота
ADMIN_IDS=123456789,987654321
```

Применить:

```bash
systemctl restart polka-rtc-bot
```

## Бэкап

Через бота: `💾 Создать бэкап`.

Через сервер:

```bash
polka-rtc-backup
```

Архивы лежат в:

```text
/var/backups/polka-rtc
```

## Важные замечания

- Одна ссылка рассчитана на одно устройство/подключение.
- Бот не делает авто-рестарт активных сессий по времени.
- Watchdog перезапускает только `failed/inactive + enabled`.
- Если клиент остановлен кнопкой `Остановить`, watchdog его не поднимет.
- Для тяжёлого трафика сначала тестируйте `Jitsi + datachannel`; Telemost лучше использовать как запасной вариант.

## Исправление установщика

В этой версии исправлена ошибка установщика:

```text
cp: cannot stat './bot.py': No such file or directory
```

Причина была в том, что во время сборки оригинального `olcrtc` скрипт переходил в `/opt/olcrtc-src`, а потом пытался копировать `./bot.py` из текущей папки. Теперь установщик сохраняет путь к папке проекта в `PROJECT_DIR` и копирует файлы оттуда.
