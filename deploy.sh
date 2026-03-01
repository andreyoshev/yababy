#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="yababy"
PROJECT_DIR="$(pwd)"
USER="$(whoami)"

echo "Deploy config:"
echo "  User:    ${USER}"
echo "  Dir:     ${PROJECT_DIR}"
echo "  Service: ${SERVICE_NAME}"
echo ""
read -rp "Continue? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

echo "-- Creating venv and installing dependencies..."
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "-- Generating and installing systemd service..."
sed "s|{{USER}}|${USER}|g; s|{{PROJECT_DIR}}|${PROJECT_DIR}|g" \
    yababy.service > "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "-- Service status:"
systemctl status "$SERVICE_NAME" --no-pager -l
echo "-- Done! https://yababy.oshev.me/alice/webhook is ready."
