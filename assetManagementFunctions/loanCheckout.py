"""Loan Computer Checkout workflow.

Checks a loaner device out to a person, tracking their qualifying loaner
checkouts since the last configured semester cutoff, warning at the 2nd/3rd
such checkout, and requiring a staff override beyond that. The warning
email defaults on for the 2nd checkout and, since the 3rd checkout is
really "3rd or later," for every checkout from the 3rd through any
subsequent override too.

Whether a given checkout counts toward that limit is decided by the "Count
against loan limit" checkbox in the window -- it defaults off for the
"repair" reason and on for everything else, but staff can flip it either
way for any reason, and whatever it's set to at Submit time is final. This
is a deliberate override point: circumstances vary, so the reason picked
and whether it counts are two independent decisions.

History is tracked entirely inside Snipe-IT: each checkout appends one
parseable line to the *person's* Snipe-IT user "notes" field (see
_format_loan_note_line/_parse_loan_note_lines below for the line format and
parser), recording whichever counts/excused decision the checkbox held at
submit time. That keeps the tally visible on the person's own Snipe-IT
profile and immune to future edits of the reason list, since the decision
is frozen into the note line at write time rather than re-derived later.

The pure (Tk-free) helper functions below are private to this module --
they're only meaningful in the context of loan checkouts, so unlike
utilities/otherApiBits.py or utilities/messaging.py (genuinely shared
across many modules) they live here rather than in utilities/.

settings.json keys used (see utilities/defaultSettings.json for defaults,
and utilities/settingsSchema.json's "Loan Checkout" group for descriptions):
  loanCheckoutAllowedCategoryIDs, loanCheckoutStatusId,
  loanCheckoutSemesterCutoffDates, loanCheckoutMaxBeforeOverride,
  loanCheckoutReasonList, loanCheckoutCcParentDefaultSecond,
  loanCheckoutCcParentDefaultThird
"""

import logging
import re
import threading
from datetime import date, datetime, timedelta

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont
import requests

from utilities.logging_utils import configure_logging
from utilities.settings import get_settings
from utilities.otherApiBits import (
    getAssetInfo,
    get_headers,
    build_asset_info_frame,
    append_note,
    put_notes_with_retry,
)
from utilities import optionsCache
from utilities.Key import API_URL_Base
from utilities.api_user import get_api_key
from utilities.api_retry import call_with_retry
from utilities.autocomplete import AutoCompleteEntry
from utilities.tk_geometry import center_window
from utilities.tk_thread import ensure_tk_thread_pump, run_on_tk_thread
from utilities.tk_date_entry import build_date_entry_frame
from utilities.checkInOutCommon import build_soft_message_frame
from utilities.theme import get_ui_colors
from utilities.messaging import (
    message,
    get_parents,
    is_email,
    loan_checkout_warning_second,
    loan_checkout_warning_third,
)
from assetManagementFunctions.checkIn import checkIn

logger = logging.getLogger(__name__)

# One header line appended to a user's Snipe-IT notes per loaner checkout.
# The trailing [counts/excused] tag freezes the "Count against loan limit"
# checkbox's state *at checkout time* into the note itself, so later edits
# to loanCheckoutReasonList (or a reason being removed entirely) can never
# change how a past checkout tallies.
_NOTE_HEADER_RE = re.compile(
    r"^Checked out loaner on (?P<date>\d{4}-\d{2}-\d{2}) \(tag (?P<tag>\S+)\): "
    r"(?P<reason>.+) \[(?P<flag>counts|excused)\]$"
)

# Any freeform Notes text (which may span multiple lines, exactly as typed)
# is written on the line(s) immediately following a header, each prefixed
# with this marker. The prefix is what makes multi-line notes parseable
# without also swallowing unrelated freeform text a person's Snipe-IT
# profile might otherwise contain -- only prefixed lines are treated as a
# continuation of the checkout above them; anything else ends the block.
_NOTE_CONTINUATION_PREFIX = "    "

_DATE_STRING_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Reason combobox width (characters) -- shrunk when "Other" is selected so
# the free-text box that appears next to it barely widens the window.
_REASON_COMBOBOX_WIDTH_NORMAL = 28
_REASON_COMBOBOX_WIDTH_OTHER = 10

# Grey placeholder guidance shown inside the Notes box until typed over --
# kept in the box itself (word-wrapped to the box's width) rather than a
# label above it, so the full explanation doesn't force the window wider.
_NOTES_PLACEHOLDER_TEXT = (
    "Required to exceed the loan limit, or to change 'Count against loan "
    "limit' from its default."
)


# =============================================================================
# Pure logic helpers (no Tk/network) -- kept testable and separate from the
# window-building code below, mirroring dropOff.py's private-helpers pattern.
# =============================================================================

def _parse_int_list(raw):
    """Parse a semicolon-separated list of integers, skipping bad entries.

    Args:
        raw: Raw semicolon-separated setting string.

    Returns:
        List of ints (possibly empty).
    """
    out = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            logger.warning("_parse_int_list: skipping non-integer entry: %r", chunk)
    return out


