#!/usr/bin/env bash
# Второй мост Pulse-EVO для golden-mutation (@evolutionShield_bot) на сервере.
# Переиспользует Anthropic-ключ из /opt/pulse/bootstrap.env, chat_id известен.
# Спрашивает ТОЛЬКО токен бота. Запуск: bash pulse/evo_setup.sh
set -e

SRC=/opt/isitalpha/pulse
DST=/opt/pulse-evo
mkdir -p "$DST"
cp "$SRC/pulse.py" "$DST/pulse.py"
cp "$SRC/PULSE_CONTEXT_EVO.md" "$DST/PULSE_CONTEXT.md"

# переиспользуем ключ Anthropic с уже работающего моста — НЕ вводим руками
KEY=$(grep -E '^ANTHROPIC_API_KEY=' /opt/pulse/bootstrap.env 2>/dev/null | head -1 | cut -d= -f2-)
if [ -z "$KEY" ]; then
  echo "!!! Не нашёл ANTHROPIC_API_KEY в /opt/pulse/bootstrap.env. Стоп."
  exit 1
fi
echo "+++ Ключ Anthropic переиспользован (длина ${#KEY}) — вводить не надо."

echo ""
echo ">>> Кликни по чёрному полю, набери ТОКЕН бота @evolutionShield_bot и нажми Enter:"
read -r TOK
if [ ${#TOK} -lt 20 ]; then
  echo "!!! Токен короткий (${#TOK} симв) — видимо не долетел. Запусти заново."
  exit 1
fi

printf 'PULSE_TG_TOKEN=%s\nANTHROPIC_API_KEY=%s\nOWNER_CHAT_ID=694216790\n' "$TOK" "$KEY" > "$DST/bootstrap.env"
chmod 600 "$DST/bootstrap.env"
echo "+++ Секреты записаны (токен ${#TOK}, ключ переиспользован, chat_id=694216790)."

cat > /etc/systemd/system/pulse-evo.service <<'EOF'
[Unit]
Description=Pulse-EVO — мост golden-mutation (Telegram <-> Claude) 24/7
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/pulse-evo
ExecStart=/usr/bin/python3 /opt/pulse-evo/pulse.py
Restart=always
RestartSec=3
StandardOutput=append:/var/log/pulse-evo.log
StandardError=append:/var/log/pulse-evo.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pulse-evo
sleep 2
echo ""
echo -n "Статус pulse-evo: "
systemctl is-active pulse-evo
echo ""
echo "=== ГОТОВО. Напиши боту @evolutionShield_bot 'привет' — он ответит по-умному. ==="
echo "=== ВАЖНО: выключи СТАРЫЙ мост на Маке (launchd), иначе два слушателя одного бота = конфликт! ==="
