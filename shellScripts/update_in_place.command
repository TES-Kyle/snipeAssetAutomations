#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# BLOCK A — Config, paths, logging
###############################################################################
APP_NAME="Snipe Asset GUI"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"          # …/app/shellScripts
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"              # …/app
VENV="$APP_DIR/.venv"
PY="$VENV/bin/python"
BUILD_DIR="$APP_DIR/.build"
META="$BUILD_DIR/meta.json"
MANIFEST="$BUILD_DIR/manifest.txt"                   # previously installed tracked files list

LOG_DIR="$HOME/Library/Logs/$APP_NAME"
mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/update.log" 2>&1
echo "===== Update $(date) ====="
echo "USER: $(whoami)"
echo "APP_DIR: $APP_DIR"

alert() { /usr/bin/osascript -e 'display dialog '"$1"' buttons {"OK"} default button 1' >/dev/null 2>&1 || true; }
note()  { /usr/bin/osascript -e 'display dialog '"$1"' buttons {"OK"} giving up after 1' >/dev/null 2>&1 || true; }
as_admin() { /usr/bin/osascript <<APPLESCRIPT >/dev/null
do shell script "$1" with administrator privileges
APPLESCRIPT
}
q() { /usr/bin/python3 -c 'import shlex,sys;print(shlex.quote(sys.argv[1]))' "$1"; }

###############################################################################
# BLOCK A2 — Detect a partial install
###############################################################################
# A partial install (utilities/partialInstallBuilder.py) has an
# intentionally trimmed Key.py and intentionally cut-down routing tables.
# Block F below copies every git-tracked file from a fresh clone straight
# over the existing install, which would restore every routing entry
# regardless of what was originally selected -- Block C2/F2 further down
# re-derive and re-apply the same trim against the fresh code so that
# temporary un-trimming never becomes visible, and Block H/H2 are adjusted
# so they don't fight with or bypass that. PARTIAL_MANIFEST is read again
# (unchanged throughout, since it's gitignored and Block F never touches
# gitignored files) after Block F for the actual selection/regeneration.
PARTIAL_MANIFEST="$APP_DIR/utilities/partialInstallManifest.json"
IS_PARTIAL=0
[ -f "$PARTIAL_MANIFEST" ] && IS_PARTIAL=1
echo "IS_PARTIAL: $IS_PARTIAL"

###############################################################################
# BLOCK B — Read repo + branch from meta (require or reconstruct minimal)
###############################################################################
if [ ! -f "$META" ]; then
  REPO_URL_DEFAULT="https://github.com/TES-Kyle/snipeAssetAutomations"
  BRANCH_DEFAULT="main"
  mkdir -p "$BUILD_DIR"
  printf '{"repo_url":"%s","branch":"%s"}' "$REPO_URL_DEFAULT" "$BRANCH_DEFAULT" > "$META"
fi

REPO_URL="$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("repo_url",""))' "$META")"
BRANCH="$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("branch","main"))' "$META")"

if [ -z "$REPO_URL" ]; then
  alert '"No repository URL in meta.json — cannot update."'
  exit 1
fi
echo "REPO_URL: $REPO_URL"
echo "BRANCH: $BRANCH"

###############################################################################
# BLOCK C — Clone new code to temp
###############################################################################
TMPDIR="$(/usr/bin/mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

note '"Downloading update...\n\nThis may take a minute."'
git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$TMPDIR/repo"
NEW_SHA="$(git -C "$TMPDIR/repo" rev-parse HEAD || echo unknown)"
echo "NEW_SHA: $NEW_SHA"

