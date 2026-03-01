#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="yababy"
PORT=7433
DOMAIN="yababy.oshev.me"
PROJECT_DIR="$(pwd)"
USER="$(whoami)"

echo "Deploy config:"
echo "  User:    ${USER}"
echo "  Dir:     ${PROJECT_DIR}"
echo "  Service: ${SERVICE_NAME}"
echo "  Port:    ${PORT}"
echo "  Domain:  ${DOMAIN}"
echo ""
read -rp "Continue? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

echo "-- Creating venv and installing dependencies..."
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "-- Installing systemd service..."
sed "s|{{USER}}|${USER}|g; s|{{PROJECT_DIR}}|${PROJECT_DIR}|g" \
    yababy.service > "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "-- Configuring nginx..."
cat > "/etc/nginx/sites-available/${SERVICE_NAME}" <<NGINX
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
NGINX
ln -sf "/etc/nginx/sites-available/${SERVICE_NAME}" /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

echo "-- Status:"
systemctl status "$SERVICE_NAME" --no-pager -l
echo "-- Done! https://${DOMAIN}/alice/webhook is ready."
