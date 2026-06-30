#!/usr/bin/env bash
# Вписать OWNER_CHAT_ID (твой номер от бота) — бот станет личным + заработает Claude.
# Запуск: bash pulse/setchat.sh
echo ""
echo ">>> Набери свой chat_id (ЧИСЛО, что прислал бот) и нажми Enter:"
read -r CID
if ! [[ "$CID" =~ ^-?[0-9]+$ ]]; then
  echo "!!! Это должно быть только число (например 123456789). Запусти заново."
  exit 1
fi
sed -i "s#^OWNER_CHAT_ID=.*#OWNER_CHAT_ID=${CID}#" /opt/pulse/bootstrap.env
echo "+++ OWNER_CHAT_ID = ${CID} сохранён. Бот теперь отвечает только тебе."
systemctl restart pulse
sleep 2
echo -n "Статус pulse: "
systemctl is-active pulse
echo "=== ГОТОВО! Напиши боту любой вопрос — он ответит по-умному (через Claude). ==="
echo "=== Если ответит осмысленно — ключ Anthropic тоже верный, мост полностью готов! ==="
