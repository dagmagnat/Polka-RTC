# Migration notes

Эта сборка возвращает идею к оригинальному upstream olcrtc:

- не используется patched OlcBox;
- не используется авто-восстановление каждые 5 минут;
- не используется плановый рестарт активных Telemost-сессий;
- по умолчанию собирается `openlibrecommunity/olcrtc` branch `refactor/universal-carrier`;
- серверные сервисы запускаются через YAML (`OLCRTC_GENERATION=refactor`).

Если на сервере уже стоит старая сборка, обновление:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/dagmagnat/polka-rtc/main/install.sh) --update
```

Для пересборки самого olcrtc:

```bash
cd /root/polka-rtc
bash install.sh
```

и выберите полную установку/переконфигурацию.
