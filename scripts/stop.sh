#!/bin/bash
# Signa — Stop all servers + remove firewall exceptions
# Usage: ./scripts/stop.sh

echo "Stopping Signa..."
pkill -f "uvicorn main:app" 2>/dev/null && echo "  Backend stopped" || echo "  Backend not running"
pkill -f "next-server" 2>/dev/null && echo "  Frontend stopped" || echo "  Frontend not running"

echo "Removing firewall exceptions..."
PYTHON_PATH="/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
NODE_PATH=$(which node)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$PYTHON_PATH" > /dev/null 2>&1
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --remove "$NODE_PATH" > /dev/null 2>&1

echo "Done."