def _parse_reason_list(raw):
    """Parse the loanCheckoutReasonList setting into reason dicts.

    Format: semicolon-separated entries, each 'key:Label:repair:dueDays'
    (repair is '0' or '1' -- used only to set the "Count against loan limit"
    checkbox's *default*, and to disable the due-date field; whether a
    checkout actually counts is decided by that checkbox at submit time, not
    stored per-reason). dueDays controls the expected check-in date field's
    behavior for that reason:
      - blank    -> no default; field stays enabled for manual entry.
      - integer  -> field defaults to today + N days, but stays editable
                    (e.g. 0 for "today", 7 for "a week out").
      - 'off'    -> the field isn't applicable at all; it's cleared and
                    disabled (e.g. a repair's return date isn't known yet).
    Labels must not contain ':' or ';'. Malformed entries are logged and
    skipped rather than raising, so one bad hand-edited entry can't break
    the whole reason list.

    Args:
        raw: Raw loanCheckoutReasonList setting string.

    Returns:
        Ordered list of dicts: {"key", "label", "repair", "due_days",
        "checkin_enabled"}.
    """
    reasons = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 4:
            logger.warning("_parse_reason_list: skipping malformed entry (expected 4 ':'-fields): %r", chunk)
            continue
        key, label, repair_raw, due_days_raw = (p.strip() for p in parts)
        if not key or not label:
            logger.warning("_parse_reason_list: skipping entry with empty key/label: %r", chunk)
            continue

        if due_days_raw.lower() in ("off", "na", "n/a"):
            due_days, checkin_enabled = None, False
        elif due_days_raw == "":
            due_days, checkin_enabled = None, True
        else:
            try:
                due_days, checkin_enabled = int(due_days_raw), True
            except ValueError:
                logger.warning("_parse_reason_list: non-integer dueDays in %r; treating as manual/blank", chunk)
                due_days, checkin_enabled = None, True

        reasons.append({
            "key": key,
            "label": label,
            "repair": repair_raw == "1",
            "due_days": due_days,
            "checkin_enabled": checkin_enabled,
        })
    logger.debug("_parse_reason_list: parsed %s reason(s) from setting", len(reasons))
    return reasons


def _parse_month_day(raw_token):
    """Parse a single MM-DD or MM/DD token into (month, day).

    Args:
        raw_token: A single cutoff token, e.g. "07-15" or "12/27".

    Returns:
        (month, day) tuple, or None if the token isn't a valid MM-DD.
    """
    token = raw_token.strip().replace("/", "-")
    parts = token.split("-")
    if len(parts) != 2:
        return None
    try:
        month, day = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return month, day


