#!/bin/bash
# Tail-end phase, extracted from make_installer_usb.command so it can be
# shared with the partial-install builder: copy installer.command + optional
# icon.icns onto an already-populated USB volume, clear quarantine. Assumes
# app payload / Key.py / settings.json are already on the volume
# (make_installer_usb.command copies its own before calling this; the
# partial-install builder writes its trimmed versions before calling this).
#
# Deliberately does NOT prompt to eject or show a final "ready" dialog --
# see offer_eject.command. Keeping that prompt out of this script lets each
# caller decide what happens between "files are all on the drive" and
# "the drive gets ejected" -- for the partial-install builder specifically,
# that gap is where its own success summary (file/secret counts, "check
# Key.py in Finder now") needs to show, which only works if nothing has
# offered to eject the drive yet.
set -e

USB_MOUNT="${1:?Usage: finalize_usb.command <mounted-volume-path>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INSTALLER_SRC="$SCRIPT_DIR/installer.command"
ICON_SRC=""

if [ ! -f "$INSTALLER_SRC" ]; then
  /usr/bin/osascript -e 'display dialog "installer.command not found.\n\nExpected at:\n'"$INSTALLER_SRC"'" buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

# Resolve icon source from common locations (repo, app bundle).
for candidate in \
  "$SCRIPT_DIR/icon.icns" \
  "$REPO_ROOT/../icon.icns" \
  "$REPO_ROOT/../../Resources/icon.icns"
do
  if [ -f "$candidate" ]; then
    ICON_SRC="$candidate"
    break
  fi
done

/bin/cp "$INSTALLER_SRC" "$USB_MOUNT/installer.command"
/bin/chmod +x "$USB_MOUNT/installer.command"
[ -n "$ICON_SRC" ] && /bin/cp "$ICON_SRC" "$USB_MOUNT/icon.icns"

# Clear quarantine on the USB contents (best effort)
/usr/bin/xattr -dr com.apple.quarantine "$USB_MOUNT" >/dev/null 2>&1 || true
