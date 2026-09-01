#!/bin/bash
# Split out of finalize_usb.command so callers control exactly when this
# fires -- specifically so the partial-install builder can show its own
# success summary (file/secret counts, "check Key.py in Finder now") BEFORE
# the drive is offered up for ejection, not after. Safe to call once the
# volume is in its final state (all files written, nothing more to add).
set -e

USB_MOUNT="${1:?Usage: offer_eject.command <mounted-volume-path>}"

RESP="$(/usr/bin/osascript <<'APPLESCRIPT'
display dialog "USB prepared successfully.\n\nEject now?" buttons {"No","Eject"} default button "Eject"
button returned of result
APPLESCRIPT
)" || true
if [ "$RESP" = "Eject" ]; then
  /usr/sbin/diskutil eject "$USB_MOUNT" >/dev/null 2>&1 || true
fi
