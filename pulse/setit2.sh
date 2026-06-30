#!/usr/bin/env bash
# Пошаговый ввод секретов Pulse: сначала ТОКЕН (сохраняем), потом КЛЮЧ.
# С проверкой длины — сразу видно, долетел ли секрет. Запуск: bash pulse/setit2.sh
mkdir -p /opt/pulse

echo ""
echo "=========== ШАГ 1: ТОКЕН бота ==========="
echo ">>> Кликни по чёрному полю, набери ТОКЕН (от BotFather) и нажми Enter:"
read -r TOK
if [ ${#TOK} -lt 20 ]; then
  echo "!!! Токен слишком короткий: ${#TOK} символов. Видимо, не долетел (фокус)."
  echo "!!! Ничего не сохранил. Запусти заново: bash pulse/setit2.sh"
  exit 1
fi
printf 'PULSE_TG_TOKEN=%s\nANTHROPIC_API_KEY=\nOWNER_CHAT_ID=\n' "$TOK" > /opt/pulse/bootstrap.env
chmod 600 /opt/pulse/bootstrap.env
echo "+++ ТОКЕН СОХРАНЁН. Длина: ${#TOK} символов (норма ~46). Если ~46 — отлично."

echo ""
echo "=========== ШАГ 2: КЛЮЧ Anthropic ==========="
echo ">>> Кликни по чёрному полю, набери КЛЮЧ (sk-ant-...) и нажми Enter:"
read -r KEY
if [ ${#KEY} -lt 40 ]; then
  echo "!!! Ключ слишком короткий: ${#KEY} символов. Видимо, не долетел."
  echo "!!! Токен уже сохранён. Перезапусти и введи оба заново: bash pulse/setit2.sh"
  exit 1
fi
sed -i "s#^ANTHROPIC_API_KEY=.*#ANTHROPIC_API_KEY=${KEY}#" /opt/pulse/bootstrap.env
echo "+++ КЛЮЧ СОХРАНЁН. Длина: ${#KEY} символов (норма ~108)."

echo ""
echo "=========== ЗАПУСК БОТА ==========="
systemctl daemon-reload
systemctl enable --now pulse
sleep 2
echo -n "Статус pulse: "
systemctl is-active pulse
echo ""
echo "=== Если 'active' — РАБОТАЕТ! Напиши боту в Telegram 'привет' — он ответит твоим chat_id. ==="
echo "=== Если 'failed' — напиши мне, гляну лог: tail -n 20 /var/log/pulse.log ==="
