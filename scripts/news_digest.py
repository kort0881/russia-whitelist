#!/usr/bin/env python3
"""Сбор заметки по новостям: белые списки, шатдауны, DPI, VPN-протоколы и профильные репозитории.

Без внешних зависимостей. Работает в двух режимах:

  * с ключом Groq (`GROQ_API_KEY`, api.groq.com, бесплатный тариф) — заметку пишет LLM на русском;
  * без ключа — экстрактивный дайджест (заголовки, источники, ссылки), без вызовов LLM.

Примеры:
    python3 scripts/news_digest.py --out notes/2026-11-19.md
    python3 scripts/news_digest.py --limit 10 --json > /tmp/news.json
    GROQ_API_KEY=... python3 scripts/news_digest.py --model openai/gpt-oss-120b
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

TIMEOUT = 25
UA = "russia-whitelist-news/1.0 (+https://github.com/kort0881/russia-whitelist)"

NEWS_QUERIES = [
    "белые списки мобильный интернет when:30d",
    "шатдаун мобильного интернета Россия when:30d",
    "Роскомнадзор блокировка VPN when:30d",
    "ТСПУ DPI блокировка трафика when:30d",
    "VPN Россия блокировка when:30d",
    "russia whitelist mobile internet shutdown when:30d",
]

HABR_FEED = "https://habr.com/ru/rss/news/?fl=ru"

KEYWORDS = [
    "белы", "whitelist", "шатдаун", "shutdown", "отключен", "ограничен",
    "тспу", "dpi", "ркн", "роскомнадзор", "блокир", "vpn", "vless", "reality",
    "xray", "прокси", "proxy", "cdn", "мобильн", "оператор", "связ",
    "яндекс", "yandex cloud", "vk cloud", "dns", "цензур", "censorship",
]

GITHUB_QUERIES = [
    "whitelist russia in:name,description,readme",
    "russia vpn list in:name,description",
    "topic:whitelist",
]


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def relevant(title: str, summary: str = "") -> bool:
    blob = f"{title} {summary}".lower()
    return any(k in blob for k in KEYWORDS)


# --- источники ------------------------------------------------------------

def news_from_google(limit: int) -> list:
    items, seen = [], set()
    for query in NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote(query)
               + "&hl=ru&gl=RU&ceid=RU:ru")
        try:
            root = ET.fromstring(http_get(url))
        except Exception as exc:  # noqa: BLE001 — источник может быть недоступен
            print(f"[!] google news '{query}': {exc}", file=sys.stderr)
            continue

        for node in root.iter("item"):
            title = strip_tags(node.findtext("title") or "")
            link = (node.findtext("link") or "").strip()
            pub = (node.findtext("pubDate") or "").strip()
            src = node.find("{*}source")
            source = strip_tags(src.text) if src is not None and src.text else "Google News"
            if not title or not link:
                continue
            key = re.sub(r"\W+", "", title.lower())[:90]
            if key in seen:
                continue
            if not relevant(title):
                continue
            seen.add(key)
            items.append({
                "kind": "news",
                "title": title,
                "url": link,
                "source": source,
                "published": pub,
                "summary": "",
            })
        if len(items) >= limit * 3:
            break
    return items


def news_from_habr(limit: int) -> list:
    try:
        root = ET.fromstring(http_get(HABR_FEED))
    except Exception as exc:  # noqa: BLE001
        print(f"[!] habr rss: {exc}", file=sys.stderr)
        return []

    items = []
    for node in root.iter("item"):
        title = strip_tags(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        desc = strip_tags(node.findtext("description") or "")[:400]
        if not title or not link or not relevant(title, desc):
            continue
        items.append({
            "kind": "news",
            "title": title,
            "url": link,
            "source": "Habr",
            "published": (node.findtext("pubDate") or "").strip(),
            "summary": desc,
        })
        if len(items) >= limit:
            break
    return items


def repos_from_github(limit: int) -> list:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    since = (dt.date.today() - dt.timedelta(days=14)).isoformat()
    out, seen = [], set()
    for query in GITHUB_QUERIES:
        q = f"{query} pushed:>{since}"
        url = "https://api.github.com/search/repositories?sort=updated&order=desc&per_page=8&q=" \
              + urllib.parse.quote(q)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[!] github '{query}': {exc}", file=sys.stderr)
            continue

        for repo in data.get("items", []):
            full = repo.get("full_name")
            if not full or full in seen:
                continue
            seen.add(full)
            out.append({
                "kind": "repo",
                "title": full,
                "url": repo.get("html_url") or f"https://github.com/{full}",
                "source": "GitHub",
                "published": (repo.get("pushed_at") or "")[:10],
                "stars": repo.get("stargazers_count", 0),
                "summary": strip_tags(repo.get("description") or "")[:300],
            })
        if len(out) >= limit:
            break
    out.sort(key=lambda r: r.get("stars", 0), reverse=True)
    return out[:limit]


# --- LLM ------------------------------------------------------------------

def llm_note(items: list, model: str) -> str:
    api_key = os.environ["GROQ_API_KEY"]
    base = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты аналитик по сетевой цензуре и доступу к интернету в России. Пишешь короткие деловые "
                    "заметки на русском языке для технического репозитория о белых списках мобильного интернета.\n"
                    "Правила:\n"
                    "1. Только факты из предоставленных материалов. Ничего не додумывай, чисел и деталей "
                    "не добавляй, причин и последствий не выдумывай.\n"
                    "2. Если у материала есть только заголовок — пункт состоит из сути заголовка, не больше.\n"
                    "3. Никаких вступлений, никакого повторения шаблона, никакой рекламы, никаких персональных "
                    "данных и призывов.\n"
                    "4. Формат: markdown, 5-8 пунктов, каждый ровно так: '- **Тезис.** Суть в 1-2 предложениях. "
                    "[Источник](ссылка)'. Дата публикации — если она есть в материале.\n"
                    "5. В конце раздел '## Что это значит для белых списков': 2-3 предложения, и явно помечай "
                    "это как интерпретацию, а не факт."
                ),
            },
            {
                "role": "user",
                "content": "Материалы:\n\n" + json.dumps(items, ensure_ascii=False, indent=1)[:24000],
            },
        ],
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def extractive_note(items: list) -> str:
    lines = []
    news = [i for i in items if i["kind"] == "news"][:8]
    repos = [i for i in items if i["kind"] == "repo"][:5]

    if news:
        lines.append("## Новости")
        for i in news:
            extra = f" — {i['summary'][:200]}" if i.get("summary") else ""
            lines.append(f"- **{i['title']}**{extra} ({i['source']}, {i['published']}) — [ссылка]({i['url']})")
    if repos:
        lines.append("\n## Репозитории и проекты")
        for i in repos:
            lines.append(f"- [{i['title']}]({i['url']}) ★{i.get('stars', 0)} — {i.get('summary') or 'без описания'}")
    if not lines:
        lines.append("_За сутки релевантных материалов не найдено. Проверено: новостные RSS и GitHub._")
    lines.append("\n_Заметка собрана без LLM (нет ключа XAI_API_KEY): заголовки и ссылки как есть, без анализа._")
    return "\n".join(lines)


# --- вывод ----------------------------------------------------------------

def is_fresh(item: dict, days: int) -> bool:
    """Материал не старше days суток. Если дату разобрать не удалось — считаем свежим."""
    raw = item.get("published") or ""
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(raw)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - d).days <= days
    except Exception:  # noqa: BLE001 — формат даты у источников разный
        return True


def render(items: list, note: str, model: str | None, limit: int) -> str:
    today = dt.date.today().isoformat()
    head = [
        f"# Заметка по новостям — {today}",
        "",
        f"Источников проверено: {len(items)}. Режим: "
        + (f"LLM Groq ({model})" if model else "экстрактивный дайджест (без LLM)") + ".",
        "",
    ]
    tail = [
        "",
        "---",
        "",
        "Автоматическая заметка. Ссылки ведут на первоисточники; проверяйте дату публикации.",
        "Данные о белых списках — в [`whitelist.txt`](../whitelist.txt) и [`data/upstream/`](../data/upstream).",
    ]
    return "\n".join(head) + "\n" + note + "\n" + "\n".join(tail) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Заметка по новостям о белых списках и VPN-протоколах")
    ap.add_argument("--limit", type=int, default=12, help="сколько материалов брать (по умолчанию 12)")
    ap.add_argument("--days", type=int, default=45, help="брать новости не старше N суток (по умолчанию 45)")
    ap.add_argument("--out", help="путь к markdown-файлу; по умолчанию notes/<дата>.md")
    ap.add_argument("--model", default=os.environ.get("NEWS_MODEL", "openai/gpt-oss-120b"),
                    help="модель LLM (по умолчанию openai/gpt-oss-120b на api.groq.com)")
    ap.add_argument("--no-llm", action="store_true", help="не вызывать LLM даже при наличии ключа")
    ap.add_argument("--json", action="store_true", help="напечатать собранные материалы и выйти")
    args = ap.parse_args(argv)

    items = news_from_google(args.limit) + news_from_habr(args.limit) + repos_from_github(6)
    items = [i for i in items if i["kind"] != "news" or is_fresh(i, args.days)]
    items = items[: args.limit + 6]

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    model = None
    if os.environ.get("GROQ_API_KEY") and not args.no_llm:
        try:
            note = llm_note(items[: args.limit], args.model)
            model = args.model
        except Exception as exc:  # noqa: BLE001 — деградируем, но не падаем
            print(f"[!] LLM недоступен ({exc}); собираю экстрактивный дайджест", file=sys.stderr)
            note = extractive_note(items)
    else:
        note = extractive_note(items)

    out = args.out or os.path.join("notes", f"{dt.date.today().isoformat()}.md")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(items, note, model, args.limit))
    print(f"записано: {out} (материалов: {len(items)}, режим: {'llm' if model else 'extractive'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
