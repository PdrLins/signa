#!/bin/bash
# Signa — Start backend + frontend in production mode
# Logs show in terminal. Keep terminal open.
#
# Usage:
#   ./scripts/start.sh                 # local only (127.0.0.1) — default, safest
#   SIGNA_LAN=1 ./scripts/start.sh     # expose on the LAN over PLAIN HTTP (see warning)
#
# Recommended way to use Signa from your phone: Tailscale, keeping the default
# loopback binding and letting `tailscale serve` terminate HTTPS:
#   tailscale serve --bg --https=443 http://127.0.0.1:3000
#   ./scripts/start.sh
# (the API is proxied through the web server, so only port 3000 is served).
#
# Env vars:
#   SIGNA_LAN=1      serve the web page on 0.0.0.0:3000 (same-Wi-Fi phone access)
#                    and add a macOS firewall exception for Node (sudo); the
#                    API stays on 127.0.0.1 behind the /api/v1 proxy
#   SIGNA_API_URL    API base baked into the frontend build (default: /api/v1)

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/back-end"
FRONTEND="$ROOT/front-end"

# Python: prefer the project venv, fall back to python3 on PATH
if [ -x "$BACKEND/venv/bin/python" ]; then
  PYTHON="$BACKEND/venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

# Kill only processes matching $1 whose working directory is $2 (this project),
# so other Next.js / uvicorn apps on the machine are left alone.
kill_project_procs() {
  local pattern="$1" dir="$2" pid cwd
  for pid in $(pgrep -f "$pattern" 2>/dev/null); do
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
    if [ "$cwd" = "$dir" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}

# Stop any existing instances of THIS project
kill_project_procs "uvicorn main:app" "$BACKEND"
kill_project_procs "next-server|next start" "$FRONTEND"
sleep 1

# The backend ALWAYS binds 127.0.0.1. The browser reaches it through the
# Next.js /api/v1 proxy (front-end/next.config.mjs rewrites), so in LAN mode
# only the web page (port 3000) is visible on the network.
if [ "${SIGNA_LAN:-0}" = "1" ]; then
  BIND_HOST="0.0.0.0"
  LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")
  API_URL="${SIGNA_API_URL:-/api/v1}"

  echo ""
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: LAN mode. Signa will listen on ALL interfaces over PLAIN HTTP."
  echo "  Passwords, OTPs and JWTs cross the network unencrypted — anyone on"
  echo "  this Wi-Fi can sniff them. Use only on a network you fully trust."
  echo "  Recommended instead: Tailscale (see header of this script)."
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""

  # macOS firewall exception for the Node binary serving the web page
  FW_NODE=$(command -v node)
  echo "Adding a firewall exception for Node (may ask for password)..."
  sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$FW_NODE" > /dev/null 2>&1 || true
  PHONE_LINE="  Phone:    http://$LOCAL_IP:3000  (plain HTTP!)"
else
  BIND_HOST="127.0.0.1"
  API_URL="${SIGNA_API_URL:-/api/v1}"
  PHONE_LINE="  Phone:    not exposed (SIGNA_LAN=1 for same Wi-Fi, or Tailscale serve)"
fi

echo "========================================="
echo "  Signa — Starting"
echo "========================================="
echo "  Desktop:  http://localhost:3000"
echo "$PHONE_LINE"
echo "  API:      $API_URL"
echo "  Stop:     Ctrl+C"
echo "========================================="
echo ""

# Start backend in background (logs to terminal)
cd "$BACKEND"
"$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Wait for backend
for i in {1..15}; do
  curl -s http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1 && break
  sleep 1
done

# Build frontend with the API URL baked in (also pins the CSP connect-src)
cd "$FRONTEND"
export NEXT_PUBLIC_API_URL="$API_URL"

echo "[Building frontend for $API_URL...]"
if ! npm run build; then
  echo ""
  echo "✗ Frontend build failed. See errors above."
  kill $BACKEND_PID 2>/dev/null
  exit 1
fi

# Start frontend in background (logs to terminal)
npx next start -H "$BIND_HOST" -p 3000 &
FRONTEND_PID=$!

echo ""
echo "✓ Signa is running. Press Ctrl+C to stop."
echo ""

# On Ctrl+C: kill servers (+ remove firewall exceptions in LAN mode)
cleanup() {
  echo ""
  echo "========================================="
  echo "  Signa — Shutting down"
  echo "========================================="
  echo "  Stopping backend..."
  kill $BACKEND_PID 2>/dev/null
  echo "  Stopping frontend..."
  kill $FRONTEND_PID 2>/dev/null
  kill_project_procs "next-server|next start" "$FRONTEND"
  sleep 1
  if [ "${SIGNA_LAN:-0}" = "1" ]; then
    echo "  Removing firewall exceptions..."
    sudo /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$FW_NODE" > /dev/null 2>&1
    echo "  Firewall restored."
  fi
  echo "========================================="
  echo "  Signa stopped. See you next time."
  echo "========================================="
  exit 0
}
trap cleanup INT TERM
wait
