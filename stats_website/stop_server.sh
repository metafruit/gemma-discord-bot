#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$SCRIPT_DIR/server.pid"

if [[ -f "$PIDFILE" ]]; then
  PID=$(cat "$PIDFILE" 2>/dev/null || true)
  if [[ -n "$PID" ]]; then
    echo "Stopping server (PID $PID)..."
    kill "$PID" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "✅ Server stop signal sent."
    exit 0
  fi
  rm -f "$PIDFILE"
fi

echo "PID file not found. If running, stop with: pkill -f 'stats_website/server.py'"
