import json
import logging
import os
import re
from datetime import datetime

import tkinter as tk
from tkinter import messagebox

from utilities.labelPrinting import createImage
from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings
from utilities.otherApiBits import *

logger = logging.getLogger(__name__)

"""
Drop-off automation (shared state via Snipe-IT asset Notes) + Help/Box State UI + Reset + Check-In

- Status always -> ID 5
- Hinge removed everywhere
- No notes appended to the *device* asset
- 6 box streams: SG, SM, SD, WG, WM, WD
  * map damage: good=0, mild/medium=1, damaged/repair=2|3
- Box label: "<STREAM>-NN" (2 digits; 3 digits at 100+)
- Shared box tallies live in the Notes of a dedicated Snipe-IT asset (tag in settings)
- Pull state -> assign new label -> push state (tight window)
- **Checks asset in** from the user via POST /hardware/{id}/checkin (Retry/Cancel)
- Retry/Cancel messageboxes for all network calls
- Help screen: shows current state, updates capacity, explains damage levels,
  provides "Reset All", and shows a mapping for the two-letter stream acronyms.

settings.json must include (located at ../utilities/settings.json relative to this file):
  {
    "boxStateAssetTag": "BOX-STATE-TRACKER",
    "defaultBoxCapacity": "12",
    ... other existing keys ...
  }
"""

# ----------------------------
# Constants / regex
# ----------------------------
STREAMS = ["SG", "SM", "SD", "WG", "WM", "WD"]
STREAM_DESCRIPTIONS = {
    "SG": "Senior Good",
    "SM": "Senior Mild/Medium",
    "SD": "Senior Damaged/Needs Repair",
    "WG": "Withdrawal Good",
    "WM": "Withdrawal Mild/Medium",
    "WD": "Withdrawal Damaged/Needs Repair",
}

# Matches either "box capacity <N>" or "<STREAM> box <B> [computer <C>]"
_STATE_LINE_RE = re.compile(
    r"""
    (?ix)
    \b(?P<key>
        box\ capacity
        |sg\ box|sm\ box|sd\ box|wg\ box|wm\ box|wd\ box
    )
    \s+
    (?P<num1>\d+)
    (?:\s+computer\s+(?P<num2>\d+))?
    """,
    re.IGNORECASE | re.VERBOSE
)

# Notes appended during drop-off. Use {asset_tag} anywhere to insert the main device's tag.
LOST_ASSET_NOTE = "\nThis asset was marked lost during drop off of asset {asset_tag}."    # <-- set your note text here
CHARGER_ASSET_NOTE = "\nThis charger was checked in during drop off of asset {asset_tag}." # <-- set your note text here

HELP_TEXT = (
    "What this does:\n"
    "• Checks the asset in (if currently checked out) and sets Status to 5 on drop-off\n"
    "• Assigns a box label based on type & damage: SG/SM/SD/WG/WM/WD\n"
    "• Labels are STREAM-NN (2 digits; 3 digits at 100+)\n"
    "• Shared box tallies are stored in the Notes of a tracker asset\n\n"
    "Damage levels:\n"
    "• Little/None — light enough damage that it would be suitable to give to a new 8th grade student.\n"
    "• Mild/Medium — enough cosmetic damage to not give to a new eighth grader, but still fully functional.\n"
    "• Significant — functionality is impacted but repair is possible.\n"
    "• Irreparable — the computer is so damaged or mangled that it’s either impossible or not sensible to repair."
)

# ----------------------------
# Settings helpers
# ----------------------------
def _settings_path():
    """Return the path to utilities/settings.json.

    Returns:
        Absolute path string to the settings file.
    """
    # settings.json is one directory up, then in 'utilities'
    # <this_file_dir>/../utilities/settings.json
    base = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(os.path.dirname(base), "utilities", "settings.json")

