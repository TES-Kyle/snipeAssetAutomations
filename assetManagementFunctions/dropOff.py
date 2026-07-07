"""Drop-off automation (shared state via Snipe-IT asset Notes) + Help/Box State UI + Reset + Check-In.

- 6 box streams: SG, SM, SD, WG, WM, WD (Senior/Withdrawal × Good/Mild/Damaged)
- Box label: "<STREAM>-NN" (2 digits; 3 digits at 100+)
- Shared box tallies live in the Notes of a dedicated Snipe-IT asset (tag in settings)
- Pull state -> assign new label -> push state (tight window)
- Checks asset in from the user via POST /hardware/{id}/checkin (Retry/Cancel)
- Retry/Cancel messageboxes for all network calls
- Help screen: shows current state, updates capacity, explains damage levels,
  provides "Reset All", and shows a mapping for the two-letter stream acronyms.

settings.json must include:
  boxStateAssetTag, defaultBoxCapacity, dropOffStatusId, dropOffPendingStatusId,
  dropOffLostStatusId, dropOffChargerStatusId, macBookCategoryID, and field key overrides.
"""

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
from utilities.tk_geometry import center_window
from utilities.validation import valid_asset_tag

logger = logging.getLogger(__name__)

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
    path = os.path.join(os.path.dirname(base), "utilities", "settings.json")
    logger.debug("_settings_path: resolved path=%s", path)
    return path

