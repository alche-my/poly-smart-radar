# Deployment Guide

## Quick Start

```bash
# On your VPS
cd /home/user/poly-smart-radar
git pull

# Run deployment script
sudo ./deploy/setup.sh your-domain.com
```

## Manual Deployment

### 1. Install Dependencies

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip nginx certbot python3-certbot-nginx nodejs npm
```

### 2. Python Environment

```bash
cd /home/user/poly-smart-radar
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Build Frontend

```bash
cd frontend
npm install
npm run build
```

### 4. Configure Environment

```bash
# Create .env file
cat > .env << EOF
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
MINIAPP_URL=https://your-domain.com
EOF

chmod 600 .env
```

### 5. Nginx Setup

```bash
# Copy and edit nginx config
sudo cp deploy/nginx.conf /etc/nginx/sites-available/poly-radar
sudo sed -i 's/your-domain.com/YOUR_ACTUAL_DOMAIN/g' /etc/nginx/sites-available/poly-radar
sudo ln -s /etc/nginx/sites-available/poly-radar /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 6. SSL Certificate

```bash
sudo certbot --nginx -d your-domain.com
```

### 7. Systemd Services

```bash
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Start services
sudo systemctl start poly-radar-api
sudo systemctl start poly-radar-bot
sudo systemctl start poly-radar-scanner

# Enable on boot
sudo systemctl enable poly-radar-api poly-radar-bot poly-radar-scanner
```

## Service Management

```bash
# Check status
sudo systemctl status poly-radar-api
sudo systemctl status poly-radar-bot
sudo systemctl status poly-radar-scanner

# View logs
sudo journalctl -u poly-radar-api -f
sudo journalctl -u poly-radar-bot -f
sudo journalctl -u poly-radar-scanner -f

# Restart
sudo systemctl restart poly-radar-api
```

## Architecture

```
                    ┌──────────────┐
                    │   Internet   │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │    Nginx     │ :443 (HTTPS)
                    │  + SSL/TLS   │
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼─────┐   ┌──────▼─────┐   ┌──────▼──────┐
    │  /api/*   │   │     /*     │   │  Bot API    │
    │  FastAPI  │   │   Static   │   │  Telegram   │
    │  :8000    │   │  Frontend  │   │             │
    └─────┬─────┘   └────────────┘   └──────┬──────┘
          │                                  │
          └──────────────┬───────────────────┘
                         │
                  ┌──────▼──────┐
                  │   SQLite    │
                  │  radar.db   │
                  └─────────────┘
```

## Ports

| Service | Port | Access |
|---------|------|--------|
| Nginx HTTP | 80 | Public (redirects to HTTPS) |
| Nginx HTTPS | 443 | Public |
| FastAPI | 8000 | localhost only |

## Troubleshooting

### API not responding
```bash
# Check if API is running
curl http://localhost:8000/api/health

# Check logs
sudo journalctl -u poly-radar-api --since "10 minutes ago"
```

### Bot not responding
```bash
# Check logs
sudo journalctl -u poly-radar-bot --since "10 minutes ago"

# Verify bot token
grep TELEGRAM_BOT_TOKEN .env
```

### SSL certificate issues
```bash
# Renew certificate
sudo certbot renew

# Check certificate
sudo certbot certificates
```
