#!/bin/bash
# USB maker for macOS: builds a full-install USB (installer.command + this
# machine's real Key.py/settings.json/icon.icns).
#
# Disk selection/erase/mount and the installer.command+icon copy/eject tail
# are shared with the partial-install builder via select_and_erase_usb.command
# and finalize_usb.command -- this script's own job is just the bit in
# between that's unique to a *full* install: copying this machine's real,
# untrimmed Key.py/settings.json onto the USB. The partial-install builder
# never calls this script -- it calls the two shared ones directly and
# writes its own trimmed Key.py in between instead.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Sources (relative to repo)
INSTALLER_SRC="$SCRIPT_DIR/installer.command"          # required
KEY_SRC="$REPO_ROOT/utilities/Key.py"                  # optional
SETTINGS_SRC="$REPO_ROOT/utilities/settings.json"      # optional

# Sanity: installer must exist (fail before bothering the admin with a
# destructive disk-erase prompt for nothing).
if [ ! -f "$INSTALLER_SRC" ]; then
  /usr/bin/osascript -e 'display dialog "installer.command not found.\n\nExpected at:\n'"$INSTALLER_SRC"'" buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

CANCELLED=2
# Invoked via explicit `bash <path>` rather than the script's own shebang/+x
# bit, so this doesn't depend on execute permissions surviving a git clone.
# set +e/-e brackets the call: with set -e active, USB_MOUNT="$(...)" would
# otherwise abort the whole script the instant the helper exits non-zero
# (e.g. exit 2 for "admin cancelled"), before STATUS=$? is ever reached.
set +e
USB_MOUNT="$(bash "$SCRIPT_DIR/select_and_erase_usb.command")"
STATUS=$?
set -e
if [ "$STATUS" -eq "$CANCELLED" ]; then
  exit 0
elif [ "$STATUS" -ne 0 ] || [ -z "$USB_MOUNT" ]; then
  exit "$STATUS"
fi

[ -f "$KEY_SRC" ]      && /bin/cp "$KEY_SRC" "$USB_MOUNT/Key.py"
[ -f "$SETTINGS_SRC" ] && /bin/cp "$SETTINGS_SRC" "$USB_MOUNT/settings.json"

bash "$SCRIPT_DIR/finalize_usb.command" "$USB_MOUNT"
bash "$SCRIPT_DIR/offer_eject.command" "$USB_MOUNT"

/usr/bin/osascript -e 'display dialog "USB is ready.\n\nCopied:\n• installer.command\n• (optional) icon.icns\n• (optional) Key.py\n• (optional) settings.json" buttons {"OK"} default button 1' >/dev/null