###############################################################################
# BLOCK C2 — Partial install: re-derive the same trim against the fresh
#            code BEFORE touching APP_DIR at all
###############################################################################
# Checked here, before Block D/E/F ever modify anything, so a failure
# (fresh code needs a secret this machine doesn't have) leaves APP_DIR
# completely untouched instead of half-updated with routing tables
# temporarily restored to full. REGEN_DIR's contents get moved into place
# in Block F2, after Block F's full-tree copy has landed.
REGEN_DIR="$TMPDIR/regenerated"
if [ "$IS_PARTIAL" -eq 1 ]; then
  REGEN_DRIVER="$TMPDIR/regenerate_partial.py"
  cat > "$REGEN_DRIVER" <<'PYEOF'
import json
import sys

fresh_repo_root, existing_key_py, manifest_path, output_dir = sys.argv[1:5]
sys.path.insert(0, fresh_repo_root)
from utilities import partialInstallBuilder as pib

selection_labels = json.load(open(manifest_path)).get("selection", {})
try:
    result = pib.update_selection_in_place(fresh_repo_root, existing_key_py, selection_labels, output_dir)
except pib.UpdateNeedsRebuild as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(3)

if result["missing_labels"]:
    print(
        "Note: no longer found upstream, dropped from this update: "
        + ", ".join(result["missing_labels"]),
        file=sys.stderr,
    )
print(json.dumps({
    "included_key_names": sorted(result["included_key_names"]),
    "excluded_key_names": sorted(result["excluded_key_names"]),
}))
PYEOF

  set +e
  REGEN_OUT="$("$PY" "$REGEN_DRIVER" "$TMPDIR/repo" "$APP_DIR/utilities/Key.py" "$PARTIAL_MANIFEST" "$REGEN_DIR" 2>"$TMPDIR/regen_err.log")"
  REGEN_STATUS=$?
  set -e
  echo "REGEN_STATUS: $REGEN_STATUS"
  echo "--- regen stderr ---"
  cat "$TMPDIR/regen_err.log" || true
  echo "--- regen stdout ---"
  echo "$REGEN_OUT"

  if [ "$REGEN_STATUS" -eq 3 ]; then
    /usr/bin/osascript <<APPLESCRIPT >/dev/null
set errText to do shell script "cat " & quoted form of "$TMPDIR/regen_err.log"
display dialog "This update needs new credentials that are not on this installation:" & return & return & errText & return & return & "Rebuild and reinstall from a fresh Partial-Install USB with the same selection instead. No changes have been made." buttons {"OK"} default button 1
APPLESCRIPT
    exit 0
  elif [ "$REGEN_STATUS" -ne 0 ]; then
    alert '"Update failed while checking this partial install against the new code. No changes have been made. See ~/Library/Logs/Snipe Asset GUI/update.log for details."'
    exit 1
  fi
fi

###############################################################################
# BLOCK D — Preserve org files + meta before copy
###############################################################################
PRESERVE_DIR="$TMPDIR/preserve"
mkdir -p "$PRESERVE_DIR/utilities" "$PRESERVE_DIR/.build"

[ -f "$APP_DIR/utilities/Key.py" ]          && cp "$APP_DIR/utilities/Key.py" "$PRESERVE_DIR/utilities/Key.py"
[ -f "$APP_DIR/utilities/settings.json" ]  && cp "$APP_DIR/utilities/settings.json" "$PRESERVE_DIR/utilities/settings.json"
[ -f "$META" ]                             && cp "$META" "$PRESERVE_DIR/.build/meta.json"
[ -f "$MANIFEST" ]                         && cp "$MANIFEST" "$PRESERVE_DIR/.build/manifest.txt"

###############################################################################
# BLOCK E — Writable check
###############################################################################
NEED_ADMIN=0
if ! ( touch "$APP_DIR/.write_test" 2>/dev/null && rm -f "$APP_DIR/.write_test" ); then
  NEED_ADMIN=1
fi
echo "NEED_ADMIN: $NEED_ADMIN"

