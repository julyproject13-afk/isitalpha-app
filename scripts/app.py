"""Honest Validator (Продукт 2) web-приложение. Самодостаточно, чистый stdlib.
Маршруты: /validate (форма) /report (отчёт) /api/validate (вердикт)
          /api/checkout (создать счёт NOWPayments) /api/ipn (вебхук оплаты) /api/unlock (проверка).
Пейволл: free = только вердикт-слово; полный отчёт — после оплаты $9.
Платёж: NOWPayments (non-custodial, USDT TRC20 → кошелёк владельца). Деньги напрямую владельцу, мы их не держим.
Секреты (NP_API_KEY, NP_IPN_SECRET) — в bootstrap.env, не в git.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
WEB = os.path.join(ROOT, "web")
PAID_FILE = os.path.join(ROOT, "paid_orders.txt")   # оплаченные order_id (локальный учёт)

from validator.validator import validate, parse_returns_csv      # noqa: E402

_CT = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8"}


def _load_env():
    f = os.path.join(ROOT, "bootstrap.env")
    if os.path.isfile(f):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
NP_API_KEY = os.environ.get("NP_API_KEY", "")          # ключ мерчанта NOWPayments (секрет)
NP_IPN_SECRET = os.environ.get("NP_IPN_SECRET", "")    # секрет для проверки вебхука (секрет)
SITE_URL = os.environ.get("SITE_URL", "https://isitalpha.com")
PRICE_USD = int(os.environ.get("PRICE_USD", "15"))   # $15 «all fees included»; меняется через bootstrap.env без правки кода.
PAY_CURRENCY = os.environ.get("PAY_CURRENCY", "")   # пусто = клиент сам выбирает валюту/сеть на оплате (Polygon дешевле всего). Можно форснуть через bootstrap.env (напр. usdcmatic).
TG_TOKEN = os.environ.get("PULSE_TG_TOKEN", "")        # бот для уведомлений (тот же, что Pulse)
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")    # чат владельца для алертов/сводки
REPORT_KEY = os.environ.get("REPORT_KEY", "")          # защита /api/report (простой ключ)
METRICS_FILE = os.path.join(ROOT, "metrics.json")      # бизнес-счётчики (локально)

FREE_FIELDS = ("verdict", "headline", "n", "reason")


# ---------- бизнес-метрики (попытки/продажи/выручка) ----------
def _metrics() -> dict:
    try:
        return json.load(open(METRICS_FILE, encoding="utf-8"))
    except Exception:
        return {"attempts": 0, "sales": 0, "revenue": 0, "first_ts": 0, "last_sale_ts": 0, "seen_orders": []}


def _save_metrics(m: dict):
    try:
        json.dump(m, open(METRICS_FILE, "w"))
    except Exception:
        pass


def _bump_attempt():
    import time
    m = _metrics()
    m["attempts"] = m.get("attempts", 0) + 1
    if not m.get("first_ts"):
        m["first_ts"] = int(time.time())
    _save_metrics(m)


def _record_sale(order_id: str) -> dict | None:
    """Учитывает продажу один раз на order (защита от дубля вебхука). None если уже учтён."""
    import time
    m = _metrics()
    seen = set(m.get("seen_orders", []))
    if order_id in seen:
        return None
    seen.add(order_id)
    m["seen_orders"] = list(seen)[-500:]
    m["sales"] = m.get("sales", 0) + 1
    m["revenue"] = m.get("revenue", 0) + PRICE_USD
    m["last_sale_ts"] = int(time.time())
    _save_metrics(m)
    return m


def tg_send(text: str):
    """Шлёт сообщение владельцу в Telegram (алерты/продажи/сводка). Тихо, не роняет запрос."""
    if not (TG_TOKEN and OWNER_CHAT_ID):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": OWNER_CHAT_ID, "text": text,
                                       "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                     data=data, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def stats_report() -> str:
    """Красивая бизнес-сводка для Telegram."""
    import time
    m = _metrics()
    a = m.get("attempts", 0); s = m.get("sales", 0); rev = m.get("revenue", 0)
    conv = (s / a * 100) if a else 0
    net = round(rev * 0.99, 2)          # минус ~1% NOWPayments
    per = f"${PRICE_USD} − ~${round(PRICE_USD*0.01,2)} комиссия = ~${round(PRICE_USD*0.99,2)} net"
    last = m.get("last_sale_ts", 0)
    last_s = time.strftime("%d.%m %H:%M", time.gmtime(last)) + " UTC" if last else "—"
    return (
        "📊 <b>isitalpha — сводка</b>\n\n"
        f"👀 Попыток проверки: <b>{a}</b>\n"
        f"✅ Продаж (${PRICE_USD}): <b>{s}</b>\n"
        f"💰 Выручка: <b>${rev}</b>  (net ~${net})\n"
        f"📈 Конверсия: <b>{conv:.1f}%</b>\n\n"
        f"📦 Юнит-экономика: {per}\n"
        f"🎯 CAC: добавь расход рекламы из реестра → CAC = расход/продажи\n"
        f"🕐 Последняя продажа: {last_s}\n\n"
        "<i>LTV пока = 1 покупка (разовый продукт). Следим за повторными и пакетами.</i>"
    )


# ---------- учёт оплат (простой файл; для MVP достаточно) ----------
def _paid_set():
    try:
        return set(x.strip() for x in open(PAID_FILE, encoding="utf-8") if x.strip())
    except FileNotFoundError:
        return set()


def _mark_paid(order_id):
    with open(PAID_FILE, "a", encoding="utf-8") as f:
        f.write(order_id + "\n")


def is_paid(order_id: str) -> bool:
    return bool(order_id) and order_id in _paid_set()


# ---------- NOWPayments ----------
PAY_COINS = {"usdttrc20": "USDT (TRON)", "usdcmatic": "USDC (Polygon)"}  # монеты клиентских кнопок


def np_create_invoice(order_id: str, coin: str = "") -> str:
    """Создаёт счёт на $PRICE_USD, возвращает ссылку на оплату. Пусто, если не настроено.
    coin — фикс-монета из PAY_COINS (кнопка → чистый экран одной монеты, без списка);
    иначе берётся PAY_CURRENCY (env) либо открытый выбор клиентом."""
    if not NP_API_KEY:
        return ""
    payload = {
        "price_amount": PRICE_USD, "price_currency": "usd",
        "order_id": order_id, "order_description": "isitalpha — Full Strategy Report",
        "success_url": f"{SITE_URL}/validate?paid={order_id}",
        "cancel_url": f"{SITE_URL}/validate",
        "ipn_callback_url": f"{SITE_URL}/api/ipn",
    }
    cur = coin if coin in PAY_COINS else PAY_CURRENCY   # кнопка форсит монету; иначе env/открытый выбор
    if cur:
        payload["pay_currency"] = cur
    try:
        req = urllib.request.Request(
            "https://api.nowpayments.io/v1/invoice",
            data=json.dumps(payload).encode(),
            headers={"x-api-key": NP_API_KEY, "Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (isitalpha)"},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        return d.get("invoice_url", "")
    except Exception:
        return ""


def np_ipn_valid(raw: bytes, sig: str) -> bool:
    """Проверяет подпись вебхука NOWPayments (HMAC-SHA512 отсортированного JSON)."""
    if not (NP_IPN_SECRET and sig):
        return False
    try:
        data = json.loads(raw)
    except Exception:
        return False
    base = json.dumps(data, separators=(",", ":"), sort_keys=True)
    # NOWPayments (PHP json_encode) экранирует слэши как \/, Python — нет. Пробуем оба варианта.
    for candidate in (base, base.replace("/", "\\/")):
        mac = hmac.new(NP_IPN_SECRET.encode(), candidate.encode(), hashlib.sha512).hexdigest()
        if hmac.compare_digest(mac, sig):
            return True
    return False


def gate(result: dict, paid: bool) -> dict:
    """Не оплачено → только вердикт-слово + флаг locked + цена."""
    if paid or result.get("verdict") == "INSUFFICIENT":
        return result
    g = {k: result[k] for k in FREE_FIELDS if k in result}
    g["locked"] = True
    g["price_usd"] = PRICE_USD
    g["pay_ready"] = bool(NP_API_KEY)
    return g


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, name):
        path = os.path.join(WEB, name)
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        with open(path, "rb") as f:
            self._send(200, f.read(), _CT.get(os.path.splitext(name)[1], "application/octet-stream"))

    def _raw(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(n)
        except Exception:
            return b""

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/report":
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            if REPORT_KEY and qs.get("key", [""])[0] != REPORT_KEY:
                return self._send(403, {"error": "forbidden"})
            rep = stats_report()
            if qs.get("send", [""])[0] == "1":
                tg_send(rep)
            return self._send(200, {"report": rep, "metrics": _metrics()})
        if p in ("/", "/index.html"):
            return self._file("landing.html")
        if p == "/validate":
            return self._file("validate.html")
        if p == "/report":
            return self._file("report.html")
        if p in ("/learn", "/learn/"):
            return self._file("learn/index.html")
        if p.startswith("/learn/"):
            slug = "".join(c for c in p[7:].strip("/") if c.isalnum() or c == "-")
            if slug and os.path.isfile(os.path.join(WEB, "learn", slug + ".html")):
                return self._file("learn/" + slug + ".html")
        safe = os.path.normpath(p).lstrip("/")
        if safe and os.path.isfile(os.path.join(WEB, safe)):
            return self._file(safe)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/validate":
            try:
                body = json.loads(self._raw() or b"{}")
            except Exception:
                return self._send(400, {"error": "bad request"})
            rets = parse_returns_csv(body.get("returns", ""))
            n_trials = int(body.get("n_trials", 10) or 10)
            order = str(body.get("order", "")).strip()
            paid = is_paid(order)
            result = validate(rets, n_trials=n_trials)
            # считаем попытку (лид) только на СВЕЖий вердикт, не на повторный опрос оплаченного заказа
            if result.get("verdict") != "INSUFFICIENT" and not order:
                _bump_attempt()
            return self._send(200, gate(result, paid))

        if self.path == "/api/checkout":
            try:
                cbody = json.loads(self._raw() or b"{}")
            except Exception:
                cbody = {}
            coin = str(cbody.get("coin", "")).strip().lower()   # usdttrc20 / usdcmatic от кнопки, либо пусто
            order_id = "isa_" + _secrets.token_hex(8)
            url = np_create_invoice(order_id, coin)
            if not url:
                return self._send(200, {"ok": False, "reason": "payment_not_configured"})
            return self._send(200, {"ok": True, "order": order_id, "invoice_url": url})

        if self.path == "/api/unlock":
            try:
                body = json.loads(self._raw() or b"{}")
            except Exception:
                body = {}
            return self._send(200, {"ok": is_paid(str(body.get("order", "")).strip())})

        if self.path == "/api/ipn":
            raw = self._raw()
            sig = self.headers.get("x-nowpayments-sig", "")
            if not np_ipn_valid(raw, sig):
                return self._send(403, {"ok": False})
            try:
                d = json.loads(raw)
            except Exception:
                return self._send(400, {"ok": False})
            status = d.get("payment_status")
            order = str(d.get("order_id", "")).strip()
            if status in ("finished", "confirmed") and order:
                _mark_paid(order)
                m = _record_sale(order)          # None если дубль вебхука
                if m is not None:
                    tg_send(f"💰 <b>Продажа!</b> ${PRICE_USD} · заказ {order}\n"
                            f"Всего продаж: <b>{m['sales']}</b> · выручка <b>${m['revenue']}</b>")
                try:
                    pay_amt, actual = d.get("pay_amount"), d.get("actually_paid")
                    if actual and pay_amt and float(actual) > float(pay_amt) * 1.02:
                        tg_send(f"⚠️ Переплата по {order}: пришло {actual}, ждали {pay_amt}. Возможен возврат излишка.")
                except Exception:
                    pass
            elif status == "partially_paid" and order:
                tg_send(f"⚠️ Недоплата по {order} (partially_paid) — отчёт не открыт. Клиент мог ошибиться суммой.")
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def main(port=8423):
    print("Honest Validator app: http://127.0.0.1:%d  (/validate, /report)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8423)
