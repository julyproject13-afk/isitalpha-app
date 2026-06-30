#!/usr/bin/env bash
# Обновить ТОЛЬКО ключ Anthropic (токен Telegram не трогаем). Запуск: bash pulse/setkey.sh
echo ""
echo ">>> Кликни по чёрному полю, набери КЛЮЧ Anthropic (sk-ant-...) и нажми Enter:"
read -r KEY
if [ ${#KEY} -lt 40 ]; then
  echo "!!! Ключ короткий: ${#KEY} символов. Видимо не долетел. Запусти заново."
  exit 1
fi
sed -i "s#^ANTHROPIC_API_KEY=.*#ANTHROPIC_API_KEY=${KEY}#" /opt/pulse/bootstrap.env
echo "+++ КЛЮЧ обновлён. Длина: ${#KEY} символов (норма ~108). Токен не тронут."
systemctl restart pulse
sleep 2
echo -n "Статус pulse: "
systemctl is-active pulse
echo "=== Напиши боту вопрос — теперь должен ответить по-умному (через Claude)! ==="
