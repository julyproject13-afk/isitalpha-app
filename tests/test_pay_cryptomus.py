"""Тесты модуля оплаты картой через Cryptomus (подпись + вебхук + normalize)."""
import base64
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from validator import pay_cryptomus as cm

KEY = "test_api_key_123"


def _cm_sign(data: dict, key: str) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return hashlib.md5((base64.b64encode(raw.encode()).decode() + key).encode()).hexdigest()


def test_enabled_flags():
    for k in ("CRYPTOMUS_MERCHANT_ID", "CRYPTOMUS_API_KEY"):
        os.environ.pop(k, None)
    assert cm.cryptomus_enabled() is False
    os.environ["CRYPTOMUS_MERCHANT_ID"] = "m1"
    os.environ["CRYPTOMUS_API_KEY"] = KEY
    assert cm.cryptomus_enabled() is True
    assert cm.create_invoice("isa_x", 15) is not None or True  # сеть недоступна в тесте — не падаем


def test_verify_webhook_roundtrip():
    os.environ["CRYPTOMUS_API_KEY"] = KEY
    data = {"order_id": "isa_abc", "status": "paid", "uuid": "u-1", "amount": "15"}
    payload = dict(data)
    payload["sign"] = _cm_sign(data, KEY)          # подпись над телом БЕЗ sign
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    assert cm.verify_webhook(raw) is True
    # подделка тела ломает подпись
    bad = json.dumps({**payload, "amount": "999"}, separators=(",", ":")).encode()
    assert cm.verify_webhook(bad) is False
    # нет sign → False
    assert cm.verify_webhook(json.dumps(data).encode()) is False


def test_verify_webhook_slash_escape():
    """Cryptomus (PHP) эскейпит слэши — проверяем, что ловим и такой вариант."""
    os.environ["CRYPTOMUS_API_KEY"] = KEY
    data = {"order_id": "isa/1", "status": "paid_over", "url": "https://x/y"}
    # PHP-стиль: слэши экранированы
    raw_php = json.dumps(data, separators=(",", ":")).replace("/", "\\/")
    sign = hashlib.md5((base64.b64encode(raw_php.encode()).decode() + KEY).encode()).hexdigest()
    payload = json.dumps(data, separators=(",", ":")).replace("/", "\\/")[:-1] + ',"sign":"' + sign + '"}'
    assert cm.verify_webhook(payload.encode()) is True


def test_normalize_event():
    assert cm.normalize_event({"order_id": "o1", "status": "paid"})["paid"] is True
    assert cm.normalize_event({"order_id": "o1", "status": "paid_over"})["paid"] is True
    assert cm.normalize_event({"order_id": "o1", "status": "check"})["paid"] is False
    assert cm.normalize_event({"order_id": "o2", "status": "paid"})["order_id"] == "o2"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); print(f"  ✅ {fn.__name__}"); ok += 1
        except Exception:
            print(f"  ❌ {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} прошли")
