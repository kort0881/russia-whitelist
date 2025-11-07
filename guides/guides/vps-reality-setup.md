# Как поднять VPS для Reality (XRay/VLESS) — Обход белых списков РФ

> **Цель:** Настроить VPS с **XRay + Reality**, чтобы маскировать трафик под `yandex.ru` и обходить DPI при шатдаунах.  
> **Тестировалось:** Ubuntu 22.04, МТС/Билайн, ноябрь 2025  
> **Время:** 15 минут

---

## Шаг 1: Выбор VPS

| Провайдер | IP | Цена | Рекомендация |
|---------|----|------|-------------|
| **Hetzner** | EU/USA | от 3€ | Лучший (чистые IP) |
| **Vultr** | EU/USA | от $5 | Хорошо |
| **DigitalOcean** | EU | от $6 | Норм |
| **FirstVDS / Beget** | РФ | от 200₽ | **Не бери** — блокируют при DPI |

> **IP должен быть НЕ из РФ!** Иначе DPI заблокирует.

---

## Шаг 2: Подключаемся к VPS

```bash
ssh root@ВАШ_IP
Обновляем систему:
bashapt update && apt upgrade -y

Шаг 3: Устанавливаем XRay
bashbash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install.sh)"

Установка займёт ~1 минуту.
XRay будет в /usr/local/bin/xray


Шаг 4: Генерируем ключи Reality
bashxray x25519
Пример вывода:
textPrivate key: XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
Public key:  YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY
Сохрани оба!

Шаг 5: Создаём конфиг /usr/local/etc/xray/config.json
bashnano /usr/local/etc/xray/config.json
Вставь:
json{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "ЗДЕСЬ_ТВОЙ_UUID",
            "flow": "xtls-rprx-vision"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.yandex.ru:443",
          "xver": 0,
          "serverNames": ["www.yandex.ru"],
          "privateKey": "ЗДЕСЬ_PRIVATE_KEY",
          "publicKey": "ЗДЕСЬ_PUBLIC_KEY",
          "shortIds": ["a1b2c3d4"]
        }
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom"
    }
  ]
}
Замени:

ЗДЕСЬ_ТВОЙ_UUID → сгенерируй: xray uuid
ЗДЕСЬ_PRIVATE_KEY → из xray x25519
ЗДЕСЬ_PUBLIC_KEY → из xray x25519


Шаг 6: Запускаем XRay
bashsystemctl restart xray
systemctl enable xray
systemctl status xray

Должно быть: active (running)


Шаг 7: Клиент (на телефоне/ПК)
Nekobox / v2rayNG (Android)

Добавить сервер → VLESS
Адрес: ВАШ_IP_VPS
Порт: 443
UUID: тот же, что в конфиге
Flow: xtls-rprx-vision
TLS: reality
SNI / Server Name: www.yandex.ru
Public Key: из xray x25519
Short ID: a1b2c3d4

→ Подключиться

Проверка обхода

Включи мобильный интернет (МТС/Билайн)
Дождись шатдауна (или проверь на youtube.com)
Подключись через Nekobox
Должно работать! — YouTube, Telegram, всё


Если не работает





















ПроблемаРешениеОтваливается на 2GПопробуй dest: vk.com:443Блок по IPСмени VPS или включи Cloudflare (CDN)Ошибка handshakeПроверь shortIds и publicKey

Автостарт + обновление
bashcrontab -e
Добавь:
bash0 3 * * * /usr/local/bin/xray update:core

Полезные команды
bashxray uuid          # новый UUID
xray x25519        # новые ключи
journalctl -u xray -f  # логи

Готово!
Теперь твой трафик маскируется под Yandex и обходит белые списки.
Поделся в Discussions:

Работает ли у тебя? Регион? Оператор?

Теги: #vps #reality #xray #обход #whitelist
text---





















