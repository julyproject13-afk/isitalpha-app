"""Оплата КАРТОЙ через Cryptomus (клиент платит картой/Apple Pay → мерчант получает USDT).

Быстрый reputable вариант для теста воронки/юнит-экономики (мерчант в РФ, Cryptomus RF-доступен).
Позже, когда партнёр в Грузии — переключимся на Lemon Squeezy (pay_card.py). Оба живут рядом.

API (doc.cryptomus.com):
  create:  POST https://api.cryptomus.com/v1/payment, headers merchant + sign
           sign = md5( base64(json_body) + API_KEY )     ← над ТОЧНОЙ строкой тела
           body: amount(str), currency, order_id, url_callback, url_return, url_success
           resp: {"state":0,"result":{"url":<страница оплаты>, "uuid":..., ...}}
  webhook: поле sign = md5( base64(json_body_без_sign) + API_KEY ); статусы paid/paid_over = оплачено.
           ⚠️ PHP эскейпит слэши (\/) — при пересборке проверяем ОБА варианта (как чинили NOWPayments IPN).

Секреты (CRYPTOMUS_MERCHANT_ID, CRYPTOMUS_API_KEY) — только в bootstrap.env, в коде их нет.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import urllib.request
from typing import Dict, Optional

_API = "https://api.cryptomus.com/v1/payment"
_PAID = {"paid", "paid_over"}


def _merchant() -> str:
    return os.environ.get("CRYPTOMUS_MERCHANT_ID", "").strip()


def _key() -> str:
    return os.environ.get("CRYPTOMUS_API_KEY", "").strip()


def cryptomus_enabled() -> bool:
    return bool(_merchant() and _key())


def _sign(body_str: str) -> str:
    """md5( base64(тело) + api_key ) — как для запроса, так и для проверки вебхука."""
    b64 = base64.b64encode(body_str.encode("utf-8")).decode("ascii")
    return hashlib.md5((b64 + _key()).encode("utf-8")).hexdigest()


def create_invoice(order_id: str, amount, currency: str = "USD",
                   callback_url: str = "", return_url: str = "", success_url: str = "") -> Optional[str]:
    """Создать платёж → вернуть URL страницы оплаты (клиент платит там картой). None при ошибке."""
    if not cryptomus_enabled():
        return None
    body: Dict[str, str] = {"amount": str(amount), "currency": currency, "order_id": order_id}
    if callback_url:
        body["url_callback"] = callback_url
    if return_url:
        body["url_return"] = return_url
    if success_url:
        body["url_success"] = success_url
    raw = json.dumps(body, separators=(",", ":"))       # подпись над ЭТОЙ же строкой
    req = urllib.request.Request(
        _API, data=raw.encode("utf-8"),
        headers={"merchant": _merchant(), "sign": _sign(raw),
                 "Content-Type": "application/json",
                 # Cloudflare режет дефолтный python-urllib UA (урок NOWPayments) → браузерный UA
                 "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            d = json.loads(resp.read())
        return (d.get("result") or {}).get("url")
    except Exception:
        return None


def verify_webhook(raw_body: bytes) -> bool:
    """Проверка подписи вебхука. Пересобираем тело без sign, сверяем md5(base64(...)+key).
    Пробуем и слэш-эскейп (PHP), и без (как чинили NOWPayments)."""
    if not _key():
        return False
    try:
        data = json.loads(raw_body)
    except Exception:
        return False
    got = str(data.pop("sign", "") or "")
    if not got:
        return False
    base = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    for variant in (base, base.replace("/", "\\/"),
                    json.dumps(data, separators=(",", ":"))):     # ascii-вариант тоже
        if hmac.compare_digest(_sign(variant), got):
            return True
    return False


def normalize_event(payload: Dict) -> Dict:
    """→ {paid, status, order_id, uuid}. Статусы paid/paid_over = оплачено."""
    status = str(payload.get("status", "")).strip().lower()
    return {"paid": status in _PAID, "status": status,
            "order_id": str(payload.get("order_id", "")).strip(),
            "uuid": str(payload.get("uuid", "")).strip()}
