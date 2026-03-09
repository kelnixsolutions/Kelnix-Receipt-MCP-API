#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Receipt MCP Server — Update script
# Run this to pull latest code and restart the server
#
# Usage: sudo bash /opt/receipt-mcp/deploy/update.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/receipt-mcp"

echo "Pulling latest code..."
cd "$APP_DIR"
sudo -u mcpserver git pull origin main

echo "Updating dependencies..."
sudo -u mcpserver "$APP_DIR/venv/bin/pip" install -r requirements.txt -q

echo "Restarting server..."
systemctl restart receipt-mcp

echo "Waiting for server to start..."
sleep 2

if systemctl is-active --quiet receipt-mcp; then
    echo "Server is running."
    curl -s http://127.0.0.1:8000/health
    echo ""
else
    echo "ERROR: Server failed to start. Check logs:"
    echo "  journalctl -u receipt-mcp -n 20"
fi
