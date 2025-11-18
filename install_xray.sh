#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Xray REALITY + VLESS + Vision (2025) ===${NC}"

apt update && apt upgrade -y

echo -e "${GREEN}Установка Xray...${NC}"
bash <(curl -Ls https://raw.githubusercontent.com/XTLS/Xray-install/main/install-release.sh) @ install

echo -e "${GREEN}Генерация ключей...${NC}"
PRIVATE_KEY=$(xray x25519 | awk '/Private key:/ {print $3}')
PUBLIC_KEY=$(xray x25519 | awk '/Public key:/ {print $3}')
UUID=$(xray uuid)
SHORT_ID=$(openssl rand -hex 4)

cat > /usr/local/etc/xray/config.json <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [{
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{"id": "$UUID", "flow": "xtls-rprx-vision"}],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "show": false,
        "fingerprint": "chrome",
        "dest": "www.microsoft.com:443",
        "serverNames": ["www.microsoft.com","login.microsoft.com"],
        "privateKey": "$PRIVATE_KEY",
        "publicKey": "$PUBLIC_KEY",
        "shortIds": ["$SHORT_ID","a1b2c3d4"]
      }
    },
    "sniffing": {"enabled": true, "destOverride": ["http","tls"]}
  }],
  "outbounds": [{"protocol": "freedom"}]
}
EOF

# Проверка конфига
xray -test -config /usr/local/etc/xray/config.json || exit 1

ufw allow 443/tcp 2>/dev/null || true
systemctl restart xray && systemctl enable xray

IP=$(curl -s ifconfig.me)

echo -e "${GREEN}ГОТОВО!${NC}"
echo "UUID: $UUID"
echo "Public Key: $PUBLIC_KEY"
echo "Short ID: $SHORT_ID"
echo
echo "Ссылка для клиента:"
echo "vless://$UUID@$IP:443?security=reality&encryption=none&flow=xtls-rprx-vision&fp=chrome&pbk=$PUBLIC_KEY&sni=www.microsoft.com&sid=$SHORT_ID&type=tcp#Reality-2025"
echo
echo "Сохраните эту ссылку — она больше не появится!"
