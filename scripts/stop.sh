#!/bin/bash
# Signa — Stop all servers
# Usage: ./scripts/stop.sh

echo "Stopping Signa..."
pkill -f "uvicorn main:app" 2>/dev/null && echo "  Backend stopped" || echo "  Backend not running"
pkill -f "next-server" 2>/dev/null && echo "  Frontend stopped" || echo "  Frontend not running"
echo "Done."
