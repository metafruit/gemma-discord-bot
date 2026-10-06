#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$SCRIPT_DIR/server.pid"
LOGFILE="$SCRIPT_DIR/server.log"
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
  echo "Stat website server is already active on port $PORT$PID_STR."
  echo "🌐 Access it at: http://localhost:$PORT/"
  exit 0
fi

echo "Starting Stat Website Server on port $PORT..."
python3 "$SCRIPT_DIR/server.py" --port "$PORT" >> "$LOGFILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PIDFILE"

# Wait a moment to verify startup
sleep 1
IS_ACTIVE_NOW=$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(('127.0.0.1', $PORT))
    s.close()
    print('no')
except OSError:
    print('yes')
")

if [[ "$IS_ACTIVE_NOW" == "yes" ]]; then
  echo "✅ Server started successfully (PID: $SERVER_PID)!"
  echo "🌐 Website URL: http://localhost:$PORT/"
  echo "📄 Logs: $LOGFILE"
else
  echo "❌ Server failed to start. Last log lines:"
  tail -n 15 "$LOGFILE"
  exit 1
fi
