#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${POLKA_RTC_REPO_URL:-https://github.com/dagmagnat/polka-rtc.git}"

# Official olcrtc source. No client patches are applied by this installer.
OLCRTC_REPO_URL="${OLCRTC_REPO_URL:-https://github.com/openlibrecommunity/olcrtc.git}"
OLCRTC_BRANCH="${OLCRTC_BRANCH:-refactor/universal-carrier}"

if [[ ! -f "./bot.py" || ! -f "./requirements.txt" || ! -f "./polka-olcrtc-run" || ! -f "./polka-rtc-backup" || ! -f "./polka-rtc-watchdog" ]]; then
  echo "Full project files not found near install.sh."
  echo "Cloning full Polka RTC project from: ${REPO_URL}"

  apt update
  apt install -y git curl ca-certificates

  TMP_DIR="/tmp/polka-rtc-install-$$"
  rm -rf "$TMP_DIR"
  git clone "$REPO_URL" "$TMP_DIR"

  cd "$TMP_DIR"
  exec bash ./install.sh "$@"
fi

# Keep the Polka RTC project directory fixed, because the installer later cd-s into /tmp and /opt/olcrtc-src.
PROJECT_DIR="$(pwd)"

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

FORCE_UPDATE=0
if [[ "${1:-}" == "--update" || "${1:-}" == "update" ]]; then
  FORCE_UPDATE=1
fi

if [[ -f "$ENV_FILE" ]]; then
  echo "Existing installation detected: $ENV_FILE"
  if [[ "${FORCE_UPDATE:-0}" == "1" ]]; then
    INSTALL_MODE="1"
    echo "Forced update mode selected."
  else
    echo "1) Update bot files only"
    echo "2) Full install / reconfigure"
    read -rp "Choose mode [1/2, default 1]: " INSTALL_MODE
    INSTALL_MODE="${INSTALL_MODE:-1}"
  fi
else
  INSTALL_MODE="2"
fi

install_bot_files() {
  echo
  echo "Creating directories..."
  mkdir -p "$APP_DIR" "$DB_DIR" "$CLIENT_DIR" "$OLCRTC_BIN_DIR" /var/backups/polka-rtc

  echo
  echo "Installing Polka RTC bot files..."
  cp -f "$PROJECT_DIR/bot.py" "$APP_DIR/bot.py"
  cp -f "$PROJECT_DIR/requirements.txt" "$APP_DIR/requirements.txt"
  cp -f "$PROJECT_DIR/polka-olcrtc-run" /usr/local/bin/polka-olcrtc-run
  cp -f "$PROJECT_DIR/polka-rtc-backup" /usr/local/bin/polka-rtc-backup
  cp -f "$PROJECT_DIR/polka-rtc-watchdog" /usr/local/bin/polka-rtc-watchdog
  chmod +x /usr/local/bin/polka-olcrtc-run /usr/local/bin/polka-rtc-backup /usr/local/bin/polka-rtc-watchdog

  echo
  echo "Creating/updating Python venv..."
  python3 -m venv "$APP_DIR/.venv"
  "$APP_DIR/.venv/bin/pip" install --upgrade pip
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

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
RestartSec=3
StartLimitIntervalSec=0
StartLimitBurst=0
KillSignal=SIGTERM
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

  cat > /etc/systemd/system/polka-rtc-watchdog.service <<'EOF'
[Unit]
Description=Polka RTC Telemost stability watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-/etc/polka-rtc-bot.env
ExecStart=/usr/local/bin/polka-rtc-watchdog
EOF

  cat > /etc/systemd/system/polka-rtc-watchdog.timer <<'EOF'
[Unit]
Description=Run Polka RTC watchdog every 3 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=3min
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
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
}


