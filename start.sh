#!/usr/bin/env bash 
set -euo pipefail 
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)" 
VENV_DIR="$PROJECT_DIR/venv" 
PYTHON="$VENV_DIR/bin/python" 
ACTIVATE="$VENV_DIR/bin/activate" 
BOT_SCRIPT="$PROJECT_DIR/ro_telegram_test_bot.py" 
ENV_FILE="$PROJECT_DIR/.env" 
LOG_DIR="$PROJECT_DIR/logs" 
OUT_LOG="$LOG_DIR/out.log" 
ERR_LOG="$LOG_DIR/err.log" 
mkdir -p "$LOG_DIR" 
cd "$PROJECT_DIR" 
if [ -f "$ACTIVATE" ]; then 
   source "$ACTIVATE" 
else 
   echo "Virtualenv nu a fost găsit la $VENV_DIR. Creează-l cu: python3 -m venv venv" >&2 
   exit 1 
fi 
if [ -f "$ENV_FILE" ]; then 
   set -o allexport 
   eval "$(grep -v '^\s*#' "$ENV_FILE" | sed -n 's/^\s*\([^=]\+\)=\(.*\)$/export \1=\"\2\"/p')"
   set +o allexport 
fi 
exec >>"$OUT_LOG" 2>>"$ERR_LOG" 
echo "=== Pornire bot: $(date -u +"%Y-%m-%dT%H:%M:%SZ") ===" 
exec "$PYTHON" "$BOT_SCRIPT" 
EOF 
chmod +x start.sh