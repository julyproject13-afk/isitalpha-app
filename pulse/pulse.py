#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pulse — двухсторонний мост isitalpha: владелец (Telegram) <-> ИИ-ассистент (Claude API), 24/7.
Чистый Python stdlib (0 pip). Демон под systemd (Restart=always).

Секреты берутся из окружения ИЛИ из ./bootstrap.env (chmod 600, не в git):
    PULSE_TG_TOKEN     — токен бота от @BotFather
    ANTHROPIC_API_KEY  — ключ Anthropic (мозг)
    OWNER_CHAT_ID      — chat_id владельца (whitelist). Если пуст — режим знакомства (см. ниже).

Главный урок прошлого моста: он молчал, потому что не был ПОСТОЯННЫМ сервисом.
Здесь — вечный цикл long-poll + systemd Restart=always. Всегда живой, всегда отвечает.
"""
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
HISTORY_FILE = HERE / "pulse_history.json"
OFFSET_FILE = HERE / "pulse_offset.txt"
CONTEXT_FILE = HERE / "PULSE_CONTEXT.md"
LOG = lambda m: print(time.strftime("%Y-%m-%d %H:%M:%S "), m, flush=True)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 1500
HISTORY_KEEP = 40          # сколько последних сообщений шлём в контекст Claude
POLL_TIMEOUT = 30          # long-poll Telegram, сек
SITE_URL = "https://isitalpha.com/"
ALERT_INTERVAL = 300       # как часто проверять здоровье сайта, сек


# ---------- секреты ----------
def load_env_file():
    """Подхватить KEY=VALUE из ./bootstrap.env, не перетирая реальное окружение."""
    f = HERE / "bootstrap.env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


load_env_file()
TG_TOKEN = os.environ.get("PULSE_TG_TOKEN", "").strip()
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "").strip()

if not TG_TOKEN or not ANTHROPIC_KEY:
    LOG("ОШИБКА: нет PULSE_TG_TOKEN или ANTHROPIC_API_KEY (положи в bootstrap.env). Выход.")
    sys.exit(1)


# ---------- контекст проекта (system-промпт) ----------
DEFAULT_CONTEXT = """Ты — Pulse, личный ИИ-ассистент владельца проекта isitalpha (честный валидатор торговых стратегий, сайт https://isitalpha.com уже в эфире). Ты на связи 24/7 через Telegram.

Кто ты: открытый ИИ-ассистент (не выдаёшь себя за человека). Помощник и оператор проекта.
Кто владелец: председатель/дирижёр. Принимает ключевые решения, утверждает бюджеты, несёт ответственность.

Правила (жёстко):
- Деньги и сделки — только руками владельца. Ты НЕ исполняешь сделки, не двигаешь средства, не вводишь чужие/его пароли.
- Честность и законность — базис. Никаких фейк-личностей, накруток, обмана, чужого KYC.
- Секреты (токены/ключи) — никогда не печатать в чат/логи.
- Отвечай коротко, по-русски, по делу. Сложное — раскладывай по шагам.

Твоя задача: держать владельца в курсе (статус сайта, события), помогать с задачами проекта, эскалировать сложное в рабочие сессии. Будь спокойным, тёплым и полезным."""

PROJECT_CONTEXT = CONTEXT_FILE.read_text(encoding="utf-8") if CONTEXT_FILE.exists() else DEFAULT_CONTEXT


# ---------- HTTP ----------
def _post_json(url, payload, headers, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def tg_get_updates(offset):
    url = (f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
           f"?offset={offset}&timeout={POLL_TIMEOUT}")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 15) as r:
        body = json.loads(r.read().decode("utf-8"))
    return body.get("result", []) if body.get("ok") else []


def tg_send(chat_id, text):
    """Шлём простым текстом (без parse_mode) — надёжнее, не падает на спецсимволах."""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    # Telegram лимит 4096 символов — режем при необходимости
    for chunk_start in range(0, len(text) or 1, 4000):
        chunk = text[chunk_start:chunk_start + 4000] or " "
        try:
            _post_json(url, {"chat_id": chat_id, "text": chunk},
                       {"Content-Type": "application/json"}, 20)
        except Exception as e:
            LOG(f"tg_send ошибка: {e}")


def claude_reply(messages):
    """messages = [{'role':'user'|'assistant','content':str}, ...] -> текст ответа."""
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": PROJECT_CONTEXT,
        "messages": messages[-HISTORY_KEEP:],
    }
    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    try:
        body = _post_json("https://api.anthropic.com/v1/messages", payload, headers, 120)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        LOG(f"Claude HTTPError {e.code}: {detail}")
        return "⚠️ Мозг (Claude API) вернул ошибку. Проверь баланс Anthropic/ключ. Я живой, попробуй ещё раз."
    except Exception as e:
        LOG(f"Claude ошибка: {e}")
        return "⚠️ Не достучался до Claude API (сеть?). Я на связи, повтори запрос."
    parts = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
    return ("".join(parts)).strip() or "(пустой ответ)"


# ---------- персистентность ----------
def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_history(h):
    try:
        HISTORY_FILE.write_text(json.dumps(h[-200:], ensure_ascii=False, indent=1),
                                encoding="utf-8")
    except Exception as e:
        LOG(f"save_history ошибка: {e}")


def load_offset():
    if OFFSET_FILE.exists():
        try:
            return int(OFFSET_FILE.read_text().strip())
        except Exception:
            return 0
    return 0


def save_offset(o):
    try:
        OFFSET_FILE.write_text(str(o))
    except Exception:
        pass


# ---------- проактивные алерты (здоровье сайта) ----------
def alert_loop():
    last_state = True  # считаем, что сайт жив
    while True:
        time.sleep(ALERT_INTERVAL)
        if not OWNER_CHAT_ID:
            continue
        alive = False
        try:
            with urllib.request.urlopen(SITE_URL, timeout=15) as r:
                alive = (r.status == 200)
        except Exception:
            alive = False
        if alive != last_state:
            if alive:
                tg_send(OWNER_CHAT_ID, "✅ isitalpha.com снова в эфире (200 OK).")
            else:
                tg_send(OWNER_CHAT_ID, "🔴 ВНИМАНИЕ: isitalpha.com не отвечает! Проверь сервер Koara.")
            last_state = alive


# ---------- главный цикл ----------
def main():
    LOG("Pulse запущен. " + ("OWNER_CHAT_ID задан." if OWNER_CHAT_ID
                              else "OWNER_CHAT_ID ПУСТ — режим знакомства (бот подскажет chat_id)."))
    threading.Thread(target=alert_loop, daemon=True).start()

    history = load_history()
    offset = load_offset()
    if OWNER_CHAT_ID:
        try:
            tg_send(OWNER_CHAT_ID, "🟢 Pulse на связи. Я снова живой и 24/7 с тобой.")
        except Exception:
            pass

    while True:
        try:
            updates = tg_get_updates(offset)
        except Exception as e:
            LOG(f"getUpdates ошибка: {e}; пауза 5с")
            time.sleep(5)
            continue

        for u in updates:
            offset = u["update_id"] + 1
            save_offset(offset)
            msg = u.get("message") or u.get("edited_message")
            if not msg:
                continue
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            if not text:
                continue

            # --- режим знакомства: OWNER_CHAT_ID ещё не задан ---
            if not OWNER_CHAT_ID:
                tg_send(chat_id,
                        f"Твой chat_id: {chat_id}\n\n"
                        f"Впиши его в bootstrap.env на сервере как OWNER_CHAT_ID и перезапусти Pulse — "
                        f"тогда я буду отвечать только тебе.")
                LOG(f"Знакомство: chat_id={chat_id} написал боту.")
                continue

            # --- whitelist: отвечаем только владельцу ---
            if str(chat_id) != str(OWNER_CHAT_ID):
                LOG(f"Игнор чужого chat_id={chat_id}")
                continue

            LOG(f"Владелец: {text[:80]}")
            history.append({"role": "user", "content": text})
            reply = claude_reply(history)
            history.append({"role": "assistant", "content": reply})
            save_history(history)
            tg_send(chat_id, reply)


if __name__ == "__main__":
    main()
