#!/bin/bash
# Poly Smart Radar - Deployment Script
# Usage: sudo ./deploy/setup.sh your-domain.com

set -e

DOMAIN=${1:-"your-domain.com"}
PROJECT_DIR="/home/user/poly-smart-radar"
USER="user"

echo "=== Poly Smart Radar Deployment ==="
echo "Domain: $DOMAIN"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# 1. Install system dependencies
echo "[1/8] Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx curl

# Install Node.js 20.x LTS
if ! command -v node &> /dev/null; then
    echo "Installing Node.js 20.x..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

# 2. Create Python virtual environment
echo "[2/8] Setting up Python environment..."
cd "$PROJECT_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

# 3. Build frontend
echo "[3/8] Building frontend..."
cd "$PROJECT_DIR/frontend"
npm install
npm run build

# 4. Configure Nginx
echo "[4/8] Configuring Nginx..."
sed "s/your-domain.com/$DOMAIN/g" "$PROJECT_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/poly-radar
ln -sf /etc/nginx/sites-available/poly-radar /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 5. Get SSL certificate
echo "[5/8] Obtaining SSL certificate..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@$DOMAIN" || {
    echo "WARNING: Certbot failed. Run manually after DNS is configured:"
    echo "  certbot --nginx -d $DOMAIN"
}

# 6. Install systemd services
echo "[6/8] Installing systemd services..."
cp "$PROJECT_DIR/deploy/poly-radar-api.service" /etc/systemd/system/
cp "$PROJECT_DIR/deploy/poly-radar-bot.service" /etc/systemd/system/
cp "$PROJECT_DIR/deploy/poly-radar-scanner.service" /etc/systemd/system/
systemctl daemon-reload

# 7. Create .env if not exists
echo "[7/8] Checking .env file..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << EOF
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
MINIAPP_URL=https://$DOMAIN
EOF
    echo "Created .env file. Please edit with your actual values!"
fi

# 8. Set permissions
echo "[8/8] Setting permissions..."
chown -R $USER:$USER "$PROJECT_DIR"
chmod 600 "$PROJECT_DIR/.env"

# Start services
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit .env file with your Telegram bot token:"
echo "   nano $PROJECT_DIR/.env"
echo ""
echo "2. Start services:"
echo "   systemctl start poly-radar-api"
echo "   systemctl start poly-radar-bot"
echo "   systemctl start poly-radar-scanner"
echo ""
echo "3. Enable services on boot:"
echo "   systemctl enable poly-radar-api poly-radar-bot poly-radar-scanner"
echo ""
echo "4. Check status:"
echo "   systemctl status poly-radar-api poly-radar-bot poly-radar-scanner"
echo ""
echo "5. View logs:"
echo "   journalctl -u poly-radar-api -f"
echo ""
