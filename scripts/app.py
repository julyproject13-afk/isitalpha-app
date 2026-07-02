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
PRICE_USD = int(os.environ.get("PRICE_USD", "12"))   # $12: выше минимума NOWPayments для USDT-TRC20 (~$10.74). Меняется через bootstrap.env без правки кода.

FREE_FIELDS = ("verdict", "headline", "n", "reason")


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
def np_create_invoice(order_id: str) -> str:
    """Создаёт счёт на $9, возвращает ссылку на страницу оплаты. Пусто, если не настроено."""
    if not NP_API_KEY:
        return ""
    payload = {
        "price_amount": PRICE_USD, "price_currency": "usd", "pay_currency": "usdttrc20",
        "order_id": order_id, "order_description": "isitalpha — Full Strategy Report",
        "success_url": f"{SITE_URL}/validate?paid={order_id}",
        "cancel_url": f"{SITE_URL}/validate",
        "ipn_callback_url": f"{SITE_URL}/api/ipn",
    }
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
        if p in ("/", "/index.html"):
            return self._file("landing.html")
        if p == "/validate":
            return self._file("validate.html")
        if p == "/report":
            return self._file("report.html")
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
            paid = is_paid(str(body.get("order", "")).strip())
            return self._send(200, gate(validate(rets, n_trials=n_trials), paid))

        if self.path == "/api/checkout":
            order_id = "isa_" + _secrets.token_hex(8)
            url = np_create_invoice(order_id)
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
            if d.get("payment_status") in ("finished", "confirmed") and d.get("order_id"):
                _mark_paid(str(d["order_id"]))
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def main(port=8423):
    print("Honest Validator app: http://127.0.0.1:%d  (/validate, /report)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8423)
