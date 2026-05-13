# Polka RTC

Telegram bot + one-command installer for managing per-client OlcRTC instances.

## Install

```bash
apt update && apt install -y curl git
bash <(curl -fsSL https://raw.githubusercontent.com/dagmagnat/polka-rtc/main/install.sh)
```

Installer asks for:

- Telegram bot token
- Telegram admin ID
- optional proxy
- DNS
- whether to build OlcRTC

## Bot features

- WB Stream is first in provider list
- WB Stream has two modes:
  - automatic Room ID via `olcrtc -mode gen`
  - manual Room ID input
- Telemost is optional provider
- one new client = one device/link/QR
- add more devices later from client card
- list devices
- show link/QR
- restart/delete device
- create backup and send it to Telegram

## CLI backup

```bash
polka-rtc-backup
ls -lah /var/backups/polka-rtc/
```

## Services

```bash
systemctl status polka-rtc-bot --no-pager
journalctl -fu polka-rtc-bot
systemctl list-units 'olcrtc-client@*' --no-pager
```

## Restore idea

Copy backup to server, unpack selected files:

```bash
tar -xzf polka-rtc-backup-YYYY-MM-DD_HH-MM-SS.tar.gz -C /
systemctl daemon-reload
systemctl restart polka-rtc-bot
```
