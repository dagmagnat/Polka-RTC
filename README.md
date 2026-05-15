# Polka RTC

Telegram-бот для управления отдельными подключениями OlcRTC на VPS.

Репозиторий: `https://github.com/dagmagnat/polka-rtc`

## Главное правило

**1 ссылка = 1 устройство / 1 подключение.**

Не давайте одну ссылку двум людям. Если одному клиенту нужно 2–3 устройства, создайте для него 2–3 отдельные ссылки через бота. Это надёжнее, чем пытаться использовать одну ссылку на всех.

## Что умеет бот

- создавать отдельную ссылку `olcrtc://...`;
- выдавать QR-код;
- создавать отдельный systemd-сервис на каждое устройство;
- показывать список клиентов;
- повторно показывать ссылку и QR;
- перезапускать, запускать и останавливать устройство;
- показывать логи и диагностику;
- удалять устройство;
- делать бэкап и отправлять его в Telegram.

## Актуальные режимы

### Яндекс Телемост

Основной стабильный режим:

```text
telemost + vp8channel + ручной ID встречи
```

Вы заранее создаёте встречу Яндекс Телемост и вставляете ссылку или ID в бота.

Пример:

```text
https://telemost.yandex.ru/j/220722504595729
```

### WB Stream

WB Stream оставлен в боте, но сейчас он нестабилен.

Рекомендуемый вариант для тестов:

```text
wbstream + vp8channel + ручной ID
```

`WB Stream авто-ID` оставлен только на случай, если WB вернёт авто-создание комнат. Сейчас авто-создание может не работать.

`WB Stream + datachannel` оставлен как экспериментальный режим. Он может не работать без прав `canPublishData`.

## Быстрая установка

```bash
apt update && apt install -y git curl && rm -rf /root/polka-rtc && git clone https://github.com/dagmagnat/polka-rtc.git /root/polka-rtc && cd /root/polka-rtc && bash install.sh
```

## Обновление установленного бота

```bash
cd /root
rm -rf /root/polka-rtc
git clone https://github.com/dagmagnat/polka-rtc.git /root/polka-rtc
cd /root/polka-rtc
bash install.sh
```

Если установщик увидит `/etc/polka-rtc-bot.env`, выберите:

```text
1) Update bot files only
```

или просто нажмите Enter.

## Что спрашивает установщик

```text
Telegram BOT_TOKEN from @BotFather:
Telegram ADMIN_IDS, comma-separated, e.g. 341361869:
Optional BOT_PROXY, leave empty if not needed:
DNS for OlcRTC [1.1.1.1:53]:
Install/update OlcRTC from source? [Y/n]:
```

## BOT_TOKEN

Токен берётся у `@BotFather`.

```text
@BotFather
/mybots
→ выбрать бота
→ API Token
```

## ADMIN_IDS

Один администратор:

```text
341361869
```

Несколько администраторов:

```text
341361869,123456789
```

Узнать Telegram ID можно через `@userinfobot` или `@RawDataBot`.

## Проверка

```bash
systemctl status polka-rtc-bot --no-pager
journalctl -fu polka-rtc-bot
```

Проверка OlcRTC:

```bash
/opt/olcrtc/bin/olcrtc -h | head
```

Проверка сервисов клиентов:

```bash
systemctl list-units 'olcrtc-client@*' --no-pager
```

## Использование

Откройте Telegram-бота и отправьте:

```text
/start
```

Меню:

```text
➕ Создать клиента
📋 Список клиентов
💾 Создать бэкап
ℹ️ Помощь
```

### Создание Telemost-ссылки

```text
➕ Создать клиента
→ Яндекс Телемост
→ имя клиента
→ вставить ID/ссылку встречи
```

### Создание WB Stream-ссылки

```text
➕ Создать клиента
→ WB Stream
→ vp8channel — рекомендуется
→ Ввести ID вручную — рекомендуется
→ имя клиента
→ вставить ID комнаты WB Stream
```

