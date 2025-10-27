#!/usr/bin/env bash
set -euo pipefail

# ---------- config ----------
APP_NAME="Snipe Asset GUI"
# ----------------------------

# Paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"            # …/app/shellScripts (inside bundle at runtime)
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"                # …/app
VENV="$APP_DIR/.venv"
PY="$VENV/bin/python"
META="$APP_DIR/.build/meta.json"

# Logging (optional but handy)
LOG_DIR="$HOME/Library/Logs/$APP_NAME"
mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/update.log" 2>&1
echo "===== Update $(date) ====="

alert() { /usr/bin/osascript -e 'display dialog '"$1"' buttons {"OK"} default button 1' >/dev/null || true; }

# Sanity checks
if [ ! -f "$META" ]; then
  alert '"Missing .build/meta.json — please reinstall."'
  exit 1
fi

# Read repo + branch from meta
REPO_URL="$(/usr/bin/python3 - <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("repo_url",""))
PY
"$META")"

BRANCH="$(/usr/bin/python3 - <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("branch","main"))
PY
"$META")"

if [ -z "$REPO_URL" ]; then
  alert '"No repository URL in meta.json — cannot update."'
  exit 1
fi

TMPDIR="$(/usr/bin/mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

/usr/bin/osascript -e 'display dialog "Downloading update...\n\nThis may take a minute." buttons {"OK"} giving up after 1' >/dev/null || true

# Clone fresh (latest on branch)
git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$TMPDIR/repo"

NEW_SHA="$(git -C "$TMPDIR/repo" rev-parse HEAD || echo unknown)"

# Preserve local secrets/settings
PRESERVE_DIR="$TMPDIR/preserve"
mkdir -p "$PRESERVE_DIR/utilities"
[ -f "$APP_DIR/utilities/Key.py" ] && cp "$APP_DIR/utilities/Key.py" "$PRESERVE_DIR/utilities/Key.py"
[ -f "$APP_DIR/utilities/settings.json" ] && cp "$APP_DIR/utilities/settings.json" "$PRESERVE_DIR/utilities/settings.json"

# Rsync into place
rsync -a --delete \
  --exclude ".git" --exclude "__pycache__" --exclude ".DS_Store" \
  "$TMPDIR/repo"/ "$APP_DIR"/

# Restore preserved files
[ -f "$PRESERVE_DIR/utilities/Key.py" ] && cp "$PRESERVE_DIR/utilities/Key.py" "$APP_DIR/utilities/Key.py"
[ -f "$PRESERVE_DIR/utilities/settings.json" ] && cp "$PRESERVE_DIR/utilities/settings.json" "$APP_DIR/utilities/settings.json"

# Ensure scripts are executable (in case git lost x-bit)
chmod +x "$APP_DIR/shellScripts/run_gui.command" 2>/dev/null || true
chmod +x "$APP_DIR/shellScripts/update_in_place.command" 2>/dev/null || true

# Reinstall dependencies (if venv + requirements exist)
if [ -x "$PY" ] && [ -f "$APP_DIR/requirements.txt" ]; then
  "$PY" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
  "$PY" -m pip install -r "$APP_DIR/requirements.txt"
fi

# Update meta
/usr/bin/python3 - <<PY "$META" "$REPO_URL" "$BRANCH" "$NEW_SHA"
import json,sys,datetime
p,repo,branch,sha=sys.argv[1:]
try: d=json.load(open(p))
except Exception: d={}
d.update({"repo_url": repo, "branch": branch, "installed_sha": sha, "last_checked": datetime.datetime.now().isoformat()})
json.dump(d, open(p,"w"))
PY

/usr/bin/osascript -e 'display dialog "Update complete.\n\nPlease quit and relaunch the app." buttons {"OK"} default button 1' >/dev/null || true
