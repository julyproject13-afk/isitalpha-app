#!/usr/bin/env bash
# Обновить ТОЛЬКО токен Telegram (ключ Anthropic не трогаем). Запуск: bash pulse/settoken.sh
echo ""
echo ">>> Кликни по чёрному полю, набери ТОКЕН (правильный!) и нажми Enter:"
read -r TOK
if [ ${#TOK} -lt 20 ]; then
  echo "!!! Токен короткий: ${#TOK} символов. Видимо не долетел. Запусти заново."
  exit 1
fi
sed -i "s#^PULSE_TG_TOKEN=.*#PULSE_TG_TOKEN=${TOK}#" /opt/pulse/bootstrap.env
echo "+++ ТОКЕН обновлён. Длина: ${#TOK} символов (норма ~46). Ключ Anthropic не тронут."
systemctl restart pulse
sleep 2
echo -n "Статус pulse: "
systemctl is-active pulse
echo "=== Теперь напиши боту в Telegram 'привет' — он ответит твоим chat_id. ==="
