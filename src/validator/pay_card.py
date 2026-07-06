"""Оплата КАРТОЙ через Merchant-of-Record (Lemon Squeezy) — самодостаточный модуль.

Рядом с крипто-оплатой (NOWPayments). Config-driven: секреты в bootstrap.env, в коде их нет.
Вшивка в app.py (кнопка + роут /api/pay/callback) — по docs/PAY_CARD_INTEGRATION_SPEC.md.

Безопасность: вебхук проверяется HMAC-SHA256 по PAY_WEBHOOK_SECRET (защита от подделки).
Единый путь разблокировки: карта и крипта ведут к одному is_paid — вторую логику доступа НЕ плодим.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import urllib.parse
from typing import Dict, Optional

# карта плана -> env-переменная со ссылкой чекаута
_LINK_ENV = {
    "report": "PAY_LINK_REPORT",     # $15
    "regime": "PAY_LINK_REGIME",     # $19 (report + Signal-Guard)
    "monitor": "PAY_LINK_MONITOR",   # $9/мес
}


def card_enabled() -> bool:
    """Кнопка карты показывается только если включено И есть хоть одна ссылка (грациозно)."""
    return os.environ.get("PAY_CARD_ENABLED", "0") == "1" and bool(checkout_links())


def checkout_links() -> Dict[str, str]:
    """{plan: url} только для заданных в окружении (пустые не показываем)."""
    out: Dict[str, str] = {}
    for plan, env in _LINK_ENV.items():
        url = os.environ.get(env, "").strip()
        if url:
            out[plan] = url
    return out


def checkout_link(plan: str) -> Optional[str]:
    return checkout_links().get(plan)


def checkout_url_for(plan: str, order_id: str, site_url: str = "") -> Optional[str]:
    """Ссылка чекаута MoR + наш order_id (прокинется в вебхук как custom_data) + success-redirect
    обратно на /validate?paid=<order_id> для авто-разблокировки. Единый order с крипто-путём."""
    base = checkout_link(plan)
    if not base:
        return None
    params = {"checkout[custom][order_id]": order_id}
    if site_url:
        params["checkout[success_url]"] = f"{site_url.rstrip('/')}/validate?paid={order_id}"
    sep = "&" if "?" in base else "?"
    return base + sep + urllib.parse.urlencode(params)


def verify_signature(raw_body: bytes, signature_header: str, secret: str = "") -> bool:
    """HMAC-SHA256(raw_body, secret) hex == X-Signature. Постоянное время сравнения."""
    secret = secret or os.environ.get("PAY_WEBHOOK_SECRET", "")
    if not secret or not signature_header:
        return False
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # заголовок может прийти как "sha256=..." или голым хексом — нормализуем
    sig = signature_header.strip()
    if "=" in sig:
        sig = sig.split("=", 1)[1]
    try:
        return hmac.compare_digest(digest, sig)
    except Exception:
        return False


_PAID_STATUSES = {"paid", "active", "completed", "success", "successful"}


def normalize_event(payload: Dict) -> Dict:
    """Из вебхука MoR извлечь {paid, status, order_id, email, plan}. Устойчиво к вариациям схемы.

    Lemon Squeezy: meta.event_name (order_created / subscription_payment_success),
    data.attributes.{status,user_email,identifier}, meta.custom_data.order_id (если прокинем)."""
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    attrs = data.get("attributes", {}) if isinstance(data, dict) else {}
    custom = meta.get("custom_data", {}) if isinstance(meta, dict) else {}

    event = str(meta.get("event_name", "")).lower()
    status = str(attrs.get("status", "")).lower()
    email = (attrs.get("user_email") or attrs.get("email")
             or custom.get("email") or "").strip().lower()
    order_id = str(custom.get("order_id") or attrs.get("identifier")
                   or data.get("id") or "").strip()

    paid = (status in _PAID_STATUSES) or event in {
        "order_created", "subscription_payment_success", "order_paid"}
    # order_created сам по себе не всегда оплачен — требуем непустой статус ЛИБО явное success-событие
    if event == "order_created" and status and status not in _PAID_STATUSES:
        paid = False

    return {"paid": bool(paid), "status": status, "event": event,
            "order_id": order_id, "email": email}
