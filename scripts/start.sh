#!/bin/bash
# Signa — Start backend + frontend in production mode
# Logs show in terminal. Keep terminal open.
# Usage: ./scripts/start.sh

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/back-end"
FRONTEND="$ROOT/front-end"

# Stop any existing instances
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
sleep 1

# Get local IP
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "localhost")

# Firewall exceptions for phone access
PYTHON_PATH="/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
NODE_PATH=$(which node)
echo "Adding firewall exceptions (may ask for password)..."
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PYTHON_PATH" > /dev/null 2>&1
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$NODE_PATH" > /dev/null 2>&1

echo "========================================="
echo "  Signa — Starting"
echo "========================================="
echo "  Desktop:  http://localhost:3000"
echo "  Phone:    http://$LOCAL_IP:3000"
echo "  API:      http://localhost:8000"
echo "  Stop:     Ctrl+C"
echo "========================================="
echo ""

# Start backend in background (logs to terminal)
cd "$BACKEND"
source venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend
for i in {1..15}; do
  curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1 && break
  sleep 1
done

# Build frontend with LAN IP so phone/tablet can reach the API
cd "$FRONTEND"
export NEXT_PUBLIC_API_URL="http://$LOCAL_IP:8000/api/v1"

if [ ! -f ".next/BUILD_ID" ]; then
  echo "[Building frontend for $LOCAL_IP...]"
  npm run build --silent 2>/dev/null
fi

# Start frontend in background (logs to terminal)
NEXT_PUBLIC_API_URL="http://$LOCAL_IP:8000/api/v1" npx next start -H 0.0.0.0 -p 3000 &
FRONTEND_PID=$!

echo ""
echo "✓ Signa is running. Press Ctrl+C to stop."
echo ""

# On Ctrl+C: kill servers + remove firewall exceptions
cleanup() {
  echo ""
  echo "========================================="
  echo "  Signa — Shutting down"
  echo "========================================="
  echo "  Stopping backend..."
  kill $BACKEND_PID 2>/dev/null
  echo "  Stopping frontend..."
  kill $FRONTEND_PID 2>/dev/null
  sleep 1
  echo "  Removing firewall exceptions..."
  sudo /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$PYTHON_PATH" > /dev/null 2>&1
  sudo /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$NODE_PATH" > /dev/null 2>&1
  echo "  Firewall restored."
  echo "========================================="
  echo "  Signa stopped. See you next time."
  echo "========================================="
  exit 0
}
trap cleanup INT TERM
wait
