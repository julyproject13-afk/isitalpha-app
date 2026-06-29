#!/usr/bin/env bash
# Запускается НА сервере (Ubuntu 24.04). Ставит nginx+certbot, systemd-сервис isitalpha,
# reverse-proxy и SSL. Идемпотентно — можно гонять повторно.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
EMAIL="julyproject13@gmail.com"
APP_DIR="/opt/isitalpha"
PORT=8423

echo "== apt: nginx + certbot =="
apt-get update -y
apt-get install -y nginx certbot python3-certbot-nginx rsync

echo "== systemd-сервис isitalpha =="
cat >/etc/systemd/system/isitalpha.service <<EOF
[Unit]
Description=isitalpha validator
After=network.target
[Service]
WorkingDirectory=${APP_DIR}
Environment=PYTHONPATH=${APP_DIR}/src
ExecStart=/usr/bin/python3 ${APP_DIR}/scripts/app.py ${PORT}
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable isitalpha
systemctl restart isitalpha

echo "== nginx reverse-proxy =="
cat >/etc/nginx/sites-available/isitalpha <<EOF
server {
    listen 80;
    server_name isitalpha.com www.isitalpha.com;
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ln -sf /etc/nginx/sites-available/isitalpha /etc/nginx/sites-enabled/isitalpha
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "== проверка локально =="
sleep 2
curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/" && echo "  приложение отвечает ✅" || echo "  ⚠️ приложение не ответило — проверь journalctl -u isitalpha"

echo "== SSL (Let's Encrypt) =="
certbot --nginx -d isitalpha.com -d www.isitalpha.com \
    --non-interactive --agree-tos -m "${EMAIL}" --redirect \
    && echo "  SSL выдан ✅" \
    || echo "  ⚠️ SSL не выдался (вероятно DNS ещё не распространился) — повтори: certbot --nginx -d isitalpha.com -d www.isitalpha.com --agree-tos -m ${EMAIL} --redirect"

echo "== ГОТОВО =="
echo "http://isitalpha.com  (после SSL → https://isitalpha.com)"
