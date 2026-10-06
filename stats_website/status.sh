#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$SCRIPT_DIR/server.pid"
PORT="${1:-8080}"

IS_ACTIVE=$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(('127.0.0.1', $PORT))
    s.close()
    print('no')
except OSError:
    print('yes')
")

if [[ "$IS_ACTIVE" == "yes" ]]; then
  PID_STR=""
  if [[ -f "$PIDFILE" ]]; then
    PID_STR=" (PID $(cat "$PIDFILE" 2>/dev/null || true))"
  fi
  echo "🟢 Stat Website Server is RUNNING on port $PORT$PID_STR"
  echo "🌐 Local URL: http://localhost:$PORT/"
  exit 0
else
  echo "🔴 Stat Website Server is NOT running on port $PORT."
  echo "Run ./stats_website/start_server.sh to launch it."
  exit 1
fi