def _load_settings():
    """Load settings.json for the drop-off workflow.

    Returns:
        Dict of settings values or {} on failure.
    """
    configure_logging()
    try:
        # Read settings from disk with a fallback on any failure.
        with open(_settings_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to read settings.json for drop-off workflow")
        messagebox.showerror(
            "Settings Error",
            "Could not read settings.json at ../utilities/settings.json relative to this module."
        )
        return {}

def _save_settings_key(key: str, value):
    """Best-effort write-back to settings.json to keep defaults in sync."""
    configure_logging()
    try:
        p = _settings_path()
        # Load existing settings, update one key, and write back.
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data[key] = str(value)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.exception("Failed to update settings.json key %s", key)
        messagebox.showwarning("Settings Write Warning", f"Couldn't update settings.json ({key}):\n{e}")
        return False

def _get_box_state_asset_tag_and_capacity():
    """Return tracker asset tag and box capacity from settings.

    Returns:
        (tag, capacity) tuple with validated defaults.
    """
    configure_logging()
    s = _load_settings()
    tag = s.get("boxStateAssetTag", "").strip()
    cap = s.get("defaultBoxCapacity", "12")
    try:
        cap = int(cap)
    except Exception:
        cap = 12
    if cap < 1:
        cap = 1
    if not tag:
        logger.error("settings.json missing boxStateAssetTag")
        messagebox.showerror("Settings Error", "settings.json is missing 'boxStateAssetTag'.")
    return tag, cap


def _get_dropoff_status_ids():
    """Read configured drop-off status IDs from settings.

    Returns:
        (drop_status_id, pending_status_id, lost_status_id, charger_status_id) tuple,
        or None if any key is missing or not a valid integer.
    """
    settings = get_settings()
    _KEYS = [
        ("dropOffStatusId",      "drop-off"),
        ("dropOffPendingStatusId","pending drop-off"),
        ("dropOffLostStatusId",  "lost asset"),
        ("dropOffChargerStatusId","charger"),
        ("macBookCategoryID", "category"),
    ]
    values = []
    for key, label in _KEYS:
        raw = settings.get(key)
        try:
            values.append(int(raw))
        except (TypeError, ValueError):
            msg = f"settings.json key '{key}' ({label} status ID) is missing or not a valid integer (got {raw!r})."
            logger.error(msg)
            messagebox.showerror("Settings Error", msg)
            return None
    return tuple(values)


def _get_dropoff_field_keys():
    """Read configured custom field keys for drop-off metadata.

    Returns:
        Tuple of (charger_field_key, cord_field_key, box_field_key).
    """
    settings = get_settings()
    # Normalize and fallback to default field keys for each metadata field.
    charger_key = settings.get("dropOffChargerFieldKey", "_snipeit_chargeringoodcondition_6").strip()
    cord_key = settings.get("dropOffCordFieldKey", "_snipeit_cordingoodcondition_11").strip()
    box_key = settings.get("dropOffBoxFieldKey", "_snipeit_box_number_5").strip()
    if not charger_key:
        charger_key = "_snipeit_chargeringoodcondition_6"
    if not cord_key:
        cord_key = "_snipeit_cordingoodcondition_11"
    if not box_key:
        box_key = "_snipeit_box_number_5"
    return charger_key, cord_key, box_key

# ----------------------------
# Snipe-IT helpers (tracker asset)
# ----------------------------
def _get_asset_by_tag_with_retry(asset_tag: str):
    """
    GET /hardware/bytag/{asset_tag}
    Returns (ok: bool, data: dict or None)
    """
    configure_logging()
    url = Key.API_URL_Base + "hardware/bytag/" + str(asset_tag)
    while True:
        try:
            r = requests.get(url, headers=get_headers(), timeout=20)
            if 200 <= r.status_code < 300:
                logger.info("Loaded asset by tag for tracker: %s", asset_tag)
                return True, r.json()
            else:
                try:
                    msg = r.json()
                except Exception:
                    msg = r.text
                logger.error("Tracker load failed for %s (HTTP %s): %s", asset_tag, r.status_code, msg)
                retry = messagebox.askretrycancel(
                    "Load Failed",
                    f"Failed to load asset by tag '{asset_tag}' (HTTP {r.status_code}).\n"
                    f"{str(msg)[:500]}\n\nRetry?"
                )
                if not retry:
                    return False, None
        except Exception as e:
            logger.exception("Network error loading asset tag %s", asset_tag)
            retry = messagebox.askretrycancel("Network Error", f"Error loading asset tag '{asset_tag}':\n{e}\n\nRetry?")
            if not retry:
                return False, None

def _put_asset_notes_with_retry(asset_id: str, new_notes: str):
    """
    PUT /hardware/{id} with just the 'notes' field.
    Returns True on success, False if user cancels.
    """
    configure_logging()
    url = Key.API_URL_Base + "hardware/" + str(asset_id)
    payload = {"notes": new_notes}
    while True:
        try:
            r = requests.put(url, json=payload, headers=get_headers(), timeout=20)
            if 200 <= r.status_code < 300:
                logger.info("Updated tracker notes for asset %s", asset_id)
                return True
            else:
                try:
                    msg = r.json()
                except Exception:
                    msg = r.text
                logger.error("Tracker notes update failed for %s (HTTP %s): %s", asset_id, r.status_code, msg)
                retry = messagebox.askretrycancel(
                    "Update Failed",
                    f"Failed to update tracker notes (HTTP {r.status_code}).\n"
                    f"{str(msg)[:500]}\n\nRetry?"
                )
                if not retry:
                    return False
        except Exception as e:
            logger.exception("Network error updating tracker notes for %s", asset_id)
            retry = messagebox.askretrycancel("Network Error", f"Error updating tracker notes:\n{e}\n\nRetry?")
            if not retry:
                return False

# ----------------------------
# State (parse/format/validate) in tracker asset Notes
# ----------------------------
def _init_default_state(capacity: int):
    """Initialize the tracker state with default counters.

    Args:
        capacity: Items per box.

    Returns:
        State dict with per-stream counters.
    """
    return {
        "capacity": capacity,
        "streams": {code: {"box": 1, "count": 0} for code in STREAMS},
    }

def _format_state_line(state) -> str:
    """Serialize the state into a single-line representation.

    Args:
        state: Parsed tracker state dict.

    Returns:
        One-line string suitable for notes storage.
    """
    parts = [f"box capacity {int(state['capacity'])}"]
    for code in STREAMS:
        s = state["streams"][code]
        parts.append(f"{code} box {int(s['box'])} computer {int(s['count'])}")
    return "; ".join(parts)

def _format_state_notes(state) -> str:
    """Wrap the state line with a header and timestamp.

    Args:
        state: Parsed tracker state dict.

    Returns:
        Notes text with header + state line.
    """
    header = f"# BOX STATE (updated {datetime.now().isoformat(timespec='seconds')})"
    return header + "\n" + _format_state_line(state) + "\n"

def _detect_malformed_notes(notes_text: str) -> bool:
    """
    Return True if notes_text is non-empty but doesn't look like our state.
    Criteria: must contain 'box capacity' and at least one '<STREAM> box'.
    """
    if not isinstance(notes_text, str):
        return False
    text = notes_text.strip()
    if not text:
        return False
    if "box capacity" not in text.lower():
        return True
    if not re.search(r"\b(SG|SM|SD|WG|WM|WD)\s+box\b", text, re.IGNORECASE):
        return True
    return False

def _parse_state_from_notes(notes_text: str, default_capacity: int):
    """
    Parse a forgiving single-line state; tolerate spacing/semicolons/newlines.
    If empty string -> default blank state (caller may push it).
    If malformed but non-empty -> we still parse what we can; caller warns.
    """
    if not isinstance(notes_text, str) or not notes_text.strip():
        return _init_default_state(default_capacity)

    lines = [ln.strip() for ln in notes_text.splitlines() if ln.strip()]
    if not lines:
        return _init_default_state(default_capacity)

    state_line = None
    for ln in reversed(lines):
        if "box capacity" in ln.lower():
            state_line = ln
            break
    if state_line is None:
        state_line = lines[-1]

    state = _init_default_state(default_capacity)

    tokens = re.split(r"[;\n]+", state_line)
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        m = _STATE_LINE_RE.search(tok)
        if not m:
            continue
        key = m.group("key").lower()
        n1 = int(m.group("num1"))
        n2 = m.group("num2")
        if key == "box capacity":
            state["capacity"] = max(1, n1)
        else:
            code = key.split()[0].upper()
            box_num = max(1, n1)
            prev_count = state["streams"].get(code, {"count": 0})["count"]
            count_num = int(n2) if n2 is not None else prev_count
            count_num = max(0, count_num)
            state["streams"][code] = {"box": box_num, "count": count_num}

    for code in STREAMS:
        state["streams"].setdefault(code, {"box": 1, "count": 0})
        state["streams"][code]["box"] = max(1, state["streams"][code]["box"])
        state["streams"][code]["count"] = max(0, state["streams"][code]["count"])

    return state

def _format_seq(box_number: int) -> str:
    """Format box numbers with leading zeros (2 or 3 digits)."""
    return f"{box_number:02d}" if box_number < 100 else f"{box_number:03d}"

def _assign_from_remote_state(stream_code: str, default_capacity: int):
    """
    Pull tracker notes, validate/normalize, compute new label, push notes (tight window).
    - If notes empty: initialize fresh state and push it, then continue.
    - If notes malformed: warn and offer to reset; if declined, cancel.
    Returns (ok: bool, box_label: str or None).
    """
    configure_logging()
    tracker_tag, fallback_cap = _get_box_state_asset_tag_and_capacity()
    if not tracker_tag:
        return False, None

    logger.info("Assigning box for stream %s", stream_code)
    ok, tracker = _get_asset_by_tag_with_retry(tracker_tag)
    if not ok or not tracker:
        return False, None

    tracker_id = str(tracker["id"])
    tracker_notes = tracker.get("notes", "")
    empty_notes = (not isinstance(tracker_notes, str)) or (not tracker_notes.strip())
    malformed = _detect_malformed_notes(tracker_notes)

    if empty_notes:
        state = _init_default_state(default_capacity or fallback_cap)
        if not _put_asset_notes_with_retry(tracker_id, _format_state_notes(state)):
            return False, None
    else:
        if malformed:
            do_reset = messagebox.askyesno(
                "Tracker Note Looks Wrong",
                "The tracker asset's note exists but doesn't match the expected format.\n\n"
                "Reset it to a clean state now?\n\n"
                "Yes = reset to default (box 1 / computer 0 for all streams)\n"
                "No = cancel this drop-off"
            )
            if not do_reset:
                return False, None
            state = _init_default_state(default_capacity or fallback_cap)
            if not _put_asset_notes_with_retry(tracker_id, _format_state_notes(state)):
                return False, None
        else:
            state = _parse_state_from_notes(tracker_notes, default_capacity or fallback_cap)

    cap = int(state.get("capacity") or fallback_cap)
    if cap < 1:
        cap = fallback_cap

    stream_code = stream_code.upper()
    s = state["streams"].get(stream_code, {"box": 1, "count": 0})

    if s["count"] >= cap:
        s["box"] += 1
        s["count"] = 0
    s["count"] += 1
    state["streams"][stream_code] = s

    new_notes = _format_state_notes(state)
    ok = _put_asset_notes_with_retry(tracker_id, new_notes)
    if not ok:
        return False, None

    return True, f"{stream_code}-{_format_seq(s['box'])}"

# ----------------------------
# PUT/POST (device) with Retry/Cancel
# ----------------------------
def _checkin_asset_with_retry(id, note="Checked in via Drop-Off automation"):
    """
    POST /hardware/{id}/checkin
    - Treats "already checked in/not checked out" responses as non-fatal and continues.
    Returns True if checked in or already in, False if user cancels on other errors.
    """
    configure_logging()
    url = Key.API_URL_Base + "hardware/" + str(id) + "/checkin"
    payload = {"note": note}
    while True:
        try:
            r = requests.post(url, json=payload, headers=get_headers(), timeout=20)
            if 200 <= r.status_code < 300:
                logger.info("Checked in asset %s (drop-off)", id)
                return True
            else:
                # If it's a known "not checked out" case, continue without blocking
                try:
                    msg = r.json()
                except Exception:
                    msg = r.text
                text = str(msg).lower()
                if "not checked out" in text or "already checked in" in text:
                    # Non-fatal; proceed
                    logger.info("Asset %s already checked in; continuing.", id)
                    return True
                logger.error("Check-in failed for %s (HTTP %s): %s", id, r.status_code, msg)
                retry = messagebox.askretrycancel(
                    "Check-In Failed",
                    f"Failed to check in asset (HTTP {r.status_code}).\n"
                    f"{str(msg)[:500]}\n\nRetry?"
                )
                if not retry:
                    return False
        except Exception as e:
            logger.exception("Network error during check-in for %s", id)
            retry = messagebox.askretrycancel(
                "Network Error",
                f"Error checking in asset:\n{e}\n\nRetry?"
            )
            if not retry:
                return False

def _update_asset_with_retry(id, assetTag, statusID, modelID, chargerCond, cordCond, boxLabel, existingNotes):
    """
    PUT /hardware/{id} to set status=5, custom fields, and preserve existing notes.
    """
    configure_logging()
    putURL = Key.API_URL_Base + "hardware/" + str(id)
    charger_key, cord_key, box_key = _get_dropoff_field_keys()
    payload = {
        "asset_tag": assetTag,
        "status_id": statusID,
        "model_id": modelID,
        "notes": existingNotes,
        charger_key: "y" if chargerCond == "y" else "n",
        cord_key: "y" if cordCond == "y" else "n",
        box_key: boxLabel
    }
    logger.debug(
        "Drop-off payload keys: charger=%s cord=%s box=%s",
        charger_key,
        cord_key,
        box_key,
    )

    while True:
        try:
            response = requests.put(putURL, json=payload, headers=get_headers(), timeout=20)
            if 200 <= response.status_code < 300:
                logger.info("Updated drop-off asset %s (box=%s)", id, boxLabel)
                return True
            else:
                try:
                    msg = response.json()
                except Exception:
                    msg = response.text
                logger.error("Drop-off update failed for %s (HTTP %s): %s", assetTag, response.status_code, msg)
                retry = messagebox.askretrycancel(
                    "Update Failed",
                    f"Failed to update asset {assetTag} (HTTP {response.status_code}).\n"
                    f"{str(msg)[:500]}\n\nRetry?"
                )
                if not retry:
                    return False
        except Exception as e:
            logger.exception("Network error updating asset %s", assetTag)
            retry = messagebox.askretrycancel(
                "Network Error",
                f"Error updating asset {assetTag}:\n{e}\n\nRetry?"
            )
            if not retry:
                return False

def _update_asset_status_and_notes_with_retry(asset_id, asset_tag, status_id, model_id, new_notes):
    """PUT /hardware/{id} to set a status and notes, leaving all other fields unchanged."""
    configure_logging()
    url = Key.API_URL_Base + "hardware/" + str(asset_id)
    payload = {
        "asset_tag": asset_tag,
        "status_id": status_id,
        "model_id": model_id,
        "notes": new_notes,
    }
    while True:
        try:
            r = requests.put(url, json=payload, headers=get_headers(), timeout=20)
            if 200 <= r.status_code < 300:
                logger.info("Updated status/notes for asset %s (status=%s)", asset_tag, status_id)
                return True
            else:
                try:
                    msg = r.json()
                except Exception:
                    msg = r.text
                logger.error("Status/notes update failed for %s (HTTP %s): %s", asset_tag, r.status_code, msg)
                retry = messagebox.askretrycancel(
                    "Update Failed",
                    f"Failed to update asset {asset_tag} (HTTP {r.status_code}).\n"
                    f"{str(msg)[:500]}\n\nRetry?"
                )
                if not retry:
                    return False
        except Exception as e:
            logger.exception("Network error updating status/notes for %s", asset_tag)
            retry = messagebox.askretrycancel(
                "Network Error",
                f"Error updating asset {asset_tag}:\n{e}\n\nRetry?"
            )
            if not retry:
                return False

# ----------------------------
# Help / Box State UI
# ----------------------------
def _open_help_dialog(parent):
    """
    Shows:
      - Tracker asset tag
      - Current box state (live from tracker Notes)
      - Capacity editor (updates tracker + settings.json)
      - Reset All: sets all streams to box 1 / computer 0 (keeps capacity)
      - How-it-works + damage level guidance
      - Stream acronym key (SG/SM/SD/WG/WM/WD)
    """
    settings = _load_settings()
    tracker_tag = settings.get("boxStateAssetTag", "").strip()
    try:
        default_cap = int(settings.get("defaultBoxCapacity", 12))
    except Exception:
        default_cap = 12

    dlg = tk.Toplevel(parent)
    dlg.title("Drop-Off: Help & Box State")
    dlg.transient(parent)
    dlg.grab_set()

    # Tracker tag
    tk.Label(dlg, text=f"Tracker asset tag: {tracker_tag or '(missing in settings.json)'}").pack(anchor="w", padx=12, pady=(12, 4))

    # Stream key line
    stream_key = "Streams: " + ", ".join([f"{k}={v}" for k, v in STREAM_DESCRIPTIONS.items()])
    tk.Label(dlg, text=stream_key).pack(anchor="w", padx=12, pady=(0, 8))

    # State frame
    state_frame = tk.LabelFrame(dlg, text="Current box state (live)")
    state_frame.pack(fill="x", padx=12, pady=8)

    state_var = tk.StringVar(value="(loading...)")
    state_label = tk.Label(state_frame, textvariable=state_var, anchor="w", justify="left", wraplength=600)
    state_label.pack(fill="x", padx=10, pady=8)

    def refresh_state():
        """Fetch tracker notes and update the displayed state."""
        if not tracker_tag:
            messagebox.showerror("Tracker Missing", "boxStateAssetTag is not set in settings.json.")
            return
        ok, tracker = _get_asset_by_tag_with_retry(tracker_tag)
        if not ok or not tracker:
            return
        notes = tracker.get("notes", "")
        if _detect_malformed_notes(notes):
            messagebox.showwarning(
                "Note Format Warning",
                "The tracker note exists but doesn't match the expected format.\n"
                "You can use 'Reset All' to initialize a clean state."
            )
        state = _parse_state_from_notes(notes, default_cap)
        state_var.set(_format_state_line(state))
        cap_entry_var.set(str(state.get("capacity", default_cap)))

    tk.Button(state_frame, text="Refresh", command=refresh_state).pack(padx=10, pady=(0, 10), anchor="e")

    # Capacity editor
    cap_frame = tk.LabelFrame(dlg, text="Box capacity")
    cap_frame.pack(fill="x", padx=12, pady=8)
    tk.Label(cap_frame, text="Capacity (items per box):").pack(side="left", padx=10, pady=8)
    cap_entry_var = tk.StringVar(value=str(default_cap))
    cap_entry = tk.Entry(cap_frame, textvariable=cap_entry_var, width=6)
    cap_entry.pack(side="left", padx=(0, 10), pady=8)

    def save_capacity():
        """Save capacity changes to the tracker and settings."""
        try:
            new_cap = int(cap_entry_var.get())
        except Exception:
            messagebox.showerror("Invalid Capacity", "Please enter a whole number (≥1).")
            return
        if new_cap < 1:
            messagebox.showerror("Invalid Capacity", "Capacity must be at least 1.")
            return

        tt, fallback_cap = _get_box_state_asset_tag_and_capacity()
        if not tt:
            return
        ok, tracker = _get_asset_by_tag_with_retry(tt)
        if not ok or not tracker:
            return

        tracker_id = str(tracker["id"])
        state = _parse_state_from_notes(tracker.get("notes", ""), fallback_cap)
        state["capacity"] = new_cap
        new_notes = _format_state_notes(state)
        ok = _put_asset_notes_with_retry(tracker_id, new_notes)
        if not ok:
            return

        _save_settings_key("defaultBoxCapacity", new_cap)

        state_var.set(_format_state_line(state))
        # messagebox.showinfo("Capacity Updated", f"Capacity set to {new_cap}.")

    tk.Button(cap_frame, text="Save", command=save_capacity).pack(side="left", padx=10, pady=8)

    # Reset All
    reset_frame = tk.Frame(dlg)
    reset_frame.pack(fill="x", padx=12, pady=(0, 8))
    def reset_all():
        """Reset tracker state to defaults after confirmation."""
        if not messagebox.askyesno(
            "Reset All Streams",
            "Are you sure you want to reset all streams to box 1 / computer 0?\n\nThis cannot be undone."
        ):
            return
        tt, fallback_cap = _get_box_state_asset_tag_and_capacity()
        if not tt:
            return
        ok, tracker = _get_asset_by_tag_with_retry(tt)
        if not ok or not tracker:
            return
        tracker_id = str(tracker["id"])

        notes = tracker.get("notes", "")
        st = _parse_state_from_notes(notes, fallback_cap)
        cap = st.get("capacity", fallback_cap)

        new_state = _init_default_state(cap)
        new_notes = _format_state_notes(new_state)
        ok = _put_asset_notes_with_retry(tracker_id, new_notes)
        if not ok:
            return

        state_var.set(_format_state_line(new_state))
        # messagebox.showinfo("Reset Complete", "All streams reset to box 1 / computer 0 (capacity unchanged).")

    tk.Button(reset_frame, text="Reset All Streams", command=reset_all).pack(side="left", padx=10, pady=8)

    # Help text
    help_frame = tk.LabelFrame(dlg, text="How it works & damage levels")
    help_frame.pack(fill="both", expand=True, padx=12, pady=(8, 12))
    tk.Label(help_frame, text=HELP_TEXT, justify="left", anchor="nw", wraplength=620).pack(fill="both", expand=True, padx=10, pady=8)

    # Buttons
    btns = tk.Frame(dlg)
    btns.pack(fill="x", padx=12, pady=(0, 12))
    tk.Button(btns, text="Close", command=dlg.destroy).pack(side="right")

    # Initial refresh
    refresh_state()

    # Center dialog
    dlg.update_idletasks()
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    ww = dlg.winfo_width()
    wh = dlg.winfo_height()
    cx = int((sw / 2) - (ww / 2))
    cy = int((sh / 2) - (wh / 2))
    dlg.geometry(f"+{cx}+{cy}")

# ----------------------------
# UI + main flow
# ----------------------------
def dropOff(asset_tag):
    """Run the drop-off workflow for an asset tag.

    Args:
        asset_tag: Asset tag to process.

    Returns:
        Status message string for the main UI.
    """
    configure_logging()
    logger.info("Starting drop-off for asset %s", asset_tag)
    def process_dropoff(assetData):
        """Validate answers, update state, and apply drop-off updates."""
        # Validate required fields
        if charger.get() < 0 or drop.get() < 0:
            messagebox.showerror("Error", "Dumb dumb, answer all the questions!")
            return

        charger_asset_tag = charger_tag_var.get().strip()
        if charger_asset_tag and not re.fullmatch(r"\d{4,5}", charger_asset_tag):
            messagebox.showerror("Invalid Charger Tag", "Charger asset tag must be 4 or 5 digits with no other characters.")
            return

        seniorStatus = drop.get()         # 1=Senior, 0=Withdrawal
        q_charger = charger.get()         # 1 yes, 0 no
        q_cord = cord.get()               # 1 yes, 0 no
        q_damage = repair.get()           # 0 none, 1 mild, 2 significant, 3 irreparable
        logger.debug(
            "Drop-off answers for %s: senior=%s charger=%s cord=%s damage=%s",
            asset_tag,
            seniorStatus,
            q_charger,
            q_cord,
            q_damage,
        )

        # Map to 'y'/'n'
        charger_str = "y" if q_charger == 1 else "n"
        cord_str = "y" if q_cord == 1 else "n"

        # Status IDs from settings
        _ids = _get_dropoff_status_ids()
        if _ids is None:
            return
        status_id, pending_status_id, lost_status_id, charger_status_id, _macbook_category_id = _ids

        # Determine stream (SG/SM/SD/WG/WM/WD)
        if seniorStatus == 1:  # Senior
            if q_damage == 0:
                stream = "SG"
            elif q_damage == 1:
                stream = "SM"
            else:  # 2 or 3
                stream = "SD"
        else:  # Withdrawal
            if q_damage == 0:
                stream = "WG"
            elif q_damage == 1:
                stream = "WM"
            else:
                stream = "WD"

        # Pull state → assign → push (tight window)
        settings_data = _load_settings()
        try:
            default_cap = int(settings_data.get("defaultBoxCapacity", 12))
        except Exception:
            default_cap = 12
        ok, box_label = _assign_from_remote_state(stream, default_cap)
        if not ok or not box_label:
            return  # canceled or failed
        logger.info("Drop-off stream assigned for %s: %s -> %s", asset_tag, stream, box_label)

        # **Check the asset in** (Retry/Cancel; non-fatal if already checked in)
        if not _checkin_asset_with_retry(str(assetData["id"])):
            return

        # Build the note to append to the main device.
        lost_tags = [tag for cb_var, tag in check_vars if cb_var.get()]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note_parts = [f"This device was dropped off at {now_str}."]
        if charger_asset_tag:
            note_parts.append(f"Charger asset {charger_asset_tag} was returned during dropoff.")
        if lost_tags:
            tag_list = ", ".join(lost_tags)
            verb = "was" if len(lost_tags) == 1 else "were"
            noun = "Asset" if len(lost_tags) == 1 else "Assets"
            note_parts.append(f"{noun} {tag_list} {verb} marked lost during dropoff.")
        device_note = "\n".join(note_parts)
        existing_device_notes = (assetData.get("notes") or "").rstrip()
        full_device_notes = (existing_device_notes + "\n" + device_note) if existing_device_notes else device_note

        # Update the actual device asset with Retry/Cancel
        if not _update_asset_with_retry(
            id=str(assetData["id"]),
            assetTag=assetData["asset_tag"],
            statusID=status_id,
            modelID=assetData["model"]["id"],
            chargerCond=charger_str,
            cordCond=cord_str,
            boxLabel=box_label,
            existingNotes=full_device_notes
        ):
            return

        # Print label (4 lines used)
        var1 = assetData["asset_tag"]
        var2 = assetData["serial"]
        try:
            var3 = assetData["custom_fields"]["batteryData"]["value"]
        except KeyError:
            var3 = "No Battery Data"
        var4 = f"Box: {box_label}"

        createImage([str(var1), var2, str(var3), str(var4), ""])
        logger.info("Drop-off completed for %s (box=%s)", asset_tag, box_label)

        # Process any assets the user marked as lost.
        for cb_var, lost_tag in check_vars:
            if not cb_var.get():
                continue
            logger.info("Processing lost asset %s", lost_tag)
            _var_list, lost_data = getAssetInfo(lost_tag, allow_missing=False)
            if not lost_data or lost_data.get("status") == "error":
                messagebox.showwarning("Lost Asset", f"Could not fetch data for {lost_tag} — skipping.")
                continue
            lost_id = str(lost_data["id"])
            lost_model_id = (lost_data.get("model") or {}).get("id")
            existing_notes = (lost_data.get("notes") or "").rstrip()
            note_text = LOST_ASSET_NOTE.format(asset_tag=asset_tag)
            appended_notes = (existing_notes + "\n" + note_text) if existing_notes else note_text
            # Check in first (non-fatal if already checked in), then set status 6 + note.
            _checkin_asset_with_retry(lost_id)
            _update_asset_status_and_notes_with_retry(lost_id, lost_tag, lost_status_id, lost_model_id, appended_notes)

        # Process charger asset if a tag was entered.
        if charger_asset_tag:
            logger.info("Processing charger asset %s", charger_asset_tag)
            _var_list, charger_data = getAssetInfo(charger_asset_tag, allow_missing=False)
            if not charger_data or charger_data.get("status") == "error":
                messagebox.showwarning("Charger Asset", f"Could not fetch data for charger {charger_asset_tag} — skipping.")
            else:
                charger_asset_id = str(charger_data["id"])
                charger_model_id = (charger_data.get("model") or {}).get("id")
                charger_existing_notes = (charger_data.get("notes") or "").rstrip()
                charger_note_text = CHARGER_ASSET_NOTE.format(asset_tag=asset_tag)
                charger_appended_notes = (charger_existing_notes + "\n" + charger_note_text) if charger_existing_notes else charger_note_text
                _checkin_asset_with_retry(charger_asset_id)
                _update_asset_status_and_notes_with_retry(charger_asset_id, charger_asset_tag, charger_status_id, charger_model_id, charger_appended_notes)

        dropoff_window.destroy()

    # Fetch asset and confirm status
    var_list, assetData = getAssetInfo(asset_tag)
    proceed = False

    _ids = _get_dropoff_status_ids()
    if _ids is None:
        return f"Drop-off aborted: status ID settings error for {asset_tag}."
    _status_id, pending_status_id, _lost_status_id, _charger_status_id, _macbook_category_id = _ids

    if assetData["category"]["id"] != _macbook_category_id:
        proceed = messagebox.askyesno(
            title="Not A MacBook!",
            message='This asset is not a MacBook\n\nProceed anyway?'
        )
        logger.info("Drop-off category override prompt for %s: %s", asset_tag, proceed)
    elif assetData["status_label"]["id"] != pending_status_id:
        proceed = messagebox.askyesno(
            title="Proceed?",
            message='This asset is not "Pending Drop-Off"\n\nProceed anyway?'
        )
        logger.info("Drop-off status override prompt for %s: %s", asset_tag, proceed)
    else:
        proceed = True

    if proceed:
        # Window
        dropoff_window = tk.Toplevel()

        #Info Frame
        info_frame, _check_vars = build_asset_info_frame(dropoff_window, var_list, include_checkboxes=False, padx=5, pady=5)
        info_frame.grid(row=0, column=0, sticky='nsew')

        # Dropoff Frame (return fields).
        dropoff_frame = tk.Frame(dropoff_window)
        dropoff_frame.grid(row=0, column=1, sticky='nsew')

        # User Assets Frame
        check_vars = []
        user_id = (assetData.get('assigned_to', {}) or {}).get('id')
        if user_id:
            ua_frame, check_vars = build_user_asset_list_frame(dropoff_window, user_id, include_checkboxes=True, checkbox_header="Mark as Lost")
            ua_frame.grid(row=1, column=0, sticky='nsew', columnspan=2)

        # Drop-Off Type
        type_frame = tk.Frame(dropoff_frame)
        type_frame.pack(fill='x', padx=10, pady=5)
        type_label = tk.Label(type_frame, text="Drop-Off Type:")
        type_label.pack(side='left')
        drop = tk.IntVar(value=-1)
        senior = tk.Radiobutton(type_frame, text="Senior", variable=drop, value=1)
        senior.pack(side='left')
        withdraw = tk.Radiobutton(type_frame, text="Withdrawal", variable=drop, value=0)
        withdraw.pack(side='left')

        # Good Charger
        charger_frame = tk.Frame(dropoff_frame)
        charger_frame.pack(fill='x', padx=10, pady=5)
        charger_label = tk.Label(charger_frame, text="Do they have a good charger?")
        charger_label.pack(side='left')
        charger = tk.IntVar(value=-1)
        c_yes = tk.Radiobutton(charger_frame, text="Yes", variable=charger, value=1)
        c_yes.pack(side='left')
        c_no = tk.Radiobutton(charger_frame, text="No", variable=charger, value=0)
        c_no.pack(side='left')

        # Charger asset tag (optional)
        charger_tag_frame = tk.Frame(dropoff_frame)
        charger_tag_frame.pack(fill='x', padx=10, pady=5)
        tk.Label(charger_tag_frame, text="Charger asset tag (optional):").pack(side='left')
        charger_tag_var = tk.StringVar()
        tk.Entry(charger_tag_frame, textvariable=charger_tag_var, width=10).pack(side='left', padx=(5, 0))

        # Good Cord
        cord_frame = tk.Frame(dropoff_frame)
        cord_frame.pack(fill='x', padx=10, pady=5)
        cord_label = tk.Label(cord_frame, text="Do they have a good cord?")
        cord_label.pack(side='left')
        cord = tk.IntVar(value=-1)
        cord_yes = tk.Radiobutton(cord_frame, text="Yes", variable=cord, value=1)
        cord_yes.pack(side='left')
        cord_no = tk.Radiobutton(cord_frame, text="No", variable=cord, value=0)
        cord_no.pack(side='left')

        # Damage level
        repair_frame = tk.Frame(dropoff_frame)
        repair_frame.pack(fill='x', padx=10, pady=5)
        repair_label = tk.Label(repair_frame, text="Damage Level:")
        repair_label.pack(side='left')
        repair = tk.IntVar(value=0)
        none = tk.Radiobutton(repair_frame, text="Little/None", variable=repair, value=0)
        none.pack(side='left')
        mild = tk.Radiobutton(repair_frame, text="Mild/Cosmetic", variable=repair, value=1)
        mild.pack(side='left')
        signif = tk.Radiobutton(repair_frame, text="Significant", variable=repair, value=2)
        signif.pack(side='left')

        # Help button — col 0, row 2, anchored left
        help_bar = tk.Frame(dropoff_window)
        help_bar.grid(row=2, column=0, sticky='ew', padx=10, pady=10)
        tk.Button(help_bar, text="Help / Box State", command=lambda: _open_help_dialog(dropoff_window)).pack(
            side='left'
        )

        # Submit button — col 1, row 2, centered
        submit_bar = tk.Frame(dropoff_window)
        submit_bar.grid(row=2, column=1, sticky='ew', padx=10, pady=10)
        submit_bar.grid_columnconfigure(0, weight=1)
        submit_bar.grid_columnconfigure(1, weight=0)
        submit_bar.grid_columnconfigure(2, weight=1)
        tk.Button(submit_bar, text="Submit", command=lambda x=assetData: process_dropoff(x)).grid(
            row=0, column=1
        )

        # Center window
        dropoff_window.update_idletasks()
        sw = dropoff_window.winfo_screenwidth()
        sh = dropoff_window.winfo_screenheight()
        ww = dropoff_window.winfo_width()
        wh = dropoff_window.winfo_height()
        cx = int((sw / 2) - (ww / 2))
        cy = int((sh / 2) - (wh / 2))
        dropoff_window.geometry(f"+{cx}+{cy}")

    return f"Drop-off window opened for {asset_tag}. Submit to complete."
