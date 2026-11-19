# VPS + Xray VLESS Reality: установка с нуля (2026)

Гайд для случая «нужен сервер, к которому можно подключиться». Reality маскирует соединение под обычный HTTPS
к чужому домену, поэтому не требует своего сертификата и домена. Времени — 10–15 минут.

Проверено на Ubuntu 24.04, Xray 26.x. Команды даны в том виде, в котором их можно копировать.

## 1. Сервер

| Параметр | Значение |
|---|---|
| ОС | Ubuntu 24.04 LTS (22.04 тоже работает) |
| RAM | 512 МБ достаточно, 1 ГБ комфортно |
| Локация | вне РФ; для белых списков предпочтительнее адрес из разрешённой подсети (см. [`whitelisted-hosting.md`](./whitelisted-hosting.md)) |
| Порты | 443/tcp |

Если сервер нужен именно под белые списки, **сначала** проверьте выданный IP:

```bash
python3 tools/wlcheck.py --ip $(curl -4 -s ifconfig.me)
```

## 2. Базовая подготовка

```bash
ssh root@АДРЕС_СЕРВЕРА
apt update && apt -y install curl openssl ufw
timedatectl set-timezone Europe/Moscow   # по желанию, для логов
```

`apt upgrade -y` сразу после установки ОС не обязателен: свежий образ уже пропатчен, а полное обновление
на слабом сервере иногда тянет за собой перезагрузку ядра.

## 3. Установка Xray

Официальный установщик:

```bash
bash -c "$(curl -Ls https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
xray version
```

Ожидаемый результат: строка вида `Xray 26.x.x` и путь `/usr/local/bin/xray`.
Сторонние «one-click» скрипты из случайных репозиториев не используйте: вы запускаете чужой код от root,
а содержимое такого скрипта может измениться в любой момент.

## 4. Ключи

```bash
xray x25519      # приватный и публичный ключ Reality
xray uuid        # UUID для клиента
openssl rand -hex 8   # shortId, 8 байт (16 hex-символов) — случайный, не «a1b2c3d4»
```

Формат вывода `xray x25519` зависит от версии: в новых это `PrivateKey:` / `Password:` (`Password` — это и есть
публичный ключ), в старых — `Private key:` / `Public key:`. Ориентируйтесь на фактические строки, а не на пример.

## 5. Конфиг сервера

`nano /usr/local/etc/xray/config.json`:

```json
{
  "log": { "loglevel": "warning" },
  "inbounds": [{
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{ "id": "ВАШ-UUID", "flow": "xtls-rprx-vision" }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "show": false,
        "dest": "www.microsoft.com:443",
        "serverNames": ["www.microsoft.com"],
        "privateKey": "ВАШ-ПРИВАТНЫЙ-КЛЮЧ",
        "shortIds": ["ВАШ-SHORT-ID"]
      }
    },
    "sniffing": { "enabled": true, "destOverride": ["http", "tls"] }
  }],
  "outbounds": [{ "protocol": "freedom" }]
}
```

Что важно:

- `dest` и `serverNames` должны указывать на **один и тот же** чужой сайт с поддержкой TLS 1.3 и HTTP/2;
- `privateKey` — только приватный ключ, публичный идёт в клиентскую ссылку;
- `flow` — `xtls-rprx-vision` для TCP; для XHTTP flow не указывается;
- access-log выключен намеренно: иначе адреса клиентов пишутся на диск.

Проверка конфига **до** перезапуска:

```bash
xray -test -config /usr/local/etc/xray/config.json
```

Если проверка ругается на геоданные — запускайте из каталога с ассетами:
`cd /usr/local/x-ui/bin 2>/dev/null || cd /usr/local/share/xray; xray -test -config /usr/local/etc/xray/config.json`.

## 6. Запуск

```bash
ufw allow 443/tcp
ufw allow 22/tcp          # не отрежьте себя
ufw --force enable
systemctl enable --now xray
systemctl is-active xray   # ожидается: active
journalctl -u xray -n 30 --no-pager
```

Автообновление ядра через cron ставить не нужно: у Xray нет команды `update:core`, а смена мажорной версии
без проверки ломает рабочий конфиг. Обновляйтесь осознанно: остановка, установка, `xray -test`, запуск.

## 7. Клиентская ссылка

```
vless://UUID@АДРЕС:443?encryption=none&security=reality&flow=xtls-rprx-vision&fp=chrome&pbk=ПУБЛИЧНЫЙ_КЛЮЧ&sni=www.microsoft.com&sid=SHORT_ID&type=tcp#Мой-сервер
```

Соберите её аккуратно: UUID, `pbk` (публичный ключ), `sid` (shortId), `sni` — те же значения, что в конфиге.
Одна опечатка в `pbk` даёт «подключение есть, трафика нет» без внятной ошибки.

## 8. Проверка результата

```bash
# на сервере: слушает ли порт
ss -tlnp | grep :443

# на клиенте после подключения: чей адрес видит интернет
curl -s https://ifconfig.me
```

Если `ifconfig.me` вернул адрес сервера — канал работает. Если соединение устанавливается, но данные не идут, —
проверяйте `pbk`/`sid`/`sni` и версию ядра на клиенте.

## 9. Типовые ошибки

| Симптом | Причина | Что делать |
|---|---|---|
| `handshake failed` в логах клиента | несовпадение SNI/`pbk`/`sid` | сверить ссылку с конфигом посимвольно |
| подключение есть, трафика нет | неверный `flow` или старый клиент | обновить клиент, проверить `flow` |
| `xray -test` падает на геоданных | запуск не из каталога ассетов | `cd` в каталог с `geosite.dat` |
| после рестарта всё легло | конфиг с синтаксической ошибкой | откат из `config.json.bak_*`, разбор ошибки |
| работает дома, не работает на мобильном | режим белых списков | см. [`check-whitelist.md`](./check-whitelist.md) |

## 10. Что дальше

- нужен вход, который проходит белые списки, — [`two-hop-relay.md`](./two-hop-relay.md);
- нужен выбор хостинга — [`whitelisted-hosting.md`](./whitelisted-hosting.md);
- бесплатные шаблоны конфигов — [`../configs/`](../configs).
