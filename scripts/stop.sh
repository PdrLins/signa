#!/bin/bash
# Signa — Stop this project's servers (+ remove LAN-mode firewall exceptions)
# Usage: ./scripts/stop.sh           (SIGNA_LAN=1 ./scripts/stop.sh to also clean firewall)

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/back-end"
FRONTEND="$ROOT/front-end"

if [ -x "$BACKEND/venv/bin/python" ]; then
  PYTHON="$BACKEND/venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

# Kill only processes matching $1 whose working directory is $2 (this project).
# Prints how many were stopped.
kill_project_procs() {
  local pattern="$1" dir="$2" pid cwd n=0
  for pid in $(pgrep -f "$pattern" 2>/dev/null); do
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
    if [ "$cwd" = "$dir" ]; then
      kill "$pid" 2>/dev/null && n=$((n + 1))
    fi
  done
  echo "$n"
}

echo "Stopping Signa..."
[ "$(kill_project_procs "uvicorn main:app" "$BACKEND")" -gt 0 ] && echo "  Backend stopped" || echo "  Backend not running"
[ "$(kill_project_procs "next-server|next start" "$FRONTEND")" -gt 0 ] && echo "  Frontend stopped" || echo "  Frontend not running"

if [ "${SIGNA_LAN:-0}" = "1" ]; then
  echo "Removing firewall exceptions..."
  FW_PYTHON=$("$PYTHON" -c 'import os, sys
app = os.path.join(sys.base_prefix, "Resources/Python.app/Contents/MacOS/Python")
print(app if os.path.exists(app) else os.path.realpath(sys.executable))')
  FW_NODE=$(command -v node)
  sudo /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$FW_PYTHON" > /dev/null 2>&1
  sudo /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$FW_NODE" > /dev/null 2>&1
fi

echo "Done."
