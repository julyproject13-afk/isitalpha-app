#!/usr/bin/env bash
# Запуск НА СЕРВЕРЕ (VNC-консоль Koara):  cd /opt/isitalpha && bash deploy/setpay.sh
# Тянет свежий код (пейволл NOWPayments), спрашивает 2 секрета из Заметок,
# пишет их в bootstrap.env (chmod 600, не в git), рестартит сайт и проверяет оплату.
set -u
APP_DIR="/opt/isitalpha"
ENV="${APP_DIR}/bootstrap.env"
PORT=8423

cd "$APP_DIR" || { echo "!!! Нет каталога $APP_DIR"; exit 1; }

echo "========== 1/4: тяну свежий код с GitHub =========="
if ! git pull; then
  echo "!!! git pull не прошёл. Скопируй вывод и покажи мне."; exit 1
fi

upsert(){ # upsert KEY VALUE в $ENV, не трогая остальные строки
  local k="$1" v="$2"
  touch "$ENV"; chmod 600 "$ENV"
  if grep -q "^${k}=" "$ENV" 2>/dev/null; then
    sed -i "s#^${k}=.*#${k}=${v}#" "$ENV"
  else
    printf '%s=%s\n' "$k" "$v" >> "$ENV"
  fi
}

echo ""
echo "========== 2/4: NP_API_KEY =========="
echo ">>> Кликни по чёрному полю, вставь API key (из Заметок 'isitalpha ключи') и нажми Enter:"
read -r NPK
if [ ${#NPK} -lt 5 ]; then
  echo "!!! Слишком коротко (${#NPK} симв.) — ключ не долетел (фокус/вставка). Ничего не менял. Перезапусти."; exit 1
fi
upsert NP_API_KEY "$NPK"
echo "+++ API key записан. Длина: ${#NPK} символов."

echo ""
echo "========== 3/4: NP_IPN_SECRET =========="
echo ">>> Вставь IPN secret (из тех же Заметок) и нажми Enter:"
read -r NPI
if [ ${#NPI} -lt 5 ]; then
  echo "!!! Слишком коротко (${#NPI} симв.) — не долетел. API key уже записан, добей IPN: перезапусти."; exit 1
fi
upsert NP_IPN_SECRET "$NPI"
echo "+++ IPN secret записан. Длина: ${#NPI} символов."

upsert SITE_URL "https://isitalpha.com"

echo ""
echo "========== 4/4: рестарт сайта + проверка =========="
systemctl restart isitalpha
sleep 2
echo -n "Статус isitalpha: "; systemctl is-active isitalpha
echo "Проверка приёма оплаты (создаю тестовый счёт):"
RESP=$(curl -s -X POST "http://127.0.0.1:${PORT}/api/checkout" -H 'Content-Type: application/json' -d '{}')
echo "  $RESP"
echo ""
if echo "$RESP" | grep -q "invoice_url"; then
  echo "=== ГОТОВО! Оплата ЖИВАЯ — сайт создал реальный счёт NOWPayments. ==="
  echo "=== Иди на isitalpha.com/validate, введи числа, жми Unlock \$9 — проверим оплату вживую. ==="
else
  echo "=== Счёт не создался (ключ не подхватился или неверный). Покажи мне строку выше — разберёмся. ==="
  echo "=== Лог: journalctl -u isitalpha -n 30 --no-pager ==="
fi
