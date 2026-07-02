#!/usr/bin/env bash
# Включает Telegram-уведомления isitalpha: берёт токен Pulse-бота (не набираем руками),
# вписывает chat_id владельца, рестартит и шлёт тестовую сводку. Запуск: bash deploy/settg.sh
set -u
ENV=/opt/isitalpha/bootstrap.env
PULSE_ENV=/opt/pulse/bootstrap.env
PORT=8423

touch "$ENV"; chmod 600 "$ENV"

TOK=$(grep -E '^PULSE_TG_TOKEN=' "$PULSE_ENV" 2>/dev/null | head -1 | cut -d= -f2-)
if [ -z "${TOK:-}" ]; then
  echo "!!! Не нашёл PULSE_TG_TOKEN в $PULSE_ENV — покажи мне: cat $PULSE_ENV"
  exit 1
fi

# убрать старые строки токена/чата, если были, и вписать свежие
grep -v -E '^(PULSE_TG_TOKEN|OWNER_CHAT_ID)=' "$ENV" > "$ENV.tmp" 2>/dev/null || true
mv "$ENV.tmp" "$ENV" 2>/dev/null || true
printf 'PULSE_TG_TOKEN=%s\nOWNER_CHAT_ID=694216790\n' "$TOK" >> "$ENV"
chmod 600 "$ENV"
echo "+++ Токен вписан (длина ${#TOK}), chat_id=694216790"

systemctl restart isitalpha
sleep 2
echo -n "Статус isitalpha: "; systemctl is-active isitalpha

echo "Шлю тестовую сводку тебе в Telegram..."
if curl -s "http://127.0.0.1:${PORT}/api/report?send=1" >/dev/null; then
  echo "=== ГОТОВО! Проверь Telegram — должна прийти сводка isitalpha. ==="
else
  echo "=== Не смог дёрнуть /api/report — покажи: journalctl -u isitalpha -n 20 --no-pager ==="
fi
