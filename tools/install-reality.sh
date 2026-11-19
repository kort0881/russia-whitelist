#!/bin/bash
# Установка Xray + VLESS Reality с генерацией ключей и проверкой конфига.
# Проверено на Ubuntu 22.04/24.04, Xray 26.x.
#
# Использование:
#   bash tools/install-reality.sh                 # интерактивно, спросит домен-донор
#   DEST=www.microsoft.com bash tools/install-reality.sh
#
# Скрипт ничего не публикует и не отправляет наружу: только локальная установка.
set -euo pipefail

DEST="${DEST:-www.microsoft.com}"
PORT="${PORT:-443}"
CONFIG_DIR="/usr/local/etc/xray"
CONFIG="$CONFIG_DIR/config.json"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say() { echo -e "${GREEN}$*${NC}"; }
warn() { echo -e "${YELLOW}$*${NC}"; }
die() { echo -e "${RED}$*${NC}" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "запускать от root"

say "=== Xray + VLESS Reality ==="
warn "домен-донор: $DEST:$PORT"

# 1. Базовые пакеты
apt-get update -qq
apt-get install -y -qq curl openssl ca-certificates >/dev/null

# 2. Установка ядра официальным установщиком
if ! command -v xray >/dev/null 2>&1; then
  say "установка Xray..."
  bash -c "$(curl -Ls https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
else
  warn "Xray уже установлен: $(xray version | head -1)"
fi

# 3. Проверка, что донор вообще отвечает по TLS (иначе Reality не работает)
say "проверка донора $DEST:$PORT ..."
if ! timeout 8 openssl s_client -connect "$DEST:$PORT" -servername "$DEST" </dev/null 2>/dev/null | grep -q "BEGIN CERTIFICATE"; then
  die "донор $DEST:$PORT не отдаёт TLS. Возьмите другой домен (нужен TLS 1.3 + HTTP/2)."
fi

# 4. Ключи. Формат вывода xray x25519 меняется между версиями — разбираем оба.
X25519_OUT="$(xray x25519)"
PRIVATE_KEY="$(printf '%s\n' "$X25519_OUT" | awk -F': *' '/Private ?[Kk]ey/ {print $2; exit}')"
PUBLIC_KEY="$(printf '%s\n' "$X25519_OUT" | awk -F': *' '/Public ?[Kk]ey|^Password/ {print $2; exit}')"
[ -n "${PRIVATE_KEY:-}" ] && [ -n "${PUBLIC_KEY:-}" ] || die "не удалось разобрать вывод xray x25519: $X25519_OUT"

UUID="$(xray uuid)"
SHORT_ID="$(openssl rand -hex 8)"

# 5. Конфиг
say "запись конфига..."
mkdir -p "$CONFIG_DIR"
[ -f "$CONFIG" ] && cp -a "$CONFIG" "$CONFIG.bak_$(date +%F_%H%M%S)"

cat > "$CONFIG" <<EOF
{
  "log": { "loglevel": "warning" },
  "inbounds": [{
    "port": $PORT,
    "protocol": "vless",
    "settings": {
      "clients": [{ "id": "$UUID", "flow": "xtls-rprx-vision" }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "show": false,
        "dest": "$DEST:$PORT",
        "serverNames": ["$DEST"],
        "privateKey": "$PRIVATE_KEY",
        "shortIds": ["$SHORT_ID"]
      }
    },
    "sniffing": { "enabled": true, "destOverride": ["http", "tls"] }
  }],
  "outbounds": [{ "protocol": "freedom" }]
}
EOF

# 6. Проверка конфига ДО запуска
say "проверка конфига..."
if ! xray -test -config "$CONFIG"; then
  die "конфиг не прошёл проверку — исправьте и запустите снова"
fi

# 7. Файрвол: не отрезать себя от SSH
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow "$PORT"/tcp >/dev/null 2>&1 || true
fi

# 8. Запуск
systemctl enable xray >/dev/null 2>&1 || true
systemctl restart xray
sleep 1
ACTIVE="$(systemctl is-active xray || true)"
[ "$ACTIVE" = "active" ] || die "xray не поднялся: status=$ACTIVE (journalctl -u xray -n 50)"

SERVER_IP="$(curl -4 -s --max-time 8 https://ifconfig.me || echo 'ВАШ_IP')"

say "=== ГОТОВО ==="
cat <<EOF

Сервер:  $SERVER_IP:$PORT
UUID:    $UUID
pubkey:  $PUBLIC_KEY
shortId: $SHORT_ID
sni:     $DEST

Ссылка для клиента:
vless://$UUID@$SERVER_IP:$PORT?encryption=none&security=reality&flow=xtls-rprx-vision&fp=chrome&pbk=$PUBLIC_KEY&sni=$DEST&sid=$SHORT_ID&type=tcp#Reality

Сохраните значения: приватный ключ повторно выводить не нужно, а UUID понадобится при выдаче доступа.
Если сервер нужен под белые списки — проверьте адрес: python3 tools/wlcheck.py --ip $SERVER_IP
EOF