disable_telemost_periodic_restart() {
  # Safety migration: do not restart active Telemost calls by timer.
  if [ -f "$ENV_FILE" ]; then
    if grep -q '^TELEMOST_AUTO_RESTART_MINUTES=' "$ENV_FILE"; then
      sed -i 's/^TELEMOST_AUTO_RESTART_MINUTES=.*/TELEMOST_AUTO_RESTART_MINUTES=0/' "$ENV_FILE"
    else
      echo 'TELEMOST_AUTO_RESTART_MINUTES=0' >> "$ENV_FILE"
    fi

    if grep -q '^TELEMOST_LOG_STALL_MINUTES=' "$ENV_FILE"; then
      sed -i 's/^TELEMOST_LOG_STALL_MINUTES=.*/TELEMOST_LOG_STALL_MINUTES=0/' "$ENV_FILE"
    else
      echo 'TELEMOST_LOG_STALL_MINUTES=0' >> "$ENV_FILE"
    fi
  fi

  if [ -d /etc/olcrtc/clients ]; then
    for f in /etc/olcrtc/clients/*.env; do
      [ -f "$f" ] || continue
      grep -q '^CARRIER=telemost' "$f" || continue

      if grep -q '^TELEMOST_AUTO_RESTART_MINUTES=' "$f"; then
        sed -i 's/^TELEMOST_AUTO_RESTART_MINUTES=.*/TELEMOST_AUTO_RESTART_MINUTES=0/' "$f"
      else
        echo 'TELEMOST_AUTO_RESTART_MINUTES=0' >> "$f"
      fi

      if grep -q '^TELEMOST_LOG_STALL_MINUTES=' "$f"; then
        sed -i 's/^TELEMOST_LOG_STALL_MINUTES=.*/TELEMOST_LOG_STALL_MINUTES=0/' "$f"
      else
        echo 'TELEMOST_LOG_STALL_MINUTES=0' >> "$f"
      fi
    done
  fi
}

if [[ "$INSTALL_MODE" == "1" ]]; then
  echo "Update mode selected."
  apt update
  DEBIAN_FRONTEND=noninteractive apt install -y python3 python3-pip python3-venv sqlite3 curl git ca-certificates

  install_bot_files

  echo
  echo "Testing bot code syntax..."
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  "$APP_DIR/.venv/bin/python" -m py_compile "$APP_DIR/bot.py"

  echo
  echo "Restarting bot..."
  disable_telemost_periodic_restart
  systemctl enable --now polka-rtc-bot
  systemctl enable --now polka-rtc-watchdog.timer
  systemctl restart polka-rtc-bot
  systemctl restart polka-rtc-watchdog.timer

  echo
  echo "=== Updated ==="
  echo "Bot service: systemctl status polka-rtc-bot --no-pager"
  echo "Bot logs:    journalctl -fu polka-rtc-bot"
  exit 0
fi

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
  echo "Building original OlcRTC from $OLCRTC_REPO_URL branch $OLCRTC_BRANCH..."
  rm -rf "$OLCRTC_SRC"
  git clone --branch "$OLCRTC_BRANCH" --recurse-submodules "$OLCRTC_REPO_URL" "$OLCRTC_SRC"
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
  echo "If OlcRTC exists elsewhere, create a symlink:"
  echo "mkdir -p $OLCRTC_BIN_DIR && ln -sf /path/to/olcrtc $OLCRTC_BIN_DIR/olcrtc"
  exit 1
fi

install_bot_files

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

# Telemost stability mode.
# 0 disables stable fields for new Telemost clients.
TELEMOST_STABLE_MODE=1
# 0 is recommended. Active Telemost sessions must not be restarted automatically.
TELEMOST_AUTO_RESTART_MINUTES=0
# Disabled by default because some healthy olcrtc builds are quiet.
TELEMOST_LOG_STALL_MINUTES=0

# refactor = original olcrtc refactor/universal-carrier YAML config mode.
# URI format is left legacy for current OlcBox compatibility.
OLCRTC_GENERATION=refactor
OLCRTC_URI_FORMAT=legacy

BACKUP_DIR=/var/backups/polka-rtc
EOF
chmod 600 "$ENV_FILE"

echo
echo "Testing bot code syntax..."
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
"$APP_DIR/.venv/bin/python" -m py_compile "$APP_DIR/bot.py"

echo
echo "Starting bot..."
disable_telemost_periodic_restart
systemctl enable --now polka-rtc-bot
systemctl enable --now polka-rtc-watchdog.timer
systemctl restart polka-rtc-bot
systemctl restart polka-rtc-watchdog.timer

echo
echo "=== Installed ==="
echo "Bot service: systemctl status polka-rtc-bot --no-pager"
echo "Bot logs:    journalctl -fu polka-rtc-bot"
echo "Backup CLI:  polka-rtc-backup"
echo
echo "Open your Telegram bot and send /start"
