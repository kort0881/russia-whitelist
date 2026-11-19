#!/usr/bin/env python3
"""Проверка IP или домена по публичным белым спискам операторов мобильной связи РФ.

Без внешних зависимостей, Python 3.8+.

Примеры:
    python3 tools/wlcheck.py --ip 203.0.113.10
    python3 tools/wlcheck.py --domain example.com
    python3 tools/wlcheck.py --domain example.com --json
    python3 tools/wlcheck.py --ip 203.0.113.10 --refresh     # принудительно обновить данные

Коды возврата:
    0 — найден в белом списке
    1 — не найден
    2 — ошибка ввода / не удалось получить данные
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.request

UPSTREAM = "https://raw.githubusercontent.com/kort0881/russia-whitelist/main/data/upstream"
MIRROR = "https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main"

FILES = {
    "cidr": "cidrwhitelist.txt",
    "ip": "ipwhitelist.txt",
    "domains": "whitelist-domains-upstream.txt",
}

# у источника-зеркала файлы называются иначе
MIRROR_NAMES = {
    "cidrwhitelist.txt": "cidrwhitelist.txt",
    "ipwhitelist.txt": "ipwhitelist.txt",
    "whitelist-domains-upstream.txt": "whitelist.txt",
}

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "wlcheck")
CACHE_TTL = 12 * 3600  # секунд


def cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, name)


def fetch(name: str, refresh: bool, timeout: int = 30) -> str:
    """Возвращает содержимое списка, скачивая его при необходимости."""
    dst = cache_path(name)
    if not refresh and os.path.exists(dst) and time.time() - os.path.getmtime(dst) < CACHE_TTL:
        with open(dst, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    os.makedirs(CACHE_DIR, exist_ok=True)
    last_err: Exception | None = None
    for base, fname in ((UPSTREAM, name), (MIRROR, MIRROR_NAMES.get(name, name))):
        url = f"{base}/{fname}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wlcheck/1.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(data)
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:  # noqa: UP041
            last_err = exc
            continue

    # если сеть недоступна — используем устаревший кэш, но предупреждаем
    if os.path.exists(dst):
        print(f"[!] не удалось обновить {name} ({last_err}); используется кэш", file=sys.stderr)
        with open(dst, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    raise SystemExit(f"[x] не удалось получить {name}: {last_err}")


def parse_lines(text: str):
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            yield line


def load_cidrs(refresh: bool) -> list:
    nets = []
    for line in parse_lines(fetch(FILES["cidr"], refresh)):
        try:
            nets.append(ipaddress.ip_network(line, strict=False))
        except ValueError:
            continue
    return nets


def load_ips(refresh: bool) -> set:
    out = set()
    for line in parse_lines(fetch(FILES["ip"], refresh)):
        try:
            out.add(ipaddress.ip_address(line))
        except ValueError:
            continue
    return out


def load_domains(refresh: bool) -> set:
    out = set()
    for line in parse_lines(fetch(FILES["domains"], refresh)):
        out.add(line.lower().lstrip("*.").split(":")[0])
    return out


def check_ip(value: str, refresh: bool) -> dict:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return {"input": value, "error": "не является IP-адресом"}

    cidrs = load_cidrs(refresh)
    ips = load_ips(refresh)

    hit_nets = [str(n) for n in cidrs if addr in n]
    in_ips = addr in ips

    return {
        "input": value,
        "type": "ip",
        "found": bool(hit_nets) or in_ips,
        "matched_networks": hit_nets[:10],
        "matched_single_ip": in_ips,
        "checked_networks": len(cidrs),
        "checked_single_ips": len(ips),
    }


def domain_candidates(name: str) -> list:
    name = name.lower().strip().rstrip(".")
    parts = name.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def check_domain(value: str, refresh: bool) -> dict:
    name = value.lower().strip()
    if "/" in name or " " in name:
        return {"input": value, "error": "укажите домен без схемы и пути, например example.com"}

    domains = load_domains(refresh)
    hits = [c for c in domain_candidates(name) if c in domains]

    return {
        "input": value,
        "type": "domain",
        "found": bool(hits),
        "matched_domains": hits,
        "checked_domains": len(domains),
    }


def human(result: dict) -> str:
    if "error" in result:
        return f"{result['input']}: ошибка — {result['error']}"

    if result["type"] == "ip":
        head = f"IP {result['input']}"
    else:
        head = f"Домен {result['input']}"

    if result["found"]:
        verdict = "НАЙДЕН в белом списке"
    else:
        verdict = "НЕ найден в белом списке"

    lines = [head, f"  результат: {verdict}"]

    if result["type"] == "ip":
        lines.append(f"  проверено подсетей: {result['checked_networks']}, "
                     f"отдельных IP: {result['checked_single_ips']}")
        if result["matched_networks"]:
            lines.append("  совпавшие подсети: " + ", ".join(result["matched_networks"]))
        if result["matched_single_ip"]:
            lines.append("  совпало по списку отдельных адресов")
    else:
        lines.append(f"  проверено доменов: {result['checked_domains']}")
        if result["matched_domains"]:
            lines.append("  совпавшие домены: " + ", ".join(result["matched_domains"]))

    if not result["found"]:
        lines.append("  примечание: списки — пересечение по операторам; у конкретного оператора набор может быть шире")

    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Проверка IP или домена по белым спискам операторов РФ")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--ip", help="IP-адрес, например 203.0.113.10")
    group.add_argument("--domain", help="домен, например example.com")
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    ap.add_argument("--refresh", action="store_true", help="принудительно обновить списки")
    args = ap.parse_args(argv)

    result = check_ip(args.ip, args.refresh) if args.ip else check_domain(args.domain, args.refresh)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(human(result))

    if "error" in result:
        return 2
    return 0 if result["found"] else 1


if __name__ == "__main__":
    sys.exit(main())
