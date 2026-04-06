#!/bin/bash
# Signa — Start backend + frontend in production mode
# Usage: ./scripts/start.sh

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/back-end"
FRONTEND="$ROOT/front-end"

echo "========================================="
echo "  Signa — Starting production servers"
echo "========================================="

# Stop any existing instances
echo "[1/5] Stopping existing processes..."
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
sleep 1

# Backend
echo "[2/5] Starting backend..."
cd "$BACKEND"
source venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 > "$BACKEND/signa-backend.log" 2>&1 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"
echo "  Logs: $BACKEND/signa-backend.log"

# Wait for backend to be ready
echo "[3/5] Waiting for backend..."
for i in {1..15}; do
  if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    echo "  Backend ready!"
    break
  fi
  sleep 1
done

# Frontend
echo "[4/5] Building frontend..."
cd "$FRONTEND"
npm run build --silent 2>/dev/null

echo "[5/5] Starting frontend..."
nohup npx next start -H 0.0.0.0 -p 3000 > "$FRONTEND/signa-frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"
echo "  Logs: $FRONTEND/signa-frontend.log"

# Get local IP
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "localhost")

sleep 2
echo ""
echo "========================================="
echo "  Signa is running!"
echo "========================================="
echo "  Desktop:  http://localhost:3000"
echo "  Phone:    http://$LOCAL_IP:3000"
echo "  API:      http://localhost:8000/api/v1/health"
echo ""
echo "  Stop:     ./scripts/stop.sh"
echo "  Logs:     tail -f back-end/signa-backend.log"
echo "========================================="
