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
mkdir -p "$EMBED_APP_DIR"

# A partial-install USB (built by utilities/partialInstallBuilder.py) carries
# a pre-trimmed app copy -- Key.py already cut down to only the secrets the
# selected functions need, routing tables already cut down to only those
# functions. Use it directly and skip the clone entirely. Deliberately does
# NOT apply KEY_SRC_PY/SETTINGS_SRC_JSON below even if present at the USB
# root -- a leftover full Key.py there must never be able to silently
# overwrite the trimmed one partial_app/ already carries.
PARTIAL_APP_SRC="$USB_DIR/partial_app"
if [ -d "$PARTIAL_APP_SRC" ]; then
  /usr/bin/osascript -e 'display dialog "Installing from USB (partial install)...\n\nThis may take a moment." buttons {"OK"} giving up after 1' >/dev/null || true
  rsync -a --delete --exclude ".git" --exclude "__pycache__" --exclude ".DS_Store" "$PARTIAL_APP_SRC"/ "$EMBED_APP_DIR"/
  # No INSTALLED_SHA here -- partial_app/.build/meta.json (copied above)
  # already has the admin's real HEAD sha from USB-build time, and the
  # BUILD META BLOCK below leaves that file alone when it already exists.
else
  TMPDIR="$(mktemp -d)"; trap 'rm -rf "$TMPDIR"' EXIT
  /usr/bin/osascript -e 'display dialog "Cloning repository...\n\nThis may take a moment." buttons {"OK"} giving up after 1' >/dev/null || true
  git clone "$REPO_URL" "$TMPDIR/repo"

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

  INSTALLED_SHA="$(git -C "$TMPDIR/repo" rev-parse HEAD || echo unknown)"
fi
#############################
# [END CLONE & COPY CODE BLOCK]
#############################

#################################
# [BUILD META BLOCK — NEW]
#################################
# Record repo URL, branch and commit sha we installed. A partial install's
# partial_app/.build/meta.json was already copied in by the rsync above,
# with the admin's real HEAD sha at USB-build time (not a placeholder) --
# keep that as-is so checkUpdate() on the target machine can tell whether a
# real update is available, instead of generating a fresh one here.
mkdir -p "$EMBED_APP_DIR/.build"
if [ -f "$EMBED_APP_DIR/.build/meta.json" ]; then
  echo "Using pre-built .build/meta.json from partial_app (partial install)."
else
  REPO_BRANCH="${REPO_BRANCH:-main}"
  cat > "$EMBED_APP_DIR/.build/meta.json" <<META
{
  "repo_url": "$(printf %s "$REPO_URL")",
  "branch": "$(printf %s "$REPO_BRANCH")",
  "installed_sha": "$(printf %s "$INSTALLED_SHA")",
  "last_checked": ""
}
META
fi
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
# [PROVISION PYTHON RUNTIME BLOCK]
############################
# macOS's system python3 (/usr/bin/python3, what "need python3" above just
# confirmed exists) is stuck on Tcl/Tk 8.5 -- Apple has shipped that same
# ancient, deprecated version for over a decade. A venv built from it
# installs fine, but the GUI renders badly: flat buttons, missing
# LabelFrame borders, generally broken Aqua theming (confirmed side by
# side against a modern Tcl/Tk -- this isn't a guess). Rather than
# requiring the admin to have already installed a newer Python -- exactly
# the "extra setup on a fresh Mac" this deployment path exists to avoid --
# download a small self-contained Python build (python-build-standalone,
# the same project `uv` uses under the hood) with a real, modern, working
# Tcl/Tk, and use that for the venv instead. Extracted into the app's own
# directory, already chown'd to this user above, so this needs no
# additional admin privileges beyond what was already required.
#
# Falls back to system python3 on any failure (network blocked, download
# corrupted, unsupported architecture) rather than failing the whole
# install -- a worse-looking GUI beats no app at all -- but says so
# clearly rather than silently degrading.
PYSTANDALONE_RELEASE="20260825"
PYSTANDALONE_PYVER="3.12.14"
PYRUNTIME_DIR="$EMBED_APP_DIR/.python-runtime"
PYBIN="python3"   # falls back to this (system PATH) unless bundling succeeds below

case "$(uname -m)" in
  arm64)   PYSTANDALONE_ARCH="aarch64" ;;
  x86_64)  PYSTANDALONE_ARCH="x86_64" ;;
  *)       PYSTANDALONE_ARCH="" ;;
esac

if [ -n "$PYSTANDALONE_ARCH" ]; then
  PYSTANDALONE_ASSET="cpython-${PYSTANDALONE_PYVER}+${PYSTANDALONE_RELEASE}-${PYSTANDALONE_ARCH}-apple-darwin-install_only.tar.gz"
  PYSTANDALONE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYSTANDALONE_RELEASE}/${PYSTANDALONE_ASSET}"

  if [ -x "$PYRUNTIME_DIR/python/bin/python3" ]; then
    # Already provisioned (e.g. re-running the installer over an existing
    # copy) -- reuse it rather than re-downloading.
    PYBIN="$PYRUNTIME_DIR/python/bin/python3"
  else
    /usr/bin/osascript -e 'display dialog "Downloading a Python runtime with proper macOS support...\n\nThis may take a moment." buttons {"OK"} giving up after 1' >/dev/null || true
    PYTMP="$(mktemp -d)"
    PY_OK=0
    for attempt in 1 2 3; do
      if curl -fsSL "$PYSTANDALONE_URL" -o "$PYTMP/python.tar.gz" 2>"$PYTMP/curl_err.log" \
         && tar -tzf "$PYTMP/python.tar.gz" >/dev/null 2>"$PYTMP/tar_err.log"; then
        PY_OK=1
        break
      fi
      /bin/sleep 2
    done

    if [ "$PY_OK" -eq 1 ]; then
      mkdir -p "$PYRUNTIME_DIR"
      tar -xzf "$PYTMP/python.tar.gz" -C "$PYRUNTIME_DIR"
      xattr -dr com.apple.quarantine "$PYRUNTIME_DIR" >/dev/null 2>&1 || true
      if [ -x "$PYRUNTIME_DIR/python/bin/python3" ] && "$PYRUNTIME_DIR/python/bin/python3" -c "import tkinter" >/dev/null 2>&1; then
        PYBIN="$PYRUNTIME_DIR/python/bin/python3"
      else
        echo "Bundled Python extracted but failed a basic tkinter check; falling back to system python3."
        rm -rf "$PYRUNTIME_DIR"
      fi
    fi
    rm -rf "$PYTMP"
  fi
fi

if [ "$PYBIN" = "python3" ]; then
  /usr/bin/osascript -e 'display dialog "Could not set up a modern Python runtime (network issue or unsupported Mac).\n\nContinuing with the built-in Python on this Mac instead -- the app will still work, but menus and buttons may look visually different than expected. If this keeps happening, let the department know." buttons {"OK"} default button 1' >/dev/null
fi
############################
# [END PROVISION PYTHON RUNTIME BLOCK]
############################

############################
# [CREATE VENV BLOCK]
############################
cd "$EMBED_APP_DIR"
"$PYBIN" -m venv ".venv"
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
