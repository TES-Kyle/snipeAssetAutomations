#!/usr/bin/env bash
set -euo pipefail

##############################
# [CONFIG BLOCK — EDIT THESE]
##############################
REPO_URL="${REPO_URL:-https://github.com/TES-Kyle/snipeAssetAutomations}"
APP_NAME="${APP_NAME:-Snipe Asset GUI}"
ENTRYPOINT_REL="${ENTRYPOINT_REL:-assetManagementGui_Main.py}"
RUNNER_IN_REPO="${RUNNER_IN_REPO:-shellScripts/run_gui.command}"
USB_DIR="$(cd "$(dirname "$0")" && pwd)"
KEY_SRC_PY="$USB_DIR/Key.py"                # optional
SETTINGS_SRC_JSON="$USB_DIR/settings.json"  # optional  <-- NEW
ICON_SRC_ICNS="$USB_DIR/icon.icns"          # optional  <-- NEW
########################################
# [END CONFIG BLOCK — EDIT ABOVE ONLY]
########################################

##############################
# [PATHS & REQUIREMENTS BLOCK]
##############################
APP_DIR="/Applications/${APP_NAME}.app"
CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RES_DIR="$CONTENTS/Resources"
EMBED_APP_DIR="$RES_DIR/app"    # your project (with .venv)

need() { command -v "$1" >/dev/null 2>&1 || { /usr/bin/osascript -e 'display dialog "'"$1"' is required but not found." buttons {"OK"} default button 1' >/dev/null; exit 1; }; }
need osascript; need git; need bash
if ! command -v python3 >/dev/null 2>&1; then
  /usr/bin/osascript -e 'display dialog "python3 not found.\n\nClick OK to open the Python macOS downloads page." buttons {"OK"} default button 1' >/dev/null
  open "https://www.python.org/downloads/macos/"; exit 1
fi
########################################
# [END PATHS & REQUIREMENTS BLOCK]
########################################

##################################
# [REMOVE/CREATE BUNDLE BLOCK]
##################################
if [ -e "$APP_DIR" ]; then
  RESP="$(/usr/bin/osascript <<APPLESCRIPT
display dialog "An app named \"${APP_NAME}\" already exists in Applications. Replace it?\n\n(This will delete and re-install.)" buttons {"Cancel","Replace"} default button "Replace" with icon caution
button returned of result
APPLESCRIPT
)"; [ "$RESP" = "Replace" ] || exit 0
  /usr/bin/osascript <<APPLESCRIPT >/dev/null
set appPath to POSIX file "$APP_DIR"
do shell script "rm -rf " & quoted form of POSIX path of appPath with administrator privileges
APPLESCRIPT
fi

/usr/bin/osascript <<APPLESCRIPT >/dev/null
set macosDir to POSIX file "$MACOS_DIR"
set resDir to POSIX file "$RES_DIR"
do shell script "mkdir -p " & quoted form of POSIX path of macosDir & " " & quoted form of POSIX path of resDir with administrator privileges
do shell script "chown -R $USER " & quoted form of POSIX path of (POSIX file "$APP_DIR") with administrator privileges
APPLESCRIPT
##################################
# [END REMOVE/CREATE BUNDLE BLOCK]
##################################

#############################
# [CLONE & COPY CODE BLOCK]
#############################
TMPDIR="$(mktemp -d)"; trap 'rm -rf "$TMPDIR"' EXIT
/usr/bin/osascript -e 'display dialog "Cloning repository...\n\nThis may take a moment." buttons {"OK"} giving up after 1' >/dev/null || true
git clone "$REPO_URL" "$TMPDIR/repo"

mkdir -p "$EMBED_APP_DIR"
rsync -a --delete --exclude ".git" --exclude "__pycache__" --exclude ".DS_Store" "$TMPDIR/repo"/ "$EMBED_APP_DIR"/

# [USB SETTINGS COPY — optional]
# settings.py expects settings.json alongside it in utilities/
if [ -f "$SETTINGS_SRC_JSON" ]; then
  mkdir -p "$EMBED_APP_DIR/utilities"
  cp "$SETTINGS_SRC_JSON" "$EMBED_APP_DIR/utilities/settings.json"
fi

# Optional Key.py into utilities/
if [ -f "$KEY_SRC_PY" ]; then
  mkdir -p "$EMBED_APP_DIR/utilities"
  cp "$KEY_SRC_PY" "$EMBED_APP_DIR/utilities/Key.py"
fi
#############################
# [END CLONE & COPY CODE BLOCK]
#############################

#################################
# [BUILD META BLOCK — NEW]
#################################
# Record repo URL, branch and commit sha we installed
mkdir -p "$EMBED_APP_DIR/.build"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALLED_SHA="$(git -C "$TMPDIR/repo" rev-parse HEAD || echo unknown)"
cat > "$EMBED_APP_DIR/.build/meta.json" <<META
{
  "repo_url": "$(printf %s "$REPO_URL")",
  "branch": "$(printf %s "$REPO_BRANCH")",
  "installed_sha": "$(printf %s "$INSTALLED_SHA")",
  "last_checked": ""
}
META
#################################
# [END BUILD META BLOCK]
#################################

