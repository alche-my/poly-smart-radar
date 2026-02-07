#!/bin/bash
# Quick update script for VPS
# Usage: ./deploy/update.sh

set -e

cd /root/poly-smart-radar

echo "=== Updating Poly Smart Radar ==="

# Reset local changes and pull latest
echo "[1/4] Pulling latest code..."
git fetch origin
git reset --hard origin/claude/review-pr-questions-NtU9n

# Rebuild frontend
echo "[2/4] Building frontend..."
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
cd ..

# Restart services
echo "[3/4] Restarting services..."
systemctl restart poly-radar-api || true
systemctl restart poly-radar-bot || true

# Reload nginx
echo "[4/4] Reloading nginx..."
systemctl reload nginx

echo ""
echo "=== Update complete! ==="
echo "Check: https://radar.rawrvpn.xyz"
