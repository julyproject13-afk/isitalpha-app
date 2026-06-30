#!/usr/bin/env bash
# Одноразовый помощник: впиши 2 секрета Pulse и запусти бота — БЕЗ nano.
# Запуск на сервере:   bash /opt/pulse/setit.sh
set -e

mkdir -p /opt/pulse

echo ""
echo ">>> Набери ТОКЕН бота (от @BotFather) и нажми Enter:"
read -r TOK
echo ">>> Набери КЛЮЧ Anthropic (sk-ant-...) и нажми Enter:"
read -r KEY

printf 'PULSE_TG_TOKEN=%s\nANTHROPIC_API_KEY=%s\nOWNER_CHAT_ID=\n' "$TOK" "$KEY" > /opt/pulse/bootstrap.env
chmod 600 /opt/pulse/bootstrap.env

systemctl daemon-reload
systemctl enable --now pulse
sleep 2
echo ""
echo "=== СТАТУС PULSE ==="
systemctl --no-pager status pulse | head -n 12
echo ""
echo "=== ГОТОВО. Теперь напиши боту в Telegram 'привет' — он ответит твоим chat_id. ==="
echo "=== Потом впиши этот номер: nano /opt/pulse/bootstrap.env  (строка OWNER_CHAT_ID=) и: systemctl restart pulse ==="