def _get_last_cutoff(raw_dates, today=None):
    """Return the most recent occurrence of any recurring MM-DD cutoff on/before today.

    Cutoffs are stored as MM-DD (or MM/DD) with no year, so they recur every
    year without ever needing to be edited (e.g. a date mid-winter-break and
    a date mid-summer-break, per the semester-boundary use case).

    Args:
        raw_dates: Semicolon-separated MM-DD/MM/DD tokens.
        today: Reference date; defaults to date.today().

    Returns:
        The latest date <= today across all configured cutoffs (using
        whichever past year that cutoff most recently fell in), or None if
        none are configured/parseable.
    """
    if today is None:
        today = date.today()
    best = None
    for chunk in (raw_dates or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parsed = _parse_month_day(chunk)
        if parsed is None:
            logger.warning("_get_last_cutoff: skipping unparseable cutoff: %r", chunk)
            continue
        month, day = parsed
        # Try this year's occurrence first; if that's still in the future,
        # fall back to last year's (whichever most recently already happened).
        candidate = None
        for year in (today.year, today.year - 1):
            try:
                d = date(year, month, day)
            except ValueError:
                continue  # e.g. Feb 29 in a non-leap year
            if d <= today:
                candidate = d
                break
        if candidate is not None and (best is None or candidate > best):
            best = candidate
    logger.debug("_get_last_cutoff: raw_dates=%r today=%s -> %s", raw_dates, today, best)
    return best


def _format_loan_note_line(when, asset_tag, reason_label, counts, notes_text=""):
    """Build one loaner-checkout note block for a Snipe-IT user's notes field.

    Args:
        when: date of the checkout.
        asset_tag: Asset tag of the device checked out.
        reason_label: Human-readable reason text (must not contain '[' or ']').
        counts: Whether the "Count against loan limit" checkbox was checked
            for this checkout -- see _count_qualifying_since_cutoff.
        notes_text: Optional freeform text from the Notes box, written
            verbatim (one or more lines) below the header rather than
            flattened, so it reads the same way it was typed.

    Returns:
        The formatted block: a header line, plus one prefixed line per line
        of notes_text if any was given (no trailing newline either way).
    """
    flag = "counts" if counts else "excused"
    header = f"Checked out loaner on {when.isoformat()} (tag {asset_tag}): {reason_label} [{flag}]"
    notes_text = (notes_text or "").strip("\n")
    if not notes_text:
        logger.debug("_format_loan_note_line: %s", header)
        return header
    block = header + "\n" + "\n".join(
        f"{_NOTE_CONTINUATION_PREFIX}{note_line}" for note_line in notes_text.splitlines()
    )
    logger.debug("_format_loan_note_line: %s", block)
    return block


def _parse_loan_note_lines(notes_text):
    """Extract loaner-checkout entries previously written by _format_loan_note_line.

    Each entry is a header line optionally followed by prefixed
    continuation lines (its freeform notes, verbatim). Any line that's
    neither a recognized header nor a prefixed continuation of the entry
    directly above it -- including unrelated freeform notes a person's
    record might otherwise contain -- ends that entry's notes and is itself
    ignored, so this is safe to run over a user's full notes field as-is.

    Args:
        notes_text: Raw notes string from a Snipe-IT user record.

    Returns:
        List of dicts: {"date": date, "asset_tag": str, "reason_label": str,
        "counts": bool, "notes": str}, in the order found. "notes" is "" when
        no freeform text was recorded for that checkout; multi-line notes
        keep their original internal newlines.
    """
    entries = []
    if not isinstance(notes_text, str):
        return entries

    current = None
    note_lines = []

    def _flush():
        """Finalize the in-progress entry (if any) into entries."""
        if current is not None:
            current["notes"] = "\n".join(note_lines)
            entries.append(current)

    for raw_line in notes_text.splitlines():
        m = _NOTE_HEADER_RE.match(raw_line.strip())
        if m:
            _flush()
            try:
                when = datetime.strptime(m.group("date"), "%Y-%m-%d").date()
            except ValueError:
                current = None
                note_lines = []
                continue
            current = {
                "date": when,
                "asset_tag": m.group("tag"),
                "reason_label": m.group("reason"),
                "counts": m.group("flag") == "counts",
            }
            note_lines = []
        elif current is not None and raw_line.startswith(_NOTE_CONTINUATION_PREFIX):
            note_lines.append(raw_line[len(_NOTE_CONTINUATION_PREFIX):])
        else:
            _flush()
            current = None
            note_lines = []
    _flush()

    logger.debug("_parse_loan_note_lines: found %s loaner checkout entries", len(entries))
    return entries


def _count_qualifying_since_cutoff(entries, cutoff):
    """Count loaner checkouts that were marked as counting, on/after cutoff.

    Args:
        entries: List of entries from _parse_loan_note_lines.
        cutoff: date to filter from (inclusive), or None to count all-time.

    Returns:
        Integer count of qualifying entries.
    """
    count = sum(1 for e in entries if e["counts"] and (cutoff is None or e["date"] >= cutoff))
    logger.debug("_count_qualifying_since_cutoff: cutoff=%s entries=%s -> count=%s", cutoff, len(entries), count)
    return count


def _determine_checkout_outcome(current_count, counts, max_before_override):
    """Determine what this checkout means for warnings/overrides.

    Args:
        current_count: Qualifying checkout count *before* this checkout
            (from _count_qualifying_since_cutoff).
        counts: Whether this checkout counts toward the limit -- i.e. the
            "Count against loan limit" checkbox's current state.
        max_before_override: loanCheckoutMaxBeforeOverride setting (int).

    Returns:
        Dict: {"counts": bool, "new_count": int, "requires_warning": bool,
        "requires_override": bool, "requires_email": bool}.
        "requires_warning" is True for the two checkouts at/just-before the
        limit (e.g. the 2nd and 3rd of 3); "requires_override" is True once
        the limit is exceeded. "requires_email" covers both -- the 3rd
        checkout's warning email is really a "3rd or later" email, so every
        override past the limit sends it too, by default.
    """
    counts = bool(counts)
    new_count = current_count + 1 if counts else current_count
    requires_warning = counts and new_count in (max(max_before_override - 1, 1), max_before_override)
    requires_override = counts and new_count > max_before_override
    result = {
        "counts": counts,
        "new_count": new_count,
        "requires_warning": requires_warning,
        "requires_override": requires_override,
        "requires_email": requires_warning or requires_override,
    }
    logger.debug(
        "_determine_checkout_outcome: current_count=%s counts=%s max=%s -> %s",
        current_count, counts, max_before_override, result,
    )
    return result


def _valid_date_string(value):
    """Return True if value is a real YYYY-MM-DD date (or blank).

    Args:
        value: Candidate date string.

    Returns:
        True if blank or a valid YYYY-MM-DD date, False otherwise.
    """
    if not value:
        return True
    if not _DATE_STRING_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# =============================================================================
# GUI
# =============================================================================

def loanCheckout(asset_tag):
    """Check out a loaner computer to a person.

    Args:
        asset_tag: Asset tag of the loaner device to check out.

    Returns:
        Status string for the main UI, or None if the workflow was aborted
        or handed off (e.g. to the check-in flow, or a Toplevel awaiting
        Submit).
    """
    configure_logging()
    logger.info("loanCheckout: starting for asset_tag=%s", asset_tag)
    url = API_URL_Base.rstrip("/")

    # ---- Load and parse settings up front ------------------------------
    settings = get_settings()
    allowed_category_ids = _parse_int_list(settings.get("loanCheckoutAllowedCategoryIDs", ""))
    loaner_status_id_raw = settings.get("loanCheckoutStatusId", "").strip()
    cutoff_dates_raw = settings.get("loanCheckoutSemesterCutoffDates", "")
    try:
        max_before_override = int(settings.get("loanCheckoutMaxBeforeOverride", 3))
    except Exception:
        logger.warning("loanCheckout: invalid loanCheckoutMaxBeforeOverride; defaulting to 3")
        max_before_override = 3
    reasons = _parse_reason_list(settings.get("loanCheckoutReasonList", ""))
    cc_default_second = settings.get("loanCheckoutCcParentDefaultSecond", "0") == "1"
    cc_default_third = settings.get("loanCheckoutCcParentDefaultThird", "1") == "1"
    logger.debug(
        "loanCheckout: settings loaded allowed_category_ids=%s loaner_status_id_raw=%s "
        "max_before_override=%s reason_keys=%s cc_default_second=%s cc_default_third=%s",
        allowed_category_ids, loaner_status_id_raw, max_before_override,
        [r["key"] for r in reasons], cc_default_second, cc_default_third,
    )

    if not reasons:
        logger.error("loanCheckout: loanCheckoutReasonList setting is empty or unparseable")
        messagebox.showerror("Settings Error", "loanCheckoutReasonList is empty or invalid in settings.")
        return "Loan checkout aborted: no reasons configured."

    # ---- Fetch and validate the asset -----------------------------------
    logger.debug("loanCheckout: fetching asset info for %s", asset_tag)
    var_list, assetData = getAssetInfo(asset_tag)
    if not assetData:
        logger.error("loanCheckout: could not load asset %s", asset_tag)
        return f"Loan checkout aborted: could not load asset {asset_tag}."

    if assetData.get("assigned_to") is not None:
        # Mirrors checkoutTo.py: an already-assigned asset needs to be checked
        # in first, not re-checked-out on top of its current assignment.
        logger.info("loanCheckout: asset %s already checked out; routing to check-in", asset_tag)
        checkIn(asset_tag, "yes")
        return None

    # Hard-fail on wrong device type -- unlike the status check below, this
    # is not an "offer to change" situation, per the spec.
    category_id = (assetData.get("category") or {}).get("id")
    if allowed_category_ids and category_id not in allowed_category_ids:
        logger.warning(
            "loanCheckout: asset %s category=%s not in allowed list %s; failing",
            asset_tag, category_id, allowed_category_ids,
        )
        messagebox.showerror(
            "Wrong Device Type",
            f"Asset {asset_tag} (category id {category_id}) is not an eligible device type for loaner checkout.",
        )
        return f"Loan checkout aborted for {asset_tag}: wrong device type."
    elif not allowed_category_ids:
        logger.debug("loanCheckout: loanCheckoutAllowedCategoryIDs not configured; skipping device-type check")

    # Offer to change status if the asset isn't currently in the configured
    # loaner status -- unlike the category check, this one is recoverable.
    current_status_id = (assetData.get("status_label") or {}).get("id")
    current_status_name = (assetData.get("status_label") or {}).get("name", "")
    if loaner_status_id_raw:
        try:
            loaner_status_id = int(loaner_status_id_raw)
        except ValueError:
            logger.error("loanCheckout: loanCheckoutStatusId is not a valid integer: %r", loaner_status_id_raw)
            loaner_status_id = None
        if loaner_status_id is not None and current_status_id != loaner_status_id:
            logger.info(
                "loanCheckout: asset %s status=%s is not the loaner status=%s; prompting",
                asset_tag, current_status_id, loaner_status_id,
            )
            change = messagebox.askyesno(
                "Not a Loaner",
                f"Asset {asset_tag} is currently '{current_status_name}', not the configured Loaner status.\n\n"
                "Change its status to Loaner and continue?",
            )
            if not change:
                logger.info("loanCheckout: user declined status change for %s; aborting", asset_tag)
                return f"Loan checkout aborted for {asset_tag}: not a loaner-status device."
            model_id = (assetData.get("model") or {}).get("id")
            # No is_success override -- default_is_success also rejects
            # Snipe-IT's "HTTP 200 but body says status: error" responses.
            ok = call_with_retry(
                f"Change {asset_tag} status to Loaner",
                lambda: requests.put(
                    url + "/hardware/" + str(assetData["id"]),
                    json={"status_id": loaner_status_id, "model_id": model_id},
                    headers=get_headers(),
                    timeout=20,
                ),
            )
            if ok is None:
                logger.error("loanCheckout: failed to change status for %s; aborting", asset_tag)
                return f"Loan checkout aborted for {asset_tag}: status change failed."
            logger.info("loanCheckout: status changed to Loaner for %s", asset_tag)
            # Re-fetch so the device info pane (built from var_list below)
            # reflects the new status rather than the stale pre-change one.
            var_list, assetData = getAssetInfo(asset_tag)
    else:
        logger.debug("loanCheckout: loanCheckoutStatusId not configured; skipping loaner-status check")

    # ---- Mutable state shared across the nested callbacks below --------
    # Tk closures can't rebind a plain outer variable with '=', so these
    # dicts stand in for what would otherwise be several 'nonlocal' scalars.
    reason_by_label = {r["label"]: r for r in reasons}
    selected_user = {"id": None, "email": "", "name": ""}
    current_count_holder = {"count": 0, "cutoff": None}
    parents_holder = {"emails": []}
    # Tracks the "Count against loan limit" default for whichever reason is
    # currently selected, so submit() can tell whether the checkbox was
    # manually flipped away from it (which also requires a note).
    counts_default_holder = {"value": True}
    # True while the Notes box is showing its grey placeholder guidance
    # rather than real typed text -- see _get_notes_text() below.
    notes_placeholder_holder = {"active": True}

    reason_var = tk.StringVar()
    other_text_var = tk.StringVar()
    counts_var = tk.BooleanVar(value=True)
    email_checkbox_var = tk.BooleanVar(value=True)
    cc_parent_var = tk.BooleanVar(value=False)

    def _fetch_user_by_id(user_id):
        """Fetch the full Snipe-IT user record (including notes) by id.

        Args:
            user_id: Snipe-IT user id.

        Returns:
            User dict, or {} on failure.
        """
        try:
            response = requests.get(url + f"/users/{user_id}", headers=get_headers(), timeout=20)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("status") == "error":
                logger.error("_fetch_user_by_id: bad response for user %s: %s", user_id, data)
                return {}
            return data
        except Exception:
            logger.exception("_fetch_user_by_id: failed for user %s", user_id)
            return {}

    def _resolved_reason():
        """Return the reason dict for the current selection, with 'other' text applied.

        Returns:
            Reason dict (label overridden with the custom text for 'other'),
            or None if no valid reason is selected yet.
        """
        reason = reason_by_label.get(reason_var.get())
        if not reason:
            return None
        if reason["key"] == "other":
            custom = other_text_var.get().strip()
            if not custom:
                return None
            return {**reason, "label": custom}
        return reason

    def _render_history(entries_for_table):
        """Render this semester's loan checkouts into the read-only history box.

        Uses a plain Text widget rather than a Treeview so multi-line notes
        can be shown verbatim, on their own line(s), instead of crammed into
        a single table cell.

        Args:
            entries_for_table: Entries from _parse_loan_note_lines, already
                filtered to the window to display (e.g. since the cutoff).
        """
        history_text.configure(state="normal")
        history_text.delete("1.0", "end")
        if not entries_for_table:
            history_text.insert("end", "No loan checkouts on record for this person this semester.")
        else:
            for i, e in enumerate(sorted(entries_for_table, key=lambda e: e["date"], reverse=True)):
                if i > 0:
                    history_text.insert("end", "\n\n")
                counts_txt = "Yes" if e["counts"] else "No"
                history_text.insert("end", f"{e['date'].isoformat()}  —  {e['reason_label']}  —  Counts: {counts_txt}\n")
                history_text.insert("end", e["notes"] if e["notes"] else "(no notes)")
        history_text.configure(state="disabled")

    def _get_notes_text():
        """Return the real (non-placeholder) Notes box content.

        Returns:
            Stripped text the user actually typed, or "" if the box is
            empty or still showing the grey placeholder guidance.
        """
        if notes_placeholder_holder["active"]:
            return ""
        return notes_text_widget.get("1.0", "end-1c").strip()

    def _on_notes_focus_in(_e):
        """Clear the placeholder guidance when the Notes box receives focus."""
        if notes_placeholder_holder["active"]:
            notes_text_widget.delete("1.0", "end")
            notes_text_widget.configure(fg=theme["entry_fg"])
            notes_placeholder_holder["active"] = False

    def _on_notes_focus_out(_e):
        """Restore the placeholder guidance if the Notes box is left empty."""
        if not notes_text_widget.get("1.0", "end-1c").strip():
            notes_placeholder_holder["active"] = True
            notes_text_widget.delete("1.0", "end")
            notes_text_widget.insert("1.0", _NOTES_PLACEHOLDER_TEXT)
            notes_text_widget.configure(fg=theme["muted_fg"])

    def on_person_change():
        """Recompute the live checkout-count display when the person selection changes."""
        sel = person_ac.get_selected()
        if not sel or sel.get("type") != "user":
            # Fires on every keystroke while typing (not just on commit) --
            # skip the network work until there's an actual committed pick.
            count_prefix_var.set("Select a person to see their checkout history.")
            count_number_var.set("")
            _render_history([])
            selected_user.update({"id": None, "email": "", "name": ""})
            parents_holder["emails"] = []
            _refresh_warning_controls()
            return

        logger.debug("on_person_change: selected user id=%s label=%s", sel.get("id"), sel.get("label"))
        count_prefix_var.set("Loading checkout history…")
        count_number_var.set("")
        selected_user.update({"id": sel["id"], "email": sel.get("email", ""), "name": sel.get("label", "")})

        def worker():
            """Fetch the user's notes (background thread) and tally history.

            The checkout count/history (below) is fully derived from
            Snipe-IT alone and is the whole point of this screen -- it must
            never wait on the separate parent-email lookup that follows,
            which goes over an unrelated SFTP connection
            (utilities.messaging.get_parents) that has no bounded connect
            timeout at the TCP level. A silently-dropped connection to that
            host (e.g. a school network that blocks outbound port 22) can
            hang for minutes; previously that hang blocked this entire
            apply() from ever running, so the window stayed on "Loading
            checkout history..." forever even though everything needed to
            show it had already been fetched.
            """
            fresh = _fetch_user_by_id(sel["id"])
            entries = _parse_loan_note_lines(fresh.get("notes") or "")
            cutoff = _get_last_cutoff(cutoff_dates_raw)
            count = _count_qualifying_since_cutoff(entries, cutoff)
            logger.info(
                "on_person_change: user=%s qualifying checkouts since %s = %s",
                sel.get("label"), cutoff, count,
            )

            def apply_history():
                """Apply the checkout count/history to widgets on the Tk thread."""
                logger.debug(
                    "on_person_change: apply_history INVOKED for user=%s (window_exists=%s)",
                    sel.get("label"), checkout_window.winfo_exists(),
                )
                if not checkout_window.winfo_exists():
                    # The window closed in the gap between this background
                    # fetch finishing and Tk actually running this callback.
                    # Touching any widget below unconditionally is what
                    # produced a real SIGSEGV crash (Tcl segfaulting inside
                    # SetCmdNameFromAny resolving a destroyed widget's
                    # command) -- confirmed via a macOS crash report landing
                    # ~8ms after this exact worker's own log line.
                    logger.debug("on_person_change: window closed before apply_history ran; skipping")
                    return
                current_count_holder["count"] = count
                current_count_holder["cutoff"] = cutoff
                since_txt = cutoff.isoformat() if cutoff else "the start (no cutoff configured yet)"
                count_prefix_var.set(f"Qualifying loaner checkouts since {since_txt}:")
                count_number_var.set(str(count))

                # This semester's history only (since the same cutoff as the
                # count above), but every checkout in that window regardless
                # of whether it counted.
                since_cutoff = [e for e in entries if cutoff is None or e["date"] >= cutoff]
                _render_history(since_cutoff)

                _refresh_warning_controls()
                logger.debug("on_person_change: apply_history COMPLETED for user=%s", sel.get("label"))

            logger.debug("on_person_change: queuing apply_history for user=%s", sel.get("label"))
            run_on_tk_thread(checkout_window, apply_history)
            logger.debug("on_person_change: apply_history QUEUED for user=%s", sel.get("label"))

            # Parent-email lookup for the CC-parent preview only -- fetched
            # separately so its own success/failure/hang can never block the
            # count/history above. Nothing functionally required for
            # checking a device out depends on this finishing.
            parents = []
            try:
                parents = get_parents(fresh.get("email") or sel.get("email", "")) or []
            except Exception:
                logger.exception("on_person_change: failed to look up parent emails for %s", sel.get("label"))

            def apply_parents():
                logger.debug(
                    "on_person_change: apply_parents INVOKED for user=%s (window_exists=%s)",
                    sel.get("label"), checkout_window.winfo_exists(),
                )
                if not checkout_window.winfo_exists():
                    logger.debug("on_person_change: window closed before apply_parents ran; skipping")
                    return
                parents_holder["emails"] = parents
                _update_recipients_display()
                logger.debug("on_person_change: apply_parents COMPLETED for user=%s", sel.get("label"))

            logger.debug("on_person_change: queuing apply_parents for user=%s", sel.get("label"))
            run_on_tk_thread(checkout_window, apply_parents)
            logger.debug("on_person_change: apply_parents QUEUED for user=%s", sel.get("label"))

        threading.Thread(target=worker, daemon=True).start()

    def on_reason_change(*_args):
        """Show/hide the custom-reason box and set the due-date field's mode when the reason changes."""
        reason = reason_by_label.get(reason_var.get())
        logger.debug("on_reason_change: label=%s reason_key=%s", reason_var.get(), reason.get("key") if reason else None)

        if reason and reason["key"] == "other":
            # Stop the combobox from claiming the whole row (it only needs
            # to show "Other") so the free-text box can take the rest of
            # the row instead of widening the window.
            reason_combobox.configure(width=_REASON_COMBOBOX_WIDTH_OTHER)
            reason_combobox.pack_configure(expand=False)
            other_entry.pack(side="left", expand=True, fill="x", padx=(6, 0))
        else:
            reason_combobox.configure(width=_REASON_COMBOBOX_WIDTH_NORMAL)
            reason_combobox.pack_configure(expand=True)
            other_entry.pack_forget()

        if reason is None:
            return

        # Default the "count against limit" checkbox from the reason (off
        # for repair, on otherwise), but this is only ever a default -- the
        # checkbox itself remains the actual, overridable source of truth.
        # The default is remembered so submit() can require a note if staff
        # flip the checkbox away from it.
        counts_default_holder["value"] = not reason["repair"]
        counts_var.set(counts_default_holder["value"])

        if not reason["checkin_enabled"]:
            # Not applicable (e.g. repair) -- show a fixed "N/A" and lock the field.
            date_entry.configure(state="normal")
            date_var.set("N/A")
            date_entry.configure(state="disabled")
        elif reason["due_days"] is not None:
            # Has a sensible default, but stays editable.
            date_entry.configure(state="normal")
            due = date.today() + timedelta(days=reason["due_days"])
            date_var.set(due.isoformat())
        else:
            # No default -- clear for manual entry.
            date_entry.configure(state="normal")
            date_var.set("")

        _refresh_warning_controls()

    def _refresh_warning_controls():
        """Grey/ungrey the count/warning controls and set the CC-parent
        default for the outcome this checkout would have if submitted now."""
        reason = _resolved_reason()

        # "Count against loan limit" only needs a reason picked to make
        # sense (its default is reason-driven) -- unlike the email controls
        # below, it doesn't also need a person selected.
        counts_checkbox.configure(state="normal" if reason is not None else "disabled")

        if reason is None or selected_user["id"] is None:
            email_checkbox.configure(state="disabled")
            cc_parent_checkbox.configure(state="disabled")
            recipients_var.set("")
            return

        outcome = _determine_checkout_outcome(current_count_holder["count"], counts_var.get(), max_before_override)
        logger.debug("_refresh_warning_controls: outcome=%s", outcome)
        if outcome["requires_email"]:
            email_checkbox.configure(state="normal")
            cc_parent_checkbox.configure(state="normal")
            is_third_or_beyond = outcome["new_count"] >= max_before_override
            cc_parent_var.set(cc_default_third if is_third_or_beyond else cc_default_second)
        else:
            email_checkbox.configure(state="disabled")
            cc_parent_checkbox.configure(state="disabled")
        _update_recipients_display()

    def _update_recipients_display():
        """Refresh the 'will notify' label from current selections (no network calls).

        Hidden entirely (not just blank) when there's nothing to show, so it
        doesn't leave a permanent empty gap for the vast majority of the
        window's lifetime when no 2nd/3rd-checkout warning applies.
        """
        if str(email_checkbox["state"]) == "disabled":
            recipients_var.set("")
            recipients_label.pack_forget()
            return
        recipients = [selected_user["email"]] if selected_user["email"] else []
        if cc_parent_var.get():
            recipients += parents_holder["emails"]
        recipients_var.set("Will notify: " + (", ".join(r for r in recipients if r) or "(no email on file)"))
        recipients_label.pack(fill="x", padx=10, pady=(0, 5), before=notes_field_frame)

    def submit():
        """Validate inputs, apply warnings/overrides, and perform the checkout."""
        logger.debug("submit: starting for asset_tag=%s", asset_tag)

        if selected_user["id"] is None:
            messagebox.showerror("Error", "Pick a person to check the device out to.")
            return

        # Confirm the picked person still exists before trusting it -- a
        # form filled out right as the window opened could otherwise use
        # data that's been cached since long before this window existed.
        # (selected_user is only refreshed when the user interacts with
        # person_ac, so a live-refresh silently invalidating the selection
        # in the background wouldn't otherwise be caught here.)
        if not optionsCache.revalidate_for_submit("assignee", person_ac, transform=optionsCache.filter_to_users):
            selected_user.update({"id": None, "email": "", "name": ""})
            messagebox.showerror("Outdated Selection", "The selected person is no longer available. Please pick again.")
            return

        reason = _resolved_reason()
        if reason is None:
            if reason_by_label.get(reason_var.get(), {}).get("key") == "other":
                messagebox.showerror("Error", "Enter a custom reason for 'Other'.")
            else:
                messagebox.showerror("Error", "Pick a checkout reason.")
            return

        expected_checkin = date_var.get().strip() if reason["checkin_enabled"] else ""
        if not _valid_date_string(expected_checkin):
            messagebox.showerror("Error", "Expected Check-In must be a valid YYYY-MM-DD date, or left blank.")
            return

        notes_text = _get_notes_text()

        outcome = _determine_checkout_outcome(current_count_holder["count"], counts_var.get(), max_before_override)
        counts_flipped_from_default = counts_var.get() != counts_default_holder["value"]
        logger.info(
            "submit: asset=%s user=%s reason=%s counts=%s outcome=%s counts_flipped_from_default=%s",
            asset_tag, selected_user["name"], reason["key"], counts_var.get(), outcome, counts_flipped_from_default,
        )

        if (outcome["requires_override"] or counts_flipped_from_default) and not notes_text:
            reasons_for_note = []
            if outcome["requires_override"]:
                reasons_for_note.append(
                    f"Loan limit exceeded (checkout #{outcome['new_count']}, limit is {max_before_override})."
                )
            if counts_flipped_from_default:
                reasons_for_note.append("The 'Count against loan limit' checkbox was changed from its default.")
            logger.info("submit: required note missing for %s (%s); blocking", selected_user["name"], reasons_for_note)
            messagebox.showerror(
                "Note Required",
                " ".join(reasons_for_note) + " A note is required in order to proceed.",
            )
            return

        if outcome["requires_override"]:
            proceed = messagebox.askyesno(
                "Loan Limit Exceeded",
                f"Loan limit exceeded: this would be checkout #{outcome['new_count']} for {selected_user['name']} "
                f"since the last cutoff (limit is {max_before_override}).\n\n"
                "Override and proceed anyway?",
            )
            if not proceed:
                logger.info("submit: user declined override for %s; aborting", selected_user["name"])
                return
        elif outcome["requires_warning"]:
            messagebox.showwarning(
                "Repeat Loaner Checkout",
                f"This is checkout #{outcome['new_count']} for {selected_user['name']} "
                f"since the last cutoff (limit is {max_before_override}).",
            )

        # Built once and reused for both the checkout action's own note
        # (Snipe-IT's per-action activity note) and the person's running
        # tally note below, so the two stay identical.
        note_line = _format_loan_note_line(
            date.today(), asset_tag, reason["label"], counts_var.get(), notes_text,
        )

        # Perform the checkout API call.
        payload = {
            "checkout_to_type": "user",
            "assigned_user": selected_user["id"],
            "expected_checkin": expected_checkin if expected_checkin else None,
            "note": note_line,
        }
        logger.debug("submit: checkout payload for %s: %s", asset_tag, payload)
        # No is_success override -- default_is_success also rejects
        # Snipe-IT's "HTTP 200 but body says status: error" responses.
        result = call_with_retry(
            f"Check out {asset_tag}",
            lambda: requests.post(
                url + "/hardware/" + str(assetData["id"]) + "/checkout/",
                json=payload,
                headers=get_headers(),
                timeout=20,
            ),
        )
        if result is None:
            logger.error("submit: checkout failed for %s", asset_tag)
            return

        # Log the checkout on the person's Snipe-IT notes -- this is the
        # source of truth the next checkout's tally will read back.
        fresh_user = _fetch_user_by_id(selected_user["id"])
        if not fresh_user:
            logger.error("submit: could not re-fetch user %s; skipping loaner-checkout note", selected_user["id"])
            messagebox.showwarning(
                "Note Not Saved",
                "The checkout succeeded, but the person's record could not be re-fetched, so the "
                "tracking note could not be saved. Future checkout counts for this person may be inaccurate.",
            )
        else:
            new_notes = append_note(fresh_user.get("notes"), note_line)
            if not put_notes_with_retry("users", selected_user["id"], new_notes):
                logger.error("submit: failed to write loaner-checkout note for user %s", selected_user["id"])
                messagebox.showwarning(
                    "Note Not Saved",
                    "The checkout succeeded, but the tracking note could not be saved to the "
                    "person's record. Future checkout counts for this person may be inaccurate.",
                )

        # Send the warning email, if applicable and enabled.
        if outcome["requires_email"] and email_checkbox_var.get():
            student_email = selected_user["email"]
            if not student_email or not is_email(student_email):
                logger.warning(
                    "submit: no valid email on file for %s; skipping warning email", selected_user["name"],
                )
                messagebox.showwarning(
                    "No Email On File", f"No valid email on file for {selected_user['name']}; warning email not sent.",
                )
            else:
                is_third_or_beyond = outcome["new_count"] >= max_before_override
                template = loan_checkout_warning_third if is_third_or_beyond else loan_checkout_warning_second
                content = template(selected_user["name"], reason["label"], expected_checkin or None)
                logger.info(
                    "submit: sending %s-checkout warning email to %s (cc_parent=%s)",
                    "3rd+" if is_third_or_beyond else "2nd", student_email, cc_parent_var.get(),
                )
                message(
                    content,
                    student_email,
                    subject="Loaner Computer Checkout Notice",
                    email_recipient=True,
                    email_parent=cc_parent_var.get(),
                )

        logger.info("submit: loan checkout complete for %s -> user=%s", asset_tag, selected_user["name"])
        checkout_window.destroy()

    # ---- Build the window -----------------------------------------------
    logger.debug("loanCheckout: creating checkout window for %s", asset_tag)
    checkout_window = tk.Toplevel()
    checkout_window.title(f"Loan Checkout — {asset_tag}")
    ensure_tk_thread_pump(checkout_window)
    theme = get_ui_colors()

    # Top row: device info and this semester's history side by side, each in
    # a LabelFrame (same style as the "Asset Functions" box on the main
    # screen) so the window doesn't just grow taller and taller as more
    # sections get added below.
    top_row_frame = tk.Frame(checkout_window)
    top_row_frame.pack(fill="both", expand=True, padx=10, pady=(10, 5))

    asset_info_labelframe = tk.LabelFrame(top_row_frame, text="Asset Info")
    asset_info_labelframe.pack(side="left", fill="both", expand=True, padx=(0, 5))
    info_frame, _info_check_vars = build_asset_info_frame(asset_info_labelframe, var_list)
    info_frame.pack(fill="both", expand=True, padx=5, pady=5)

    # This semester's loan checkout history for the selected person (since
    # the same cutoff as the live count below), populated by _render_history.
    # A plain scrollable Text rather than a Treeview, since Treeview cells
    # can't render multi-line notes -- this shows each checkout's notes
    # verbatim, on their own line(s), the way they were typed. The
    # LabelFrame's own title/border is the label -- no separate one needed.
    history_labelframe = tk.LabelFrame(top_row_frame, text="Loan Checkouts This Semester")
    history_labelframe.pack(side="left", fill="both", expand=True, padx=(5, 0))
    history_text_frame = tk.Frame(history_labelframe)
    history_text_frame.pack(fill="both", expand=True, padx=5, pady=5)
    history_scrollbar = tk.Scrollbar(history_text_frame)
    history_scrollbar.pack(side="right", fill="y")
    # Wide enough that a history line ("YYYY-MM-DD  —  <reason>  —  Counts:
    # Yes", fixed parts totalling 31 chars) doesn't wrap before "Counts:" for
    # any of the *configured* reasons -- computed from the actual reason list
    # rather than hardcoded, so a longer label added later is still covered.
    # Custom "Other" text is unbounded and can still wrap; that's expected.
    _longest_reason_label_len = max((len(r["label"]) for r in reasons), default=0)
    history_text_width = max(40, 31 + _longest_reason_label_len + 4)
    history_text = tk.Text(
        history_text_frame, height=8, width=history_text_width, wrap="word",
        yscrollcommand=history_scrollbar.set, state="disabled",
    )
    history_text.pack(side="left", fill="both", expand=True)
    history_scrollbar.config(command=history_text.yview)

    # Person picker (Checkout To).
    person_frame = tk.Frame(checkout_window)
    person_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(person_frame, text="Checkout To:").pack(side="left")
    person_ac = AutoCompleteEntry(person_frame, width=30)
    person_ac.pack(side="left", expand=True, fill="x")
    person_ac.bind_change(on_person_change)
    # Stale-while-revalidate load: a "loading…" flash only shows the first
    # time "assignee" is ever loaded in this app run, not on every window
    # open. While this window stays open and focused, live-refresh then
    # quietly keeps it current with Snipe-IT instead of requiring a reopen
    # to see changes (e.g. a newly-added user) made elsewhere.
    optionsCache.load_widget(checkout_window, "assignee", person_ac, transform=optionsCache.filter_to_users)
    optionsCache.start_live_refresh(
        checkout_window, "assignee", lambda opts: person_ac.set_options(optionsCache.filter_to_users(opts)),
    )

    # Live-ish checkout-count display for the selected person -- normal-
    # weight descriptive text, with just the number itself bold/enlarged so
    # it's the part that actually stands out.
    history_frame = tk.Frame(checkout_window)
    history_frame.pack(fill="x", padx=10, pady=5)
    count_prefix_var = tk.StringVar(value="Select a person to see their checkout history.")
    count_number_var = tk.StringVar(value="")
    count_number_font = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
    count_number_font.configure(size=count_number_font.actual("size") + 6, weight="bold")
    tk.Label(history_frame, textvariable=count_prefix_var, wraplength=420, justify="left").pack(side="left")
    tk.Label(history_frame, textvariable=count_number_var, font=count_number_font).pack(side="left", padx=(4, 0))

    # Reason picker, with an "Other" free-text box shown only when needed.
    reason_frame = tk.Frame(checkout_window)
    reason_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(reason_frame, text="Checkout Reason:").pack(side="left")
    reason_combobox = ttk.Combobox(
        reason_frame, textvariable=reason_var, state="readonly",
        values=[r["label"] for r in reasons], width=_REASON_COMBOBOX_WIDTH_NORMAL,
    )
    reason_combobox.pack(side="left", expand=True, fill="x")
    reason_combobox.bind("<<ComboboxSelected>>", on_reason_change)
    other_entry = tk.Entry(reason_frame, textvariable=other_text_var, width=20)
    # other_entry is packed/unpacked by on_reason_change; not shown initially.
    # Re-check "other" text on every keystroke, not just when the reason
    # dropdown itself changes -- otherwise the count/warning controls stay
    # greyed out until some unrelated event happens to refresh them.
    other_text_var.trace_add("write", lambda *_args: _refresh_warning_controls())

    # Expected check-in date -- keystroke-validated plain Entry (same pattern
    # as makeCharger.py's Purchase Date field) rather than tkcalendar.DateEntry
    # (unreliable popup positioning across monitors/desktops, and its field
    # couldn't reliably be cleared). Autofilled/locked per-reason by
    # on_reason_change above.
    date_frame, date_var, date_entry = build_date_entry_frame(checkout_window, "Expected Check-In (YYYY-MM-DD):")

    # Count-against-limit + warning-email + CC-parent controls, all in one
    # row: "Count against loan limit" defaults off for repair, on otherwise
    # (set by on_reason_change), but is always editable -- its state at
    # Submit time is the actual, final say on whether this checkout counts,
    # regardless of the reason picked. It's greyed out until a reason is
    # selected (same as the email controls, which additionally need a
    # person picked and the 2nd/3rd-checkout threshold reached).
    checkbox_row_frame = tk.Frame(checkout_window)
    checkbox_row_frame.pack(padx=10, pady=5)
    counts_checkbox = tk.Checkbutton(
        checkbox_row_frame, text="Count against loan limit", variable=counts_var,
        command=_refresh_warning_controls, state="disabled",
    )
    counts_checkbox.pack(side="left")
    email_checkbox = tk.Checkbutton(
        checkbox_row_frame, text="Send warning email", variable=email_checkbox_var,
        command=_update_recipients_display, state="disabled",
    )
    email_checkbox.pack(side="left", padx=(10, 0))
    cc_parent_checkbox = tk.Checkbutton(
        checkbox_row_frame, text="CC Parent(s)", variable=cc_parent_var,
        command=_update_recipients_display, state="disabled",
    )
    cc_parent_checkbox.pack(side="left", padx=(10, 0))

    recipients_var = tk.StringVar(value="")
    recipients_label = tk.Label(checkout_window, textvariable=recipients_var, wraplength=420, justify="left", fg=theme["muted_fg"])
    # Not packed here -- _update_recipients_display() packs/unpacks it as
    # there is/isn't something to show, so it takes up no space when blank.

    # Freeform Notes -- always optional, except when the checkout requires
    # an override past the loan limit, where submit() requires it non-blank
    # (see _get_notes_text/_on_notes_focus_in/_on_notes_focus_out above for
    # the grey placeholder guidance that explains this, shown in the box
    # itself -- word-wrapped -- rather than a long label above it).
    notes_field_frame = tk.Frame(checkout_window)
    notes_field_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(notes_field_frame, text="Notes:").pack(anchor="w")
    notes_text_widget = tk.Text(notes_field_frame, height=3, width=40, wrap="word", relief="solid", borderwidth=1)
    notes_text_widget.pack(fill="x")
    notes_text_widget.insert("1.0", _NOTES_PLACEHOLDER_TEXT)
    notes_text_widget.configure(fg=theme["muted_fg"])
    notes_text_widget.bind("<FocusIn>", _on_notes_focus_in)
    notes_text_widget.bind("<FocusOut>", _on_notes_focus_out)

    # Submit button.
    submit_button = tk.Button(checkout_window, text="Submit", command=submit)
    submit_button.pack(pady=10)

    # Soft Message Frame (kept for visual consistency with checkoutTo.py/checkIn.py).
    soft_message_frame, soft_message = build_soft_message_frame(checkout_window)

    # Center the window on screen.
    center_window(checkout_window)

    # Ensure API user prompt (if needed) happens on the UI thread.
    get_api_key()

    return f"Loan checkout window opened for {asset_tag}. Submit to complete."