# Helper to mkdir/cp/rm with optional admin
mkdirp() {
  if [ "$NEED_ADMIN" -eq 0 ]; then
    /bin/mkdir -p "$1"
  else
    as_admin "/bin/mkdir -p $(q "$1")"
  fi
}
cp_file() {
  # $1 source $2 dest
  if [ "$NEED_ADMIN" -eq 0 ]; then
    /bin/cp -f "$1" "$2"
  else
    as_admin "/bin/cp -f $(q "$1") $(q "$2")"
  fi
}
rm_file() {
  if [ "$NEED_ADMIN" -eq 0 ]; then
    /bin/rm -f "$1"
  else
    as_admin "/bin/rm -f $(q "$1")"
  fi
}
chmodx() {
  if [ "$NEED_ADMIN" -eq 0 ]; then
    /bin/chmod +x "$1" 2>/dev/null || true
  else
    as_admin "/bin/chmod +x $(q "$1")"
  fi
}

###############################################################################
# BLOCK F — Build new manifest of tracked files and copy only those
###############################################################################
# Get list of tracked files relative to repo root
git -C "$TMPDIR/repo" ls-files > "$TMPDIR/new_manifest.txt"

# Copy each tracked file to APP_DIR, preserving directories
while IFS= read -r relpath; do
  # Skip safety exclusions even if accidentally tracked
  case "$relpath" in
    .venv/*|.build/*|.git/*|.python-runtime/*) continue ;;
  esac
  src="$TMPDIR/repo/$relpath"
  dst="$APP_DIR/$relpath"
  dst_dir="$(dirname "$dst")"
  mkdirp "$dst_dir"
  cp_file "$src" "$dst"
done < "$TMPDIR/new_manifest.txt"

# Ensure shell scripts remain executable if present
for sc in \
  "$APP_DIR/shellScripts/run_gui.command" \
  "$APP_DIR/shellScripts/update_in_place.command"
do
  [ -f "$sc" ] && chmodx "$sc"
done

###############################################################################
# BLOCK F2 — Partial install: re-apply the trim Block F just un-trimmed
###############################################################################
# Block F copied the fresh clone's full, untrimmed routing tables straight
# over the ones this install was built with. Put back the versions
# Block C2 already regenerated for the same selection, before anything
# else (including this app's own next launch) can see the untrimmed state.
if [ "$IS_PARTIAL" -eq 1 ]; then
  for relpath in \
    utilities/Key.py \
    utilities/partialInstallManifest.json \
    assetManagementFunctions/assetFunctionsRouting.py \
    otherManagementFunctions/otherFunctionsRouting.py \
    consisterizer/consisterizerScriptsRouting.py
  do
    src="$REGEN_DIR/$relpath"
    [ -f "$src" ] || continue
    mkdirp "$(dirname "$APP_DIR/$relpath")"
    cp_file "$src" "$APP_DIR/$relpath"
  done
  echo "Partial-install trim re-applied from $REGEN_DIR"
fi

###############################################################################
# BLOCK G — Remove files that were tracked before but are not tracked now
#            (ignores untracked/ignored files: they are left alone)
###############################################################################
if [ -f "$PRESERVE_DIR/.build/manifest.txt" ]; then
  # Build a set of previously-tracked files not in the new manifest
  /usr/bin/python3 - "$PRESERVE_DIR/.build/manifest.txt" "$TMPDIR/new_manifest.txt" <<'PY'
import sys
old_manifest, new_manifest = sys.argv[1], sys.argv[2]
old = set(p.strip() for p in open(old_manifest))
new = set(p.strip() for p in open(new_manifest))
to_delete = sorted(old - new)
for p in to_delete:
    print(p)
PY
  # Delete only those previously-tracked-now-removed files
  while IFS= read -r relpath; do
    [ -z "$relpath" ] && continue
    # Safety exclusions
    case "$relpath" in
      .venv/*|.build/*|.git/*|.python-runtime/*) continue ;;
    esac
    rm_file "$APP_DIR/$relpath"
  done < <(/usr/bin/python3 - "$PRESERVE_DIR/.build/manifest.txt" "$TMPDIR/new_manifest.txt" <<'PY'
import sys
old_manifest, new_manifest = sys.argv[1], sys.argv[2]
old = set(p.strip() for p in open(old_manifest))
new = set(p.strip() for p in open(new_manifest))
for p in sorted(old - new):
    print(p)
PY
)
fi

###############################################################################
# BLOCK H — Restore preserved org files and ensure .build exists
###############################################################################
mkdirp "$BUILD_DIR"
for f in Key.py settings.json; do
  if [ "$f" = "Key.py" ] && [ "$IS_PARTIAL" -eq 1 ]; then
    continue  # Block F2 already put the freshly regenerated trimmed Key.py in place
  fi
  [ -f "$PRESERVE_DIR/utilities/$f" ] || continue
  cp_file "$PRESERVE_DIR/utilities/$f" "$APP_DIR/utilities/$f"
done
[ -f "$PRESERVE_DIR/.build/meta.json" ] && cp_file "$PRESERVE_DIR/.build/meta.json" "$META"

###############################################################################
# BLOCK H2 — Override Key.py from external drive (optional, FULL INSTALLS ONLY)
###############################################################################
# Never for a partial install: this machine's Key.py is deliberately
# trimmed, and silently replacing it from whatever Key.py happens to be on
# any mounted volume (e.g. a full-install USB left plugged in) would
# defeat that without any confirmation.
if [ "$IS_PARTIAL" -eq 1 ]; then
  echo "Partial install: skipping external-drive Key.py override."
else
  EXT_KEY=""
  for vol in /Volumes/*; do
    [ -d "$vol" ] || continue
    if [ -f "$vol/Key.py" ]; then
      EXT_KEY="$vol/Key.py"
      break
    fi
    if [ -f "$vol/utilities/Key.py" ]; then
      EXT_KEY="$vol/utilities/Key.py"
      break
    fi
  done
  if [ -n "$EXT_KEY" ]; then
    echo "External Key.py found: $EXT_KEY"
    cp_file "$EXT_KEY" "$APP_DIR/utilities/Key.py"
  else
    echo "External Key.py not found in /Volumes/*"
  fi
fi

###############################################################################
# BLOCK I — Pip install (venv) if requirements changed or first run
###############################################################################
if [ -x "$PY" ] && [ -f "$APP_DIR/requirements.txt" ]; then
  # Best-effort upgrade; keep noise down
  if [ "$NEED_ADMIN" -eq 0 ]; then
    "$PY" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
    "$PY" -m pip install -r "$APP_DIR/requirements.txt"
  else
    as_admin "$(q "$PY") -m pip install --upgrade pip setuptools wheel"
    as_admin "$(q "$PY") -m pip install -r $(q "$APP_DIR/requirements.txt")"
  fi
fi

###############################################################################
# BLOCK J — Write updated meta + new manifest atomically
###############################################################################
META_NEW="$TMPDIR/meta_new.json"
/usr/bin/python3 -c 'import json,sys,datetime;
p,repo,branch,sha,out=sys.argv[1:6]
try:d=json.load(open(p))
except: d={}
d.update({"repo_url":repo,"branch":branch,"installed_sha":sha,"last_checked":datetime.datetime.now().isoformat()})
json.dump(d,open(out,"w"))' "$META" "$REPO_URL" "$BRANCH" "$NEW_SHA" "$META_NEW"

if [ "$NEED_ADMIN" -eq 0 ]; then
  /bin/mv -f "$META_NEW" "$META"
  /bin/mv -f "$TMPDIR/new_manifest.txt" "$MANIFEST"
else
  as_admin "/bin/mv -f $(q "$META_NEW") $(q "$META")"
  as_admin "/bin/mv -f $(q "$TMPDIR/new_manifest.txt") $(q "$MANIFEST")"
fi

###############################################################################
# BLOCK K — Done
###############################################################################
alert '"Update complete.\n\nPlease quit and relaunch the app."'
