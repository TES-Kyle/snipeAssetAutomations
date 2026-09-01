#!/bin/bash
# Disk-select/erase/mount phase, extracted from make_installer_usb.command so
# it can be reused by the partial-install builder (utilities/partialInstallBuilder.py),
# which populates the mounted volume itself instead of copying a fixed set of files.
#
# Contract: on success, prints ONLY the mounted volume path as the last line
# of stdout and exits 0. If the admin cancels at any prompt, exits 2 with no
# meaningful stdout. Any other failure exits non-zero (and non-2) with an
# error dialog already shown.
set -e

VOL_NAME="GUI Installer"
CANCELLED=2

# Find whole external disks: e.g. /dev/disk6 lines from diskutil
IDS_STR="$(/usr/sbin/diskutil list external physical 2>/dev/null \
  | /usr/bin/sed -n 's|^/dev/\(disk[0-9]\{1,\}\).*$|\1|p' \
  | /usr/bin/sort -u)"

if [ -z "$IDS_STR" ]; then
  /usr/bin/osascript -e 'display dialog "No external (physical) disks detected.\n\nPlug in a USB drive and try again." buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

# Build friendly labels for each disk: "diskN — <name> — <size>"
TMPDIR="$(/usr/bin/mktemp -d)"; trap 'rm -rf "$TMPDIR"' EXIT
MAP_FILE="$TMPDIR/labels.tsv"   # label<TAB>diskN
LABELS_FILE="$TMPDIR/labels.txt"

> "$MAP_FILE"
> "$LABELS_FILE"

for id in $IDS_STR; do
  # Pull a human-friendly name (try several keys)
  NAME="$(/usr/sbin/diskutil info "/dev/$id" 2>/dev/null \
    | /usr/bin/awk -F': *' '
        /Device \/ Media Name:/ {print $2; found=1; exit}
        /Device Model:/         {print $2; found=1; exit}
        /Media Name:/           {print $2; found=1; exit}
      END { if (!found) print "" }' \
    | /usr/bin/sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"

  [ -z "$NAME" ] && NAME="External Media"

  # Extract compact size from the "Total Size:" line (e.g., "64.0 GB")
  SIZE="$(/usr/sbin/diskutil info "/dev/$id" 2>/dev/null \
    | /usr/bin/awk -F': *' '/Total Size:/ {print $2; exit}' \
    | /usr/bin/awk '{print $1" "$2}')"

  [ -z "$SIZE" ] && SIZE="?"

  LABEL="${id} — ${NAME} — ${SIZE}"
  echo -e "${LABEL}\t${id}" >> "$MAP_FILE"
  echo "$LABEL" >> "$LABELS_FILE"
done

# Present the friendly list to the user
CHOICE="$(/usr/bin/osascript <<APPLESCRIPT
set disksText to do shell script "cat " & quoted form of "$LABELS_FILE"
set diskList to paragraphs of disksText
choose from list diskList with prompt "Select the WHOLE DISK to ERASE (destructive):" OK button name "Erase"
APPLESCRIPT
)" || true

if [ "$CHOICE" = "false" ] || [ -z "$CHOICE" ]; then
  exit $CANCELLED
fi

CHOICE_LABEL="$(echo "$CHOICE" | /usr/bin/sed 's/[{}]//g')"
TARGET_DISK="$(/usr/bin/awk -v lbl="$CHOICE_LABEL" -F'\t' 'BEGIN{found=0} $1==lbl{print $2; found=1; exit} END{if(!found)print""}' "$MAP_FILE")"

if [ -z "$TARGET_DISK" ]; then
  /usr/bin/osascript -e 'display dialog "Could not resolve the selected disk." buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

# Final destructive confirm
RESP="$(/usr/bin/osascript <<APPLESCRIPT
display dialog "ERASE all data on $TARGET_DISK and format as \"$VOL_NAME\"?\n\nThis CANNOT be undone." buttons {"Cancel","Erase"} default button "Erase" with icon caution
button returned of result
APPLESCRIPT
)" || true
[ "$RESP" = "Erase" ] || exit $CANCELLED

# Erase & name the volume (HFS+J for max compatibility; swap to APFS if you prefer).
# eraseDisk unmounts as part of its own operation -- an extra explicit
# `diskutil unmountDisk` before it was tried here and dropped again: on at
# least one real drive it caused the disk to fully detach rather than just
# unmount, invalidating the disk identifier for every subsequent retry
# ("Could not find disk for diskN"). Retrying eraseDisk itself is still
# worthwhile for a genuinely transient "resource busy" failure -- just
# without helping it along.
ERASE_LOG="$TMPDIR/erase.log"
ERASE_OK=0
for attempt in 1 2 3; do
  if /usr/sbin/diskutil eraseDisk JHFS+ "$VOL_NAME" "$TARGET_DISK" >"$ERASE_LOG" 2>&1; then
    ERASE_OK=1
    break
  fi
  /bin/sleep 2
done

if [ "$ERASE_OK" -ne 1 ]; then
  # Read the captured diskutil output via `do shell script` (quoted form of
  # the path) rather than embedding it directly in the AppleScript source --
  # diskutil's own error text can contain quotes/newlines that would
  # otherwise break the dialog's syntax.
  /usr/bin/osascript <<APPLESCRIPT >/dev/null
set errText to do shell script "cat " & quoted form of "$ERASE_LOG"
display dialog "Failed to erase $TARGET_DISK after 3 attempts:" & return & return & errText & return & return & "If this keeps happening, try unplugging and replugging the drive before running again." buttons {"OK"} default button 1
APPLESCRIPT
  exit 1
fi

USB_MOUNT="/Volumes/$VOL_NAME"
# Wait for mount -- a longer window than before (10s) since a retried erase
# may take a moment longer to settle before the volume actually mounts.
for i in $(seq 1 20); do
  [ -d "$USB_MOUNT" ] && break
  /bin/sleep 0.5
done
if [ ! -d "$USB_MOUNT" ]; then
  /usr/bin/osascript -e 'display dialog "Volume did not mount at '"$USB_MOUNT"'.\n\nThe erase reported success, but the volume never appeared. Try unplugging and replugging the drive." buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

echo "$USB_MOUNT"