# Ensure shipped scripts are executable
chmod +x "$EMBED_APP_DIR/shellScripts/run_gui.command" 2>/dev/null || true
chmod +x "$EMBED_APP_DIR/shellScripts/update_in_place.command" 2>/dev/null || true

############################
# [ENSURE RUNNER BLOCK]
############################
RUNNER="$EMBED_APP_DIR/$RUNNER_IN_REPO"
if [ ! -f "$RUNNER" ]; then
  mkdir -p "$(dirname "$RUNNER")"
  cat > "$RUNNER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
APP_DIR="\$(cd "\$SCRIPT_DIR/.." && pwd)"
VENV="\$APP_DIR/.venv"
PY="\$VENV/bin/python"
ENTRYPOINT="\$APP_DIR/$ENTRYPOINT_REL"
if [ ! -x "\$PY" ]; then /usr/bin/osascript -e 'display dialog "Venv missing. Please reinstall." buttons {"OK"} default button 1' >/dev/null; exit 1; fi
cd "\$APP_DIR"
exec "\$PY" "\$ENTRYPOINT"
EOF
fi
chmod +x "$RUNNER"
############################
# [END ENSURE RUNNER BLOCK]
############################

############################
# [CREATE VENV BLOCK]
############################
cd "$EMBED_APP_DIR"
python3 -m venv ".venv"
"./.venv/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
if [ -f "requirements.txt" ]; then
  /usr/bin/osascript -e 'display dialog "Installing Python dependencies..." buttons {"OK"} giving up after 1' >/dev/null || true
  "./.venv/bin/python" -m pip install -r "requirements.txt"
fi
############################
# [END CREATE VENV BLOCK]
############################

########################################
# [CREATE LOGGING LAUNCHER (MacOS) BLOCK]
########################################
cat > "$MACOS_DIR/launcher" <<'LAUNCH'
#!/usr/bin/env bash
set -euo pipefail
APP_NAME="Snipe Asset GUI"
LOG_DIR="$HOME/Library/Logs/$APP_NAME"
LOG_FILE="$LOG_DIR/launch.log"
mkdir -p "$LOG_DIR"
{
  echo "===== Launch $(date) ====="
  echo "whoami: $(whoami)"
  echo "uname: $(uname -a)"
  echo "uname -m: $(uname -m)"
  echo "PATH(before): $PATH"
  export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
  echo "PATH(after):  $PATH"
  ME_DIR="$(cd "$(dirname "$0")" && pwd)"
  RES_DIR="${ME_DIR}/../Resources"
  APP_DIR="${RES_DIR}/app"
  RUNNER="${APP_DIR}/shellScripts/run_gui.command"
  if [ "$(uname -m)" = "arm64" ]; then
    exec /usr/bin/arch -arm64 "$RUNNER"
  fi
  exec "$RUNNER"
} >>"$LOG_FILE" 2>&1
LAUNCH
chmod +x "$MACOS_DIR/launcher"
############################################
# [END CREATE LOGGING LAUNCHER (MacOS) BLOCK]
############################################

###############################
# [WRITE INFO.PLIST FILE BLOCK]
###############################
PLIST="$CONTENTS/Info.plist"
/usr/bin/plutil -convert xml1 -o "$PLIST" -- - <<PL
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>local.$(echo "$APP_NAME" | tr '[:space:]' '-' | tr '[:upper:]' '[:lower:]')</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>LSMinimumSystemVersion</key><string>10.14</string>
  <key>LSHighResolutionCapable</key><true/>
  <key>LSArchitecturePriority</key>
  <array><string>arm64</string><string>x86_64</string></array>
</dict>
</plist>
PL
#################################
# [END WRITE INFO.PLIST FILE BLOCK]
#################################

#########################
# [ICON SUPPORT — NEW]
#########################
# If icon.icns is present on the USB, use it as app icon
if [ -f "$ICON_SRC_ICNS" ]; then
  cp "$ICON_SRC_ICNS" "$RES_DIR/icon.icns"
  /usr/bin/defaults write "$CONTENTS/Info" CFBundleIconFile "icon"
  /usr/bin/plutil -convert xml1 "$CONTENTS/Info.plist" >/dev/null 2>&1 || true
fi
#########################
# [END ICON SUPPORT]
#########################

################################
# [FINALIZE & SHORTCUTS BLOCK]
################################
xattr -dr com.apple.quarantine "$APP_DIR" >/dev/null 2>&1 || true
RESP="$(/usr/bin/osascript <<'APPLESCRIPT'
display dialog "Installation complete.\n\nCreate a Desktop shortcut to launch the app?" buttons {"No","Yes"} default button "Yes"
button returned of result
APPLESCRIPT
)"
if [ "$RESP" = "Yes" ]; then
  ln -sf "$APP_DIR" "$HOME/Desktop/$APP_NAME.app"
fi
/usr/bin/osascript -e 'display dialog "All set.\n\nLaunch from Applications → '"$APP_NAME"'." buttons {"OK"} default button 1' >/dev/null
################################
# [END FINALIZE & SHORTCUTS BLOCK]
################################
