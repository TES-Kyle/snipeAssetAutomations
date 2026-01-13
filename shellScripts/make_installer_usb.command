#!/bin/bash
# USB maker for macOS that shows friendly disk names (no PlistBuddy/mapfile)
set -e

APP_NAME="Snipe Asset GUI"
VOL_NAME="GUI Installer"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Sources (relative to repo)
INSTALLER_SRC="$SCRIPT_DIR/installer.command"          # required
ICON_SRC=""                                            # optional (resolved below)
KEY_SRC="$REPO_ROOT/utilities/Key.py"                  # optional
SETTINGS_SRC="$REPO_ROOT/utilities/settings.json"      # optional

# Sanity: installer must exist
if [ ! -f "$INSTALLER_SRC" ]; then
  /usr/bin/osascript -e 'display dialog "installer.command not found.\n\nExpected at:\n'"$INSTALLER_SRC"'" buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

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
  exit 0
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
[ "$RESP" = "Erase" ] || exit 0

# Erase & name the volume (HFS+J for max compatibility; swap to APFS if you prefer)
if ! /usr/sbin/diskutil eraseDisk JHFS+ "$VOL_NAME" "$TARGET_DISK"; then
  /usr/bin/osascript -e 'display dialog "Failed to erase '"$TARGET_DISK"'." buttons {"OK"} default button 1' >/dev/null
  exit 1
fi

USB_MOUNT="/Volumes/$VOL_NAME"
# Wait for mount
for i in 1 2 3 4 5; do
  [ -d "$USB_MOUNT" ] && break
  /bin/sleep 0.5
done
if [ ! -d "$USB_MOUNT" ]; then
  /usr/bin/osascript -e 'display dialog "Volume did not mount at '"$USB_MOUNT"'." buttons {"OK"} default button 1' >/dev/null
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

# Copy files
/bin/cp "$INSTALLER_SRC" "$USB_MOUNT/installer.command"
/bin/chmod +x "$USB_MOUNT/installer.command"
[ -n "$ICON_SRC" ]     && /bin/cp "$ICON_SRC" "$USB_MOUNT/icon.icns"
[ -f "$KEY_SRC" ]      && /bin/cp "$KEY_SRC" "$USB_MOUNT/Key.py"
[ -f "$SETTINGS_SRC" ] && /bin/cp "$SETTINGS_SRC" "$USB_MOUNT/settings.json"

# Clear quarantine on the USB contents (best effort)
 /usr/bin/xattr -dr com.apple.quarantine "$USB_MOUNT" >/dev/null 2>&1 || true

# Offer to eject
RESP="$(/usr/bin/osascript <<'APPLESCRIPT'
display dialog "USB prepared successfully.\n\nEject now?" buttons {"No","Eject"} default button "Eject"
button returned of result
APPLESCRIPT
)" || true
if [ "$RESP" = "Eject" ]; then
  /usr/sbin/diskutil eject "$TARGET_DISK" >/dev/null 2>&1 || true
fi

/usr/bin/osascript -e 'display dialog "USB is ready.\n\nCopied:\n• installer.command\n• (optional) icon.icns\n• (optional) Key.py\n• (optional) settings.json" buttons {"OK"} default button 1' >/dev/null
