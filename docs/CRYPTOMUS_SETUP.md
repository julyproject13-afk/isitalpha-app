# 💳 ЗАПУСК ОПЛАТЫ КАРТОЙ через Cryptomus (быстрый тест, мерчант РФ)

Код вшит и протестирован (config-gated). Активируется, когда впишешь ключи. Партнёр Дима/Lemon Squeezy — позже.

## Шаг 1 — аккаунт Cryptomus (владелец, ~20 мин)
По инструкции Девина: cryptomus.com → Sign Up → Merchant → KYC (паспорт+селфи) → верификация.

## Шаг 2 — взять ключи (dashboard)
- Settings/API → **Merchant ID** и **Payment API Key**.
- (Опц.) Whitelist нашего домена; их IP вебхука 91.227.144.54 — на будущее.

## Шаг 3 — вписать в СЕРВЕРНЫЙ /opt/isitalpha/bootstrap.env (VNC, не в чат)
```
CRYPTOMUS_MERCHANT_ID=<merchant id>
CRYPTOMUS_API_KEY=<payment api key>
```
Рестарт: systemctl restart isitalpha (или pkill -f scripts/app.py). **Кода нового деплоить не нужно, если ветка pay-cryptomus уже в main+запушена** — тогда только env+рестарт.

## Шаг 4 — как это работает (авто)
Кнопка «Pay $15 · Card» появляется сама (pay_card_ready=True при ключах). Клиент жмёт → сервер создаёт
Cryptomus-invoice с нашим order_id → редирект на страницу Cryptomus (клиент платит КАРТОЙ) → Cryptomus шлёт
вебхук на /api/pay/cryptomus → проверка md5-подписи → отчёт разблокируется сам (_mark_paid) → USDT на кошелёк.

## Шаг 5 — тест
Открой /validate → Load example → «Pay $15 · Card» → оплати тестово → отчёт должен открыться + придёт
Telegram «💳 Продажа (карта/Cryptomus)!». Проверь приход USDT в Cryptomus dashboard → вывод на кошелёк.

## Комиссия/лимиты (Девин): ~2.9%+€0.25; без KYC €1k/мес, с KYC €10k/мес. Крипту декларировать (13% НДФЛ).
## Слэш-эскейп подписи: учтён (как чинили NOWPayments). Если вебхук вдруг не проходит (403) — скажи, донастрою.