def _load_settings():
    """Load settings.json for the drop-off workflow.

    Returns:
        Dict of settings values or {} on failure.
    """
    configure_logging()
    logger.debug("_load_settings: loading settings for drop-off workflow")
    try:
        # Read settings from disk with a fallback on any failure.
        path = _settings_path()
        logger.debug("_load_settings: reading file=%s", path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("_load_settings: loaded %s keys", len(data))
        return data
    except Exception:
        logger.exception("Failed to read settings.json for drop-off workflow")
        messagebox.showerror(
            "Settings Error",
            "Could not read settings.json at ../utilities/settings.json relative to this module."
        )
        return {}

def _save_settings_key(key: str, value):
    """Best-effort write-back to settings.json to keep defaults in sync.

    Args:
        key: Settings key to update.
        value: New value to write (will be stored as string).

    Returns:
        True on success, False on failure.
    """
    configure_logging()
    logger.debug("_save_settings_key: key=%s value=%s", key, value)
    try:
        p = _settings_path()
        logger.debug("_save_settings_key: reading %s", p)
        # Load existing settings, update one key, and write back.
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data[key] = str(value)
        logger.info("_save_settings_key: writing key=%s to %s", key, p)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug("_save_settings_key: write complete for key=%s", key)
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
    logger.debug("_get_box_state_asset_tag_and_capacity: loading settings")
    s = _load_settings()
    tag = s.get("boxStateAssetTag", "").strip()
    cap = s.get("defaultBoxCapacity", "12")
    logger.debug("_get_box_state_asset_tag_and_capacity: raw tag=%s raw cap=%s", tag, cap)
    try:
        cap = int(cap)
    except Exception:
        logger.debug("_get_box_state_asset_tag_and_capacity: invalid cap value, defaulting to 12")
        cap = 12
    if cap < 1:
        logger.debug("_get_box_state_asset_tag_and_capacity: cap < 1, clamping to 1")
        cap = 1
    if not tag:
        logger.error("settings.json missing boxStateAssetTag")
        messagebox.showerror("Settings Error", "settings.json is missing 'boxStateAssetTag'.")
    logger.debug("_get_box_state_asset_tag_and_capacity: returning tag=%s cap=%s", tag, cap)
    return tag, cap


def _get_dropoff_status_ids():
    """Read configured drop-off status IDs from settings.

    Returns:
        (drop_status_id, pending_status_id, lost_status_id, charger_status_id) tuple,
        or None if any key is missing or not a valid integer.
    """
    logger.debug("_get_dropoff_status_ids: reading drop-off status IDs from settings")
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
        logger.debug("_get_dropoff_status_ids: key=%s raw=%s", key, raw)
        try:
            values.append(int(raw))
        except (TypeError, ValueError):
            msg = f"settings.json key '{key}' ({label} status ID) is missing or not a valid integer (got {raw!r})."
            logger.error(msg)
            messagebox.showerror("Settings Error", msg)
            return None
    logger.debug("_get_dropoff_status_ids: resolved values=%s", values)
    return tuple(values)


def _get_dropoff_field_keys():
    """Read configured custom field keys for drop-off metadata.

    Returns:
        Tuple of (charger_field_key, cord_field_key, box_field_key).
    """
    logger.debug("_get_dropoff_field_keys: reading custom field keys from settings")
    settings = get_settings()
    # Normalize and fallback to default field keys for each metadata field.
    charger_key = settings.get("dropOffChargerFieldKey", "_snipeit_chargeringoodcondition_6").strip()
    cord_key = settings.get("dropOffCordFieldKey", "_snipeit_cordingoodcondition_11").strip()
    box_key = settings.get("dropOffBoxFieldKey", "_snipeit_box_number_5").strip()
    logger.debug("_get_dropoff_field_keys: raw charger_key=%s cord_key=%s box_key=%s", charger_key, cord_key, box_key)
    if not charger_key:
        charger_key = "_snipeit_chargeringoodcondition_6"
    if not cord_key:
        cord_key = "_snipeit_cordingoodcondition_11"
    if not box_key:
        box_key = "_snipeit_box_number_5"
    logger.debug("_get_dropoff_field_keys: final charger_key=%s cord_key=%s box_key=%s", charger_key, cord_key, box_key)
    return charger_key, cord_key, box_key

# ----------------------------
# Snipe-IT helpers (tracker asset)
# ----------------------------
def _get_asset_by_tag_with_retry(asset_tag: str):
    """Fetch a Snipe-IT asset by tag with Retry/Cancel on failure.

    Args:
        asset_tag: Asset tag string to look up via the Snipe-IT API.

    Returns:
        (ok, data) tuple; ok is True and data is the asset dict on success,
        or (False, None) if the user cancels after repeated failures.
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
    """Update only the notes field of a Snipe-IT asset with Retry/Cancel.

    Args:
        asset_id: Numeric Snipe-IT asset ID as a string.
        new_notes: Full replacement notes text to write.

    Returns:
        True on success, False if the user cancels after repeated failures.
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
    logger.debug("_init_default_state: capacity=%s streams=%s", capacity, STREAMS)
    state = {
        "capacity": capacity,
        "streams": {code: {"box": 1, "count": 0} for code in STREAMS},
    }
    logger.debug("_init_default_state: initialized state with %s streams", len(state["streams"]))
    return state

def _format_state_line(state) -> str:
    """Serialize the state into a single-line representation.

    Args:
        state: Parsed tracker state dict.

    Returns:
        One-line string suitable for notes storage.
    """
    logger.debug("_format_state_line: formatting state with capacity=%s", state.get("capacity"))
    parts = [f"box capacity {int(state['capacity'])}"]
    for code in STREAMS:
        s = state["streams"][code]
        parts.append(f"{code} box {int(s['box'])} computer {int(s['count'])}")
    line = "; ".join(parts)
    logger.debug("_format_state_line: result length=%s", len(line))
    return line

def _format_state_notes(state) -> str:
    """Wrap the state line with a header and timestamp.

    Args:
        state: Parsed tracker state dict.

    Returns:
        Notes text with header + state line.
    """
    logger.debug("_format_state_notes: building notes with timestamp")
    header = f"# BOX STATE (updated {datetime.now().isoformat(timespec='seconds')})"
    notes = header + "\n" + _format_state_line(state) + "\n"
    logger.debug("_format_state_notes: notes length=%s", len(notes))
    return notes

def _detect_malformed_notes(notes_text: str) -> bool:
    """Return True if notes_text is non-empty but doesn't look like tracker state.

    Args:
        notes_text: Raw notes string from the tracker asset.

    Returns:
        True if the notes exist but lack expected format markers.
    """
    logger.debug("_detect_malformed_notes: checking notes length=%s", len(notes_text) if isinstance(notes_text, str) else "non-str")
    if not isinstance(notes_text, str):
        return False
    text = notes_text.strip()
    if not text:
        logger.debug("_detect_malformed_notes: empty notes, not malformed")
        return False
    if "box capacity" not in text.lower():
        logger.debug("_detect_malformed_notes: missing 'box capacity' marker")
        return True
    if not re.search(r"\b(SG|SM|SD|WG|WM|WD)\s+box\b", text, re.IGNORECASE):
        logger.debug("_detect_malformed_notes: missing stream box marker")
        return True
    logger.debug("_detect_malformed_notes: notes appear well-formed")
    return False

def _parse_state_from_notes(notes_text: str, default_capacity: int):
    """Parse a forgiving single-line state from tracker notes.

    Args:
        notes_text: Raw notes string from the tracker asset.
        default_capacity: Fallback capacity when notes are empty or unparseable.

    Returns:
        State dict with capacity and per-stream box/count values.
    """
    logger.debug("_parse_state_from_notes: default_capacity=%s notes_len=%s", default_capacity, len(notes_text) if isinstance(notes_text, str) else "non-str")
    if not isinstance(notes_text, str) or not notes_text.strip():
        logger.debug("_parse_state_from_notes: empty notes; returning default state")
        return _init_default_state(default_capacity)

    lines = [ln.strip() for ln in notes_text.splitlines() if ln.strip()]
    if not lines:
        logger.debug("_parse_state_from_notes: no non-empty lines; returning default state")
        return _init_default_state(default_capacity)

    state_line = None
    for ln in reversed(lines):
        if "box capacity" in ln.lower():
            state_line = ln
            break
    if state_line is None:
        state_line = lines[-1]
    logger.debug("_parse_state_from_notes: using state_line length=%s", len(state_line))

    state = _init_default_state(default_capacity)

    tokens = re.split(r"[;\n]+", state_line)
    logger.debug("_parse_state_from_notes: parsing %s tokens", len(tokens))
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
            logger.debug("_parse_state_from_notes: set capacity=%s", state["capacity"])
        else:
            code = key.split()[0].upper()
            box_num = max(1, n1)
            prev_count = state["streams"].get(code, {"count": 0})["count"]
            count_num = int(n2) if n2 is not None else prev_count
            count_num = max(0, count_num)
            state["streams"][code] = {"box": box_num, "count": count_num}
            logger.debug("_parse_state_from_notes: stream %s box=%s count=%s", code, box_num, count_num)

    for code in STREAMS:
        state["streams"].setdefault(code, {"box": 1, "count": 0})
        state["streams"][code]["box"] = max(1, state["streams"][code]["box"])
        state["streams"][code]["count"] = max(0, state["streams"][code]["count"])

    logger.debug("_parse_state_from_notes: parse complete, capacity=%s", state.get("capacity"))
    return state

def _format_seq(box_number: int) -> str:
    """Format box numbers with leading zeros (2 or 3 digits).

    Args:
        box_number: Integer box number to format.

    Returns:
        Zero-padded string representation of the box number.
    """
    logger.debug("_format_seq: box_number=%s", box_number)
    return f"{box_number:02d}" if box_number < 100 else f"{box_number:03d}"

def _assign_from_remote_state(stream_code: str, default_capacity: int):
    """Pull tracker notes, assign a box label, and push updated notes.

    Args:
        stream_code: Two-letter stream code (e.g. SG, WD).
        default_capacity: Box capacity to use when initializing fresh state.

    Returns:
        (ok, box_label) tuple; ok is False and box_label is None on failure.
    """
    configure_logging()
    logger.debug("_assign_from_remote_state: stream_code=%s default_capacity=%s", stream_code, default_capacity)
    tracker_tag, fallback_cap = _get_box_state_asset_tag_and_capacity()
    if not tracker_tag:
        logger.error("_assign_from_remote_state: no tracker tag; aborting")
        return False, None

    logger.info("Assigning box for stream %s", stream_code)
    ok, tracker = _get_asset_by_tag_with_retry(tracker_tag)
    if not ok or not tracker:
        return False, None

    tracker_id = str(tracker["id"])
    tracker_notes = tracker.get("notes", "")
    empty_notes = (not isinstance(tracker_notes, str)) or (not tracker_notes.strip())
    malformed = _detect_malformed_notes(tracker_notes)
    logger.debug("_assign_from_remote_state: tracker_id=%s empty_notes=%s malformed=%s", tracker_id, empty_notes, malformed)

    if empty_notes:
        logger.info("_assign_from_remote_state: initializing fresh tracker state for tracker %s", tracker_id)
        state = _init_default_state(default_capacity or fallback_cap)
        if not _put_asset_notes_with_retry(tracker_id, _format_state_notes(state)):
            return False, None
    else:
        if malformed:
            logger.warning("_assign_from_remote_state: malformed tracker notes; prompting reset")
            do_reset = messagebox.askyesno(
                "Tracker Note Looks Wrong",
                "The tracker asset's note exists but doesn't match the expected format.\n\n"
                "Reset it to a clean state now?\n\n"
                "Yes = reset to default (box 1 / computer 0 for all streams)\n"
                "No = cancel this drop-off"
            )
            if not do_reset:
                logger.info("_assign_from_remote_state: user declined reset; canceling")
                return False, None
            logger.info("_assign_from_remote_state: resetting tracker state after malformed notes")
            state = _init_default_state(default_capacity or fallback_cap)
            if not _put_asset_notes_with_retry(tracker_id, _format_state_notes(state)):
                return False, None
        else:
            logger.debug("_assign_from_remote_state: parsing existing notes for tracker %s", tracker_id)
            state = _parse_state_from_notes(tracker_notes, default_capacity or fallback_cap)

    cap = int(state.get("capacity") or fallback_cap)
    if cap < 1:
        cap = fallback_cap
    logger.debug("_assign_from_remote_state: effective capacity=%s", cap)

    stream_code = stream_code.upper()
    s = state["streams"].get(stream_code, {"box": 1, "count": 0})
    logger.debug("_assign_from_remote_state: stream=%s current box=%s count=%s", stream_code, s["box"], s["count"])

    if s["count"] >= cap:
        logger.debug("_assign_from_remote_state: box full, advancing to next box")
        s["box"] += 1
        s["count"] = 0
    s["count"] += 1
    state["streams"][stream_code] = s
    logger.debug("_assign_from_remote_state: updated stream=%s box=%s count=%s", stream_code, s["box"], s["count"])

    new_notes = _format_state_notes(state)
    logger.info("_assign_from_remote_state: pushing updated state for stream=%s", stream_code)
    ok = _put_asset_notes_with_retry(tracker_id, new_notes)
    if not ok:
        return False, None

    label = f"{stream_code}-{_format_seq(s['box'])}"
    logger.info("_assign_from_remote_state: assigned label=%s", label)
    return True, label

# ----------------------------
# PUT/POST (device) with Retry/Cancel
# ----------------------------
def _checkin_asset_with_retry(id, note="Checked in via Drop-Off automation"):
    """Check in an asset via Snipe-IT with Retry/Cancel on error.

    Treats "already checked in" / "not checked out" responses as non-fatal
    and returns True without prompting the user.

    Args:
        id: Numeric Snipe-IT asset ID (string or int) to check in.
        note: Optional check-in note to include in the API payload.

    Returns:
        True if the asset was checked in or was already checked in,
        False if the user cancels after a non-recoverable error.
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
    """Update a drop-off device's status and custom fields with Retry/Cancel.

    Args:
        id: Numeric Snipe-IT asset ID (string or int).
        assetTag: Asset tag string (used in the PUT payload and error messages).
        statusID: Status ID integer to assign on drop-off.
        modelID: Model ID integer for the asset.
        chargerCond: 'y' if a good charger is present, 'n' otherwise.
        cordCond: 'y' if a good cord is present, 'n' otherwise.
        boxLabel: Box label string to write into the box custom field.
        existingNotes: Notes text to preserve in the payload.

    Returns:
        True on success, False if the user cancels after repeated failures.
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
    """Update only the status and notes of a Snipe-IT asset with Retry/Cancel.

    Args:
        asset_id: Numeric Snipe-IT asset ID (string or int).
        asset_tag: Asset tag string (used in payload and error messages).
        status_id: New status ID integer to apply.
        model_id: Existing model ID integer (required by Snipe-IT PUT).
        new_notes: Full replacement notes text to write.

    Returns:
        True on success, False if the user cancels after repeated failures.
    """
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
    """Open the Help and Box State dialog.

    Args:
        parent: Parent Tkinter widget for the dialog.
    """
    logger.debug("_open_help_dialog: opening help dialog")
    settings = _load_settings()
    tracker_tag = settings.get("boxStateAssetTag", "").strip()
    try:
        default_cap = int(settings.get("defaultBoxCapacity", 12))
    except Exception:
        default_cap = 12
    logger.debug("_open_help_dialog: tracker_tag=%s default_cap=%s", tracker_tag, default_cap)

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
        logger.debug("refresh_state: refreshing state for tracker_tag=%s", tracker_tag)
        if not tracker_tag:
            logger.error("refresh_state: no tracker_tag set")
            messagebox.showerror("Tracker Missing", "boxStateAssetTag is not set in settings.json.")
            return
        ok, tracker = _get_asset_by_tag_with_retry(tracker_tag)
        if not ok or not tracker:
            logger.error("refresh_state: failed to fetch tracker asset")
            return
        notes = tracker.get("notes", "")
        logger.debug("refresh_state: tracker notes length=%s", len(notes))
        if _detect_malformed_notes(notes):
            logger.warning("refresh_state: malformed notes detected for tracker %s", tracker_tag)
            messagebox.showwarning(
                "Note Format Warning",
                "The tracker note exists but doesn't match the expected format.\n"
                "You can use 'Reset All' to initialize a clean state."
            )
        state = _parse_state_from_notes(notes, default_cap)
        state_var.set(_format_state_line(state))
        cap_entry_var.set(str(state.get("capacity", default_cap)))
        logger.debug("refresh_state: state display updated")

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
        logger.debug("save_capacity: attempting to save new capacity")
        try:
            new_cap = int(cap_entry_var.get())
        except Exception:
            logger.warning("save_capacity: invalid capacity value entered")
            messagebox.showerror("Invalid Capacity", "Please enter a whole number (≥1).")
            return
        if new_cap < 1:
            logger.warning("save_capacity: capacity value < 1: %s", new_cap)
            messagebox.showerror("Invalid Capacity", "Capacity must be at least 1.")
            return
        logger.info("save_capacity: saving new capacity=%s", new_cap)

        tt, fallback_cap = _get_box_state_asset_tag_and_capacity()
        if not tt:
            logger.error("save_capacity: no tracker tag; aborting")
            return
        ok, tracker = _get_asset_by_tag_with_retry(tt)
        if not ok or not tracker:
            logger.error("save_capacity: failed to fetch tracker asset")
            return

        tracker_id = str(tracker["id"])
        logger.debug("save_capacity: tracker_id=%s", tracker_id)
        state = _parse_state_from_notes(tracker.get("notes", ""), fallback_cap)
        state["capacity"] = new_cap
        new_notes = _format_state_notes(state)
        logger.info("save_capacity: pushing updated notes with capacity=%s", new_cap)
        ok = _put_asset_notes_with_retry(tracker_id, new_notes)
        if not ok:
            logger.error("save_capacity: failed to push updated notes")
            return

        _save_settings_key("defaultBoxCapacity", new_cap)
        logger.debug("save_capacity: settings key updated")

        state_var.set(_format_state_line(state))
        # messagebox.showinfo("Capacity Updated", f"Capacity set to {new_cap}.")

    tk.Button(cap_frame, text="Save", command=save_capacity).pack(side="left", padx=10, pady=8)

    # Reset All
    reset_frame = tk.Frame(dlg)
    reset_frame.pack(fill="x", padx=12, pady=(0, 8))
    def reset_all():
        """Reset tracker state to defaults after confirmation."""
        logger.debug("reset_all: prompting user for reset confirmation")
        if not messagebox.askyesno(
            "Reset All Streams",
            "Are you sure you want to reset all streams to box 1 / computer 0?\n\nThis cannot be undone."
        ):
            logger.info("reset_all: user declined reset")
            return
        logger.info("reset_all: user confirmed reset; proceeding")
        tt, fallback_cap = _get_box_state_asset_tag_and_capacity()
        if not tt:
            logger.error("reset_all: no tracker tag; aborting")
            return
        ok, tracker = _get_asset_by_tag_with_retry(tt)
        if not ok or not tracker:
            logger.error("reset_all: failed to fetch tracker asset")
            return
        tracker_id = str(tracker["id"])
        logger.debug("reset_all: tracker_id=%s", tracker_id)

        notes = tracker.get("notes", "")
        st = _parse_state_from_notes(notes, fallback_cap)
        cap = st.get("capacity", fallback_cap)
        logger.debug("reset_all: preserving capacity=%s", cap)

        new_state = _init_default_state(cap)
        new_notes = _format_state_notes(new_state)
        logger.info("reset_all: pushing reset state to tracker %s", tracker_id)
        ok = _put_asset_notes_with_retry(tracker_id, new_notes)
        if not ok:
            logger.error("reset_all: failed to push reset state")
            return

        state_var.set(_format_state_line(new_state))
        logger.info("reset_all: all streams reset to box 1 / computer 0")
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
    center_window(dlg)

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
        """Validate answers, update state, and apply drop-off updates.

        Args:
            assetData: Asset data dict from Snipe-IT for the asset being dropped off.
        """
        logger.debug("process_dropoff: asset_tag=%s asset_id=%s", assetData.get("asset_tag"), assetData.get("id"))
        # Validate required fields
        if charger.get() < 0 or drop.get() < 0:
            messagebox.showerror("Error", "Dumb dumb, answer all the questions!")
            return

        charger_asset_tag = charger_tag_var.get().strip()
        if charger_asset_tag and not valid_asset_tag(charger_asset_tag):
            messagebox.showerror("Invalid Charger Tag", "Charger asset tag must match the configured asset tag pattern.")
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
    logger.debug("dropOff: fetching asset info for %s", asset_tag)
    var_list, assetData = getAssetInfo(asset_tag)
    logger.debug("dropOff: asset fetched id=%s name=%s", assetData.get("id"), assetData.get("name"))
    proceed = False

    _ids = _get_dropoff_status_ids()
    if _ids is None:
        logger.error("dropOff: status ID settings error for %s", asset_tag)
        return f"Drop-off aborted: status ID settings error for {asset_tag}."
    _status_id, pending_status_id, _lost_status_id, _charger_status_id, _macbook_category_id = _ids
    logger.debug("dropOff: resolved status IDs for %s: drop=%s pending=%s lost=%s charger=%s", asset_tag, _status_id, pending_status_id, _lost_status_id, _charger_status_id)

    if assetData["category"]["id"] != _macbook_category_id:
        logger.info("dropOff: asset %s is not a MacBook (category=%s); prompting override", asset_tag, assetData["category"]["id"])
        proceed = messagebox.askyesno(
            title="Not A MacBook!",
            message='This asset is not a MacBook\n\nProceed anyway?'
        )
        logger.info("Drop-off category override prompt for %s: %s", asset_tag, proceed)
    elif assetData["status_label"]["id"] != pending_status_id:
        logger.info("dropOff: asset %s status=%s not pending drop-off; prompting override", asset_tag, assetData["status_label"]["id"])
        proceed = messagebox.askyesno(
            title="Proceed?",
            message='This asset is not "Pending Drop-Off"\n\nProceed anyway?'
        )
        logger.info("Drop-off status override prompt for %s: %s", asset_tag, proceed)
    else:
        logger.debug("dropOff: asset %s is MacBook with pending status; proceeding", asset_tag)
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
        center_window(dropoff_window)

    return f"Drop-off window opened for {asset_tag}. Submit to complete."
