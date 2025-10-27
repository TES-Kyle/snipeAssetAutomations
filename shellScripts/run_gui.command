#!/usr/bin/env bash
set -euo pipefail

# Resolve project root (this script lives in <project>/shellScripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

VENV="$APP_DIR/.venv"
PY="$VENV/bin/python"

# Entry point relative to project root (edit if needed)
ENTRYPOINT="$APP_DIR/assetManagementGui_Main.py"

if [ ! -x "$PY" ]; then
  /usr/bin/osascript -e 'display dialog "Python virtual environment not found.\n\nPlease run the installer to set up venv and dependencies." buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

if [ ! -f "$ENTRYPOINT" ]; then
  /usr/bin/osascript -e 'display dialog "Entry point not found:\n'"$ENTRYPOINT"'\n\nPlease verify your installation." buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

cd "$APP_DIR"
exec "$PY" "$ENTRYPOINT"
