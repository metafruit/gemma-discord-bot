#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${(%):-%N}")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE="$SCRIPT_DIR/bot.pid"

# Guard: exit if bot is already running
if [[ -f "$PIDFILE" ]]; then
  EXISTING_PID=$(cat "$PIDFILE")
  if kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "Bot is already running (PID $EXISTING_PID). Refusing to start a second instance."
    exit 1
  fi
fi

# Write our own PID before exec (exec replaces the shell process, same PID)
echo $$ > "$PIDFILE"

# Load environment variables from .env if present
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

if [[ -z "${DISCORD_TOKEN:-}" ]]; then
  echo "Error: DISCORD_TOKEN is not set. Please set it in .env or your environment." >&2
  exit 1
fi

export GEMINI_API_KEY="${GEMINI_API_KEY:-}"
exec /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -u bot.py >> "$SCRIPT_DIR/bot.log" 2>&1
