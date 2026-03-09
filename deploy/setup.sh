#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Receipt MCP Server — Hetzner / VPS deploy script
# Run on a fresh Ubuntu 22.04+ server as root (or with sudo)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server/main/deploy/setup.sh | bash
#   — OR —
#   git clone ... && cd Receipt-Accounting-Entry-MCP-Server && sudo bash deploy/setup.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_USER="mcpserver"
APP_DIR="/opt/receipt-mcp"
REPO_URL="https://github.com/TiagoX9/Receipt-Accounting-Entry-MCP-Server.git"
DOMAIN="${DOMAIN:-}"  # set via env or prompted

echo "============================================"
echo "  Receipt MCP Server — Deploy Script"
echo "============================================"

# ── 1. System packages ───────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw curl

# ── 2. Firewall ──────────────────────────────────────────────────────────
echo "[2/7] Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ── 3. Create app user & clone ───────────────────────────────────────────
echo "[3/7] Setting up application..."
id -u "$APP_USER" &>/dev/null || useradd -r -s /bin/false -m -d "$APP_DIR" "$APP_USER"

if [ -d "$APP_DIR/.git" ]; then
    echo "  Repo already exists, pulling latest..."
    cd "$APP_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

# ── 4. Python environment ────────────────────────────────────────────────
echo "[4/7] Setting up Python environment..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r requirements.txt -q
"$APP_DIR/venv/bin/pip" install gunicorn -q

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# ── 5. Environment file ─────────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[5/7] Creating .env file (you MUST edit this)..."
    cat > "$APP_DIR/.env" <<'ENVFILE'
# ─── REQUIRED ───────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-your-key-here

# ─── STRIPE (required for payments) ────────────────────────────────────
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_BASIC_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...

# ─── STRIPE TAX & INVOICES (optional) ──────────────────────────────────
# STRIPE_TAX_ENABLED=true
# STRIPE_COLLECT_ADDRESS=true

# ─── CRYPTO PAYMENTS (optional) ────────────────────────────────────────
# NOWPAYMENTS_API_KEY=
# NOWPAYMENTS_IPN_SECRET=
# CRYPTO_IPN_CALLBACK_URL=https://your-domain.com/billing/crypto_webhook

# ─── ADMIN DASHBOARD ───────────────────────────────────────────────────
ADMIN_KEY=change-this-to-a-long-random-string

# ─── OPTIONAL ───────────────────────────────────────────────────────────
SUPPORT_EMAIL=info@kelnix.org
# REDIS_URL=redis://localhost:6379/0
ENVFILE
    chmod 600 "$APP_DIR/.env"
    chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
    echo ""
    echo "  ⚠  IMPORTANT: Edit $APP_DIR/.env with your actual keys!"
    echo ""
else
    echo "[5/7] .env already exists, skipping..."
fi

# ── 6. Systemd service ──────────────────────────────────────────────────
echo "[6/7] Creating systemd service..."
cat > /etc/systemd/system/receipt-mcp.service <<EOF
[Unit]
Description=Receipt MCP Server
After=network.target

[Service]
Type=exec
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn app:app \\
    --worker-class uvicorn.workers.UvicornWorker \\
    --workers 4 \\
    --bind 127.0.0.1:8000 \\
    --timeout 120 \\
    --access-logfile /var/log/receipt-mcp/access.log \\
    --error-logfile /var/log/receipt-mcp/error.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

mkdir -p /var/log/receipt-mcp
chown "$APP_USER":"$APP_USER" /var/log/receipt-mcp

systemctl daemon-reload
systemctl enable receipt-mcp

# ── 7. Nginx reverse proxy ──────────────────────────────────────────────
echo "[7/7] Configuring nginx..."

# Prompt for domain if not set
if [ -z "$DOMAIN" ]; then
    echo ""
    read -rp "  Enter your domain (e.g. api.kelnix.org): " DOMAIN
fi

cat > /etc/nginx/sites-available/receipt-mcp <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/receipt-mcp /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit your keys:"
echo "     nano $APP_DIR/.env"
echo ""
echo "  2. Point DNS: $DOMAIN → $(curl -s ifconfig.me)"
echo ""
echo "  3. Start the server:"
echo "     systemctl start receipt-mcp"
echo ""
echo "  4. Get free SSL certificate:"
echo "     certbot --nginx -d $DOMAIN"
echo ""
echo "  5. Verify:"
echo "     curl https://$DOMAIN/health"
echo ""
echo "  Useful commands:"
echo "     systemctl status receipt-mcp    # check status"
echo "     journalctl -u receipt-mcp -f    # live logs"
echo "     systemctl restart receipt-mcp   # restart after .env changes"
echo ""