## Несколько устройств у одного клиента

Нажмите:

```text
📋 Список клиентов
→ выбрать клиента
→ ➕ Добавить устройство
```

Каждое устройство получит отдельную ссылку.

## Файлы

Бот:

```text
/opt/polka-rtc-bot/
```

Настройки:

```text
/etc/polka-rtc-bot.env
```

База:

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

## Новый режим olcrtc refactor/universal-carrier

По умолчанию бот работает в старом режиме:

```text
OLCRTC_GENERATION=legacy
OLCRTC_URI_FORMAT=legacy
```

В новой ветке `refactor/universal-carrier` старые CLI-флаги заменены YAML-конфигом. Бот уже создаёт YAML-файл для каждого клиента, но включать новый режим нужно только если вы точно установили новый бинарник:

```bash
nano /etc/polka-rtc-bot.env
```

```text
OLCRTC_GENERATION=refactor
OLCRTC_URI_FORMAT=refactor
```

Потом:

```bash
systemctl restart polka-rtc-bot
systemctl restart 'olcrtc-client@*'
```

Если не уверены — оставьте `legacy`.

## Замена BOT_TOKEN

```bash
nano /etc/polka-rtc-bot.env
```

Замените:

```text
BOT_TOKEN=старый_токен
```

на:

```text
BOT_TOKEN=новый_токен
```

Перезапуск:

```bash
systemctl restart polka-rtc-bot
systemctl status polka-rtc-bot --no-pager
```

## Замена или добавление администратора

```bash
nano /etc/polka-rtc-bot.env
```

Один администратор:

```text
ADMIN_IDS=341361869
```

Несколько:

```text
ADMIN_IDS=341361869,123456789
```

Перезапуск:

```bash
systemctl restart polka-rtc-bot
```

## Бэкап

Через Telegram:

```text
💾 Создать бэкап
```

Через консоль:

```bash
polka-rtc-backup
```

Посмотреть бэкапы:

```bash
ls -lah /var/backups/polka-rtc/
```

## Важно

Не публикуйте:

```text
BOT_TOKEN
/etc/polka-rtc-bot.env
бэкапы
auth_key клиентов
olcrtc:// ссылки клиентов
```

Если ссылка попала не тому человеку, создайте новую ссылку и удалите старое устройство.


## Telemost Stable Mode

В этой сборке добавлен режим повышения стабильности для Яндекс Телемоста.

Что делает режим:

```text
1. systemd перезапускает упавшие olcrtc-клиенты без лимита попыток.
2. watchdog каждые 3 минуты проверяет клиентские сервисы.
3. Если Telemost-сервис упал или ушёл в failed/inactive — watchdog перезапускает его.
4. Если Telemost-сессия работает слишком долго, watchdog делает stable restart.
5. В карточке клиента есть кнопка ♻️ Stable restart.
```

Настройки находятся в `/etc/polka-rtc-bot.env`:

```bash
TELEMOST_STABLE_MODE=1
TELEMOST_AUTO_RESTART_MINUTES=180
TELEMOST_LOG_STALL_MINUTES=0
```

`TELEMOST_AUTO_RESTART_MINUTES=180` означает плановый restart Telemost-процесса примерно раз в 3 часа. Если не хотите плановый restart, поставьте:

```bash
TELEMOST_AUTO_RESTART_MINUTES=0
```

После изменения:

```bash
systemctl restart polka-rtc-bot
systemctl restart polka-rtc-watchdog.timer
```

Проверка watchdog:

```bash
systemctl status polka-rtc-watchdog.timer --no-pager
journalctl -u polka-rtc-watchdog.service -n 100 --no-pager
tail -n 100 /var/log/polka-rtc-watchdog.log
```

Важно: одна ссылка всё равно рассчитана на одно устройство/одно подключение. Для второго устройства создавайте отдельную ссылку.

