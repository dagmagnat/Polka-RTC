#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/polka-rtc-bot"
ENV_FILE="/etc/polka-rtc-bot.env"
DB_DIR="/var/lib/polka-rtc"
CLIENT_DIR="/etc/olcrtc/clients"
OLCRTC_SRC="/opt/olcrtc-src"
OLCRTC_BIN_DIR="/opt/olcrtc/bin"

if [[ "$(id -u)" != "0" ]]; then
  echo "Run as root: sudo bash install.sh"
  exit 1
fi

echo "=== Polka RTC installer ==="
echo

read -rp "Telegram BOT_TOKEN from @BotFather: " BOT_TOKEN
read -rp "Telegram ADMIN_IDS, comma-separated, e.g. 341361869: " ADMIN_IDS
read -rp "Optional BOT_PROXY, leave empty if not needed: " BOT_PROXY
read -rp "DNS for OlcRTC [1.1.1.1:53]: " DNS
DNS="${DNS:-1.1.1.1:53}"
read -rp "Install/update OlcRTC from source? [Y/n]: " BUILD_OLCRTC
BUILD_OLCRTC="${BUILD_OLCRTC:-Y}"

echo
echo "Installing OS packages..."
apt update
DEBIAN_FRONTEND=noninteractive apt install -y curl wget git build-essential nano python3 python3-pip python3-venv sqlite3 ufw openssl ca-certificates tar

echo
echo "Configuring firewall..."
ufw allow OpenSSH || true
ufw --force enable || true

if [[ "$BUILD_OLCRTC" =~ ^[Yy]$ ]]; then
  echo
  echo "Installing Go..."
  cd /tmp
  GO_VERSION="$(curl -fsSL https://go.dev/VERSION?m=text | head -n 1)"
  curl -fL "https://go.dev/dl/${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go-linux-amd64.tar.gz
  rm -rf /usr/local/go
  tar -C /usr/local -xzf /tmp/go-linux-amd64.tar.gz
  cat > /etc/profile.d/go.sh <<'EOF'
export PATH=$PATH:/usr/local/go/bin:/root/go/bin
EOF
  # shellcheck disable=SC1091
  source /etc/profile.d/go.sh

  echo
  echo "Building OlcRTC..."
  rm -rf "$OLCRTC_SRC"
  git clone https://github.com/openlibrecommunity/olcrtc --recurse-submodules "$OLCRTC_SRC"
  cd "$OLCRTC_SRC"
  go install github.com/magefile/mage@latest
  /root/go/bin/mage buildCLI

  mkdir -p "$OLCRTC_BIN_DIR"
  if [[ -f "$OLCRTC_SRC/build/olcrtc-linux-amd64" ]]; then
    install -m 755 "$OLCRTC_SRC/build/olcrtc-linux-amd64" "$OLCRTC_BIN_DIR/olcrtc"
  else
    echo "Could not find build/olcrtc-linux-amd64"
    find "$OLCRTC_SRC" -type f -name '*olcrtc*' -o -name '*linux*'
    exit 1
  fi
fi

if [[ ! -x "$OLCRTC_BIN_DIR/olcrtc" ]]; then
  echo "OlcRTC binary not found: $OLCRTC_BIN_DIR/olcrtc"
  exit 1
fi

echo
echo "Creating directories..."
mkdir -p "$APP_DIR" "$DB_DIR" "$CLIENT_DIR" "$OLCRTC_BIN_DIR" /var/backups/polka-rtc

echo
echo "Installing Polka RTC bot files..."
cp -f ./bot.py "$APP_DIR/bot.py"
cp -f ./requirements.txt "$APP_DIR/requirements.txt"
cp -f ./polka-olcrtc-run /usr/local/bin/polka-olcrtc-run
cp -f ./polka-rtc-backup /usr/local/bin/polka-rtc-backup
chmod +x /usr/local/bin/polka-olcrtc-run /usr/local/bin/polka-rtc-backup

echo
echo "Creating Python venv..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo
echo "Writing env file..."
cat > "$ENV_FILE" <<EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
BOT_PROXY=${BOT_PROXY}

OLCRTC_BIN=${OLCRTC_BIN_DIR}/olcrtc
DB_PATH=${DB_DIR}/polka.db
DNS=${DNS}

VP8_FPS=60
VP8_BATCH=64

BACKUP_DIR=/var/backups/polka-rtc
EOF
chmod 600 "$ENV_FILE"

echo
echo "Writing systemd templates..."
cat > /etc/systemd/system/olcrtc-client@.service <<'EOF'
[Unit]
Description=OlcRTC server instance for %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/olcrtc/clients/%i.env
ExecStart=/usr/local/bin/polka-olcrtc-run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/polka-rtc-bot.service <<'EOF'
[Unit]
Description=Polka RTC Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/polka-rtc-bot
EnvironmentFile=/etc/polka-rtc-bot.env
ExecStart=/opt/polka-rtc-bot/.venv/bin/python /opt/polka-rtc-bot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo
echo "Testing bot code syntax..."
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
"$APP_DIR/.venv/bin/python" -m py_compile "$APP_DIR/bot.py"

echo
echo "Starting bot..."
systemctl enable --now polka-rtc-bot

echo
echo "=== Installed ==="
echo "Bot service: systemctl status polka-rtc-bot --no-pager"
echo "Bot logs:    journalctl -fu polka-rtc-bot"
echo "Backup CLI:  polka-rtc-backup"
echo
echo "Open your Telegram bot and send /start"
