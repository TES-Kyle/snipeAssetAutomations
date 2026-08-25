"""
Consisterizer — editor for Snipe-IT assets

Features
- Table with Field / Updates / Reset / Current / Result columns
- Template-driven defaults (tokens: {username}, {serial}, {today}, {tomorrow}, {field}, {field_current})
- Special defaults: {empty} to explicitly clear, {has_value} to require non-empty
- “Maintain selected defaults” option (live-push defaults into checked rows)
- Batch mode with centered Asset Tag box (Enter and Submit share identical flow)
- Script runner panel (routing-style) for “on submit” actions
- Sticky table header + smooth, limited scrolling
- Dynamic column widths
- Saves to Snipe-IT via PATCH /hardware/{id} with retry on failure
- If assigned user is cleared, performs POST /hardware/{id}/checkin to unassign
- Quiet success via status line (e.g., “Saved 12345.”)

Notes
- Status and Model are non-clearable Autocomplete fields (blank -> keep current)
- Assigned To is an Autocomplete field that accepts “{empty}” to clear (unassign)
- Defaults comparison highlights both Result and Updates controls when mismatched
"""

import json
import logging
import os
import platform
import re
from datetime import datetime, timedelta

import requests
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter import font as tkfont

from utilities.autocomplete import AutoCompleteEntry
from utilities.otherApiBits import (
    getAssetInfo,
    getAllStatusOptions,
    getAllAssigneeOptions,
    getAllModelOptions,
)
from utilities.logging_utils import configure_logging
from utilities.settings import get_settings
from utilities.Key import API_URL_Base  # API creds
from utilities.api_user import get_api_headers, get_api_key
from utilities.theme import get_ui_colors
from utilities.tk_geometry import center_window
from utilities.validation import valid_asset_tag
from utilities.api_retry import call_with_retry

from consisterizer.consisterizerScriptsRouting import (
    submit_func_list,
    submit_func_listTXT,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Constants & Config
# =============================================================================

FIELD_ORDER = [
    "asset_tag",
    "name",
    "serial",
    "model",
    "status",
    "assigned_to",
    "expected_checkin",
    "purchase_date",
    "purchase_cost",
    "order_number",
    "box_number",
    "notes",
]

DATE_FIELDS = {"expected_checkin", "purchase_date"}
PLACEHOLDERS = {
    "asset_tag": "4–5 digits (e.g., 12345)",
    "expected_checkin": "YYYY-MM-DD",
    "purchase_date": "YYYY-MM-DD",
}

HELP_TEXT = """
Consisterizer — Quick Guide

WHAT IT DOES
- Edits one asset’s fields in Snipe-IT using a “grid”:
  Field | Updates | Reset | Current | Result
- “Updates” is what YOU type/select; “Result” shows what will be saved after expansions.
- Saves via PATCH /hardware/{id}, and if Assigned To is cleared, it also posts a CHECKIN to unassign.
- Optional “on submit” scripts run after a save.

BATCH vs ONE-AT-A-TIME
- Batch mode (checked): Submit current, then switch to the asset tag typed in the box. The box is centered up top; Enter runs submit+switch.
- One-at-a-time (unchecked): Submit current, then the window clears CURRENT/RESULT and waits. Your Updates stay put so you can scan the next tag and reuse them.
- Clear button: Skip the loaded asset WITHOUT saving or editing it in Snipe-IT. Purges CURRENT/RESULT and waits for the next tag, same as after a submit — but Updates/Reset stay put so you don't lose values you want to reuse.

UPDATES COLUMN
- Text boxes accept literal values or templates (see TOKENS).
- Autocompletes: Status, Model, Assigned To.
  • Status & Model are non-clearable; leave blank to keep current; you must pick from the list to change.
  • Assigned To accepts “{empty}” to unassign (will do a CHECKIN).
- Placeholders show expected formats (e.g., YYYY-MM-DD).

RESET COLUMN
- Check a row’s “Reset” to apply the active default into Updates when you click Reset (header) OR when “Maintain selected defaults” is on.
- “Maintain selected defaults” live-pushes default values into checked rows as defaults change.

DEFAULTS & TOKENS
- Defaults are loaded from defaultProfiles.json (consisterizer/defaultProfiles.json).
- Each rule has optional conditions and a defaults map. Rules apply by priority (highest first).
- Template tokens you can use inside Updates:
  • {today}           → YYYY-MM-DD
  • {tomorrow}        → YYYY-MM-DD (today + 1)
  • {username}        → Assigned user’s username (live; cleared if {empty} Assigned To)
  • {field}           → The evaluated value of another field (e.g., {name}, {serial})
  • {field_current}   → That field’s CURRENT value (before changes)
  • {empty}           → Explicit clear for clearable fields (text/date/cost) OR special clear for Assigned To
  • {blank}           → Explicit “keep current” marker (same as leaving Updates blank)
- You can also reference dotted paths from the raw Snipe asset payload (e.g., {status_label.name}, {model.name}). Unknown tokens are left as-is.
- Special default marker {has_value} (in defaults): requires the field to be non-empty; mismatches are highlighted.

RESULT & HIGHLIGHTING
- “Result” shows the final value that will be sent, after templates/tokens resolve.
- If a field’s Result doesn’t match the active default (or a {has_value} default is empty), it highlights red.

VALIDATION / CLEARING
- Asset Tag must be 4–5 digits when you change it.
- Dates must be YYYY-MM-DD ({empty} clears).
- Clear rules:
  • Text fields (name, serial, order_number, notes): {empty} string clears
  • Date fields (purchase_date, expected_checkin): {empty} clears
  • purchase_cost: {empty} clears
  • Assigned To: type {empty} to unassign (handled via CHECKIN)
- Status/Model can’t be cleared; blank keeps current.

SCRIPTS (On Submit)
- Tick the scripts you want; they run AFTER a successful save.
- In one-at-a-time mode, scripts run immediately after submit; window then waits for the next asset.

KEYBOARD
- Enter in the top asset-tag box = Submit (+ switch in batch mode).
- F1 = Help.

ALIASES (Optional)
- You can open Consisterizer with alias payloads to pre-fill Updates, toggle batch mode, select scripts, and set/reset rows. Example:
  {
    "title": "Check-in",
    "batch_mode": false,
    "maintain_defaults": true,
    "reset": ["status", "assigned_to", "notes"],
    "set": {
      "status": "In Storage",
      "assigned_to": "{empty}",
      "notes": "Checked in on {today} by {username}"
    },
    "scripts": "all"
  }

Troubleshooting
- If API calls fail, you’ll see a retry/cancel prompt (PATCH) or error dialogs.
- If “assigned to” was cleared but the asset is still assigned, ensure the CHECKIN succeeded (network errors can block it).
"""


# Fixed pixel widths for the Field and Reset columns.
FIELD_COL_PX = 180
RESET_COL_PX = 90
# Minimum window dimensions so the layout is usable on small screens.
MIN_W = 700
MIN_H = 400

# Minimum widths for the three flexible columns (Updates / Current / Result).
FLEX_MIN_UPDATES = 140
FLEX_MIN_CURRENT = 120
FLEX_MIN_RESULT = 120

# Path to the JSON file that holds conditional default profile rules.
TEMPLATES_PATH = os.path.join("consisterizer", "defaultProfiles.json")

# Fast membership test against FIELD_ORDER.
KNOWN_FIELDS = set(FIELD_ORDER)

# Regex that matches any {token} placeholder in template strings.
TOKEN_RE = re.compile(r"\{([^{}]+)\}")

# Internal sentinel that marks a "{has_value}" default constraint.
HAS_VALUE_SENTINEL = "<<HAS_VALUE>>"

# API base normalization (accepts with/without trailing slash)
SNIPE_BASE = API_URL_Base.rstrip("/")  # e.g., https://host/api/v1


# =============================================================================
# Small Helpers (module-level)
# =============================================================================

def _norm_field_key(k: str) -> str:
    """Normalize field labels to consistent snake_case keys.

    Args:
        k: Raw field label string (e.g. 'Asset Tag').

    Returns:
        Lowercase, space-stripped, underscore-separated key (e.g. 'asset_tag'),
        or empty string for non-string input.
    """
    logger.debug("_norm_field_key: k=%s", k)
    if not isinstance(k, str):
        logger.debug("_norm_field_key: non-string input, returning empty")
        return ""
    return k.strip().lower().replace(" ", "_")


def valid_date(value: str) -> bool:
    """Validate a date string is in YYYY-MM-DD format.

    Args:
        value: String to test.

    Returns:
        True if the string parses as a valid YYYY-MM-DD date, False otherwise.
    """
    logger.debug("valid_date: value=%s", value)
    try:
        datetime.strptime(value, "%Y-%m-%d")
        logger.debug("valid_date: %s is valid", value)
        return True
    except Exception:
        logger.debug("valid_date: %s is not a valid YYYY-MM-DD date", value)
        return False


def _widget_get_text(widget: tk.Widget) -> str:
    """Return current text content from an Entry or Text widget.

    Args:
        widget: A tk.Entry or tk.Text widget.

    Returns:
        The widget's current text as a string.
    """
    logger.debug("_widget_get_text: widget_type=%s", type(widget).__name__)
    if isinstance(widget, tk.Text):
        return widget.get("1.0", "end-1c")
    return widget.get()


def _widget_set_text(widget: tk.Widget, value: str):
    """Set text content for an Entry or Text widget.

    Args:
        widget: A tk.Entry or tk.Text widget.
        value: String to insert. Empty string clears the widget.
    """
    logger.debug("_widget_set_text: widget_type=%s value=%s", type(widget).__name__, value)
    if isinstance(widget, tk.Text):
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)
    else:
        widget.delete(0, tk.END)
        if value:
            widget.insert(0, value)


def attach_placeholder(widget: tk.Widget, text: str):
    """Attach grey placeholder behavior to an Entry or Text widget.

    The placeholder text is shown in grey when the widget has no content and
    is not focused.  It is hidden on focus-in and restored on focus-out if the
    widget is still empty.

    Args:
        widget: A tk.Entry or tk.Text widget to receive placeholder behavior.
        text: The placeholder string to display.
    """
    logger.debug("attach_placeholder: widget_type=%s text=%s", type(widget).__name__, text)
    if not isinstance(widget, (tk.Entry, tk.Text)):
        logger.debug("attach_placeholder: unsupported widget type, skipping")
        return

    # Capture the widget's configured text colour BEFORE applying placeholder
    # styling so we can restore it faithfully on focus-in.  This avoids
    # hardcoding "black" which would be invisible in dark mode.
    try:
        _normal_fg = widget.cget("fg")
    except Exception:
        try:
            _normal_fg = widget.cget("foreground")
        except Exception:
            _normal_fg = "black"

    widget.placeholder_text = text
    widget.placeholder_active = True
    _widget_set_text(widget, text)
    try:
        widget.config(fg="grey")
    except Exception:
        pass

    def _on_focus_in(_e):
        """Clear placeholder text when the widget receives focus."""
        logger.debug("_on_focus_in: placeholder_active=%s", getattr(widget, "placeholder_active", False))
        if getattr(widget, "placeholder_active", False):
            logger.debug("_on_focus_in: clearing placeholder, restoring fg=%s", _normal_fg)
            _widget_set_text(widget, "")
            try:
                widget.config(fg=_normal_fg)
            except Exception:
                pass
            widget.placeholder_active = False

    def _on_focus_out(_e):
        """Restore placeholder text when leaving an empty widget."""
        current = _widget_get_text(widget).strip()
        logger.debug("_on_focus_out: current_text=%s", current)
        if current == "":
            logger.debug("_on_focus_out: restoring placeholder text=%s", widget.placeholder_text)
            widget.placeholder_active = True
            _widget_set_text(widget, widget.placeholder_text)
            try:
                widget.config(fg="grey")
            except Exception:
                pass

    widget.bind("<FocusIn>", _on_focus_in)
    widget.bind("<FocusOut>", _on_focus_out)


def is_effective_empty(widget: tk.Widget) -> bool:
    """Return True if a widget is empty or currently showing placeholder text.

    Args:
        widget: A tk.Entry or tk.Text widget (possibly with placeholder attached).

    Returns:
        True if no real user content is present.
    """
    logger.debug("is_effective_empty: widget_type=%s", type(widget).__name__)
    return getattr(widget, "placeholder_active", False) or _widget_get_text(widget).strip() == ""


def extract_current_values(assetData: dict) -> dict:
    """Extract a normalized set of editable fields from a Snipe-IT asset payload.

    Flattens nested objects (model, status_label, assigned_to, dates) into
    simple string values keyed by FIELD_ORDER names.  All missing values become
    empty strings rather than None so callers can compare safely.

    Args:
        assetData: Raw asset dict returned by the Snipe-IT API (or getAssetInfo).

    Returns:
        Dict with keys matching FIELD_ORDER plus '_assigned_username', all str.
    """
    logger.debug("extract_current_values: asset_tag=%s", assetData.get("asset_tag"))
    # Simple scalar fields — coerce None to "".
    asset_tag = assetData.get("asset_tag") or ""
    name = assetData.get("name") or ""
    serial = assetData.get("serial") or ""
    notes = assetData.get("notes") or ""
    purchase_cost = assetData.get("purchase_cost") or ""
    order_number = assetData.get("order_number") or ""
    # Nested object fields — Snipe-IT returns these as {"id": ..., "name": ...}.
    model_name = (assetData.get("model") or {}).get("name") or ""
    status_name = (assetData.get("status_label") or {}).get("name") or ""
    # Assigned-to can be a user or location; we want the display name and username.
    assigned_obj = (assetData.get("assigned_to") or {})
    assigned_to = assigned_obj.get("name") or ""
    assigned_username = assigned_obj.get("username") or ""
    if not assigned_username:
        # Fall back to deriving a username from the email address.
        email = assigned_obj.get("email") or ""
        if "@" in email:
            assigned_username = email.split("@", 1)[0]
    # Date fields are returned as {"date": "YYYY-MM-DD", ...}; extract just the date string.
    purchase_date = (assetData.get("purchase_date") or {}).get("date") or ""
    expected_checkin = (assetData.get("expected_checkin") or {}).get("date") or ""
    # Custom field: Box Number lives under custom_fields["Box Number"]["value"].
    custom_fields = assetData.get("custom_fields") or {}
    box_number = (custom_fields.get("Box Number") or {}).get("value") or ""

    logger.debug("extract_current_values: model=%s status=%s assigned_to=%s", model_name, status_name, assigned_to)
    base = {
        "asset_tag": asset_tag,
        "name": name,
        "serial": serial,
        "model": model_name,
        "status": status_name,
        "assigned_to": assigned_to,
        "expected_checkin": expected_checkin,
        "purchase_date": purchase_date,
        "purchase_cost": purchase_cost,
        "order_number": order_number,
        "box_number": box_number,
        "notes": notes,
        "_assigned_username": assigned_username,
    }
    logger.debug("extract_current_values: returning %s fields", len(base))
    return base


def _open_help(parent):
    """Open (or focus) a simple read-only help window."""
    logger.debug("_open_help: called")
    # Reuse a single help window if already open
    existing = getattr(parent, "_help_win", None)
    if existing and existing.winfo_exists():
        logger.debug("_open_help: help window already open, raising it")
        try:
            existing.lift()
            existing.focus_force()
        except Exception:
            pass
        return

    logger.info("_open_help: creating new help window")
    win = tk.Toplevel(parent)
    parent._help_win = win
    win.title("Consisterizer Help")
    win.minsize(560, 420)

    # Layout
    frm = ttk.Frame(win)
    frm.pack(fill="both", expand=True, padx=8, pady=8)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(0, weight=1)

    # Text + scrollbar
    txt = tk.Text(frm, wrap="word")
    vsb = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=vsb.set)
    txt.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")

    # Insert + make read-only
    try:
        txt.insert("1.0", HELP_TEXT.strip())
    except Exception:
        txt.insert("1.0", "Help unavailable.")
    txt.configure(state="disabled")

    # Close button
    btns = ttk.Frame(frm)
    btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    # Esc closes
    win.bind("<Escape>", lambda e: win.destroy())


# =============================================================================
# Main Entry
# =============================================================================

def consisterizer(asset_tag, alias=None, _checked_values=None):
    """Open the Consisterizer window for a given asset tag.

    This editor allows batch updates to Snipe-IT assets, highlights
    mismatches against defaults, and runs optional post-save scripts.

    Args:
        asset_tag: Asset tag to load on startup.
        alias: Optional alias payload to prefill fields or toggle options.
        _checked_values: Legacy placeholder (unused).
    """
    configure_logging()
    logger.info("Opening Consisterizer for %s", asset_tag)
    # Resolve OS theme once per window open so all widget colours are consistent.
    # These locals must be defined BEFORE any widget or style creation that uses
    # them — Python's scoping rules treat any name assigned anywhere in a function
    # as local throughout, so assigning them late would cause UnboundLocalError.
    _theme = get_ui_colors()
    logger.debug("consisterizer: theme resolved, dark=%s", _theme["bg"] == "#1e1e1e")
    HEADER_BG     = _theme["header_bg"]
    HEADER_FG     = _theme["header_fg"]
    ROW_BG_1      = _theme["row_bg_1"]
    ROW_BG_2      = _theme["row_bg_2"]
    ROW_FG        = _theme["fg"]
    ENTRY_BG      = _theme["entry_bg"]
    ENTRY_FG      = _theme["entry_fg"]
    ERROR_BG      = _theme["error_bg"]
    ERROR_FG      = _theme["error_fg"]
    SEPARATOR_COLOR = _theme["separator"]

    # -------------------------------------------------------------------------
    # Window
    # -------------------------------------------------------------------------
    win = tk.Toplevel()
    win.title(f"Consisterizer — {asset_tag}")
    # Size the window to fill the screen (but never smaller than MIN_W x MIN_H),
    # then center it.
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    W = max(MIN_W, sw)
    H = max(MIN_H, sh)
    center_window(win, width=W, height=H)
    win.minsize(MIN_W, MIN_H)
    win.lift()
    # F1 opens the in-app help dialog from anywhere in the window.
    win.bind("<F1>", lambda e: _open_help(win))
    try:
        win.focus_force()
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # Data & Options (preload once)
    # -------------------------------------------------------------------------
    _vl, assetData = getAssetInfo(asset_tag)
    logger.debug("Loaded asset data for Consisterizer: %s", asset_tag)
    current_map = extract_current_values(assetData)
    default_font = tkfont.nametofont("TkDefaultFont")

    # Preload options once to avoid repeated API calls as the UI renders.
    status_options = getAllStatusOptions()
    assignee_options = getAllAssigneeOptions()
    model_options = getAllModelOptions()

    def _prepend_special_option(options, label, opt_type):
        """Ensure a special sentinel label exists at the top of an autocomplete list.

        Used to inject virtual options like '{blank}' and '{empty}' that have no
        real Snipe-IT IDs but need to appear in the dropdown for template tokens.

        Args:
            options: Existing list of autocomplete option dicts.
            label: Label string to prepend (e.g. '{blank}', '{empty}').
            opt_type: Type string for the synthetic option (e.g. 'blank', 'empty').

        Returns:
            The options list with the sentinel prepended (or unchanged if already present).
        """
        logger.debug("_prepend_special_option: label=%s opt_type=%s", label, opt_type)
        options = list(options or [])
        for opt in options:
            if str(opt.get("label") or "").strip() == label:
                logger.debug("_prepend_special_option: label already present, skipping prepend")
                return options
        logger.debug("_prepend_special_option: prepending special option label=%s", label)
        return [{
            "label": label,
            "id": None,
            "type": opt_type,
            "username": "",
            "email": "",
            "meta": {},
        }] + options

    # Inject sentinel options into each autocomplete list:
    # - status/model get {blank} (keep current; they cannot be cleared to empty)
    # - assigned_to gets both {empty} (explicit unassign) and {blank} (keep current)
    status_options = _prepend_special_option(status_options, "{blank}", "blank")
    model_options = _prepend_special_option(model_options, "{blank}", "blank")
    assignee_options = _prepend_special_option(assignee_options, "{empty}", "empty")
    assignee_options = _prepend_special_option(assignee_options, "{blank}", "blank")

    # live value for {username} token
    runtime_username = tk.StringVar(value=current_map.get("_assigned_username", ""))

    def _username_from_option(sel: dict | None) -> str:
        """Derive a plain username string from an autocomplete user selection dict.

        Tries the 'username' key first, then derives from 'email', then checks
        the nested 'meta' sub-dict in the same order.

        Args:
            sel: Autocomplete selection dict (or None).

        Returns:
            Username string, or empty string if none could be determined.
        """
        logger.debug("_username_from_option: sel_type=%s", (sel or {}).get("type"))
        if not sel or sel.get("type") != "user":
            logger.debug("_username_from_option: not a user selection, returning empty")
            return ""
        u = (sel.get("username") or "").strip()
        if u:
            logger.debug("_username_from_option: found username=%s", u)
            return u
        em = (sel.get("email") or "").strip()
        if "@" in em:
            derived = em.split("@", 1)[0]
            logger.debug("_username_from_option: derived username from email=%s", derived)
            return derived
        meta = sel.get("meta") or {}
        u = (meta.get("username") or "").strip()
        if u:
            logger.debug("_username_from_option: found username in meta=%s", u)
            return u
        em = (meta.get("email") or "").strip()
        if "@" in em:
            derived = em.split("@", 1)[0]
            logger.debug("_username_from_option: derived username from meta email=%s", derived)
            return derived
        logger.debug("_username_from_option: no username found, returning empty")
        return ""

    # -------------------------------------------------------------------------
    # Styles
    # -------------------------------------------------------------------------
    style = ttk.Style(win)
    # Error style uses theme-appropriate colours so it's visible in dark mode.
    try:
        style.configure("ConsistError.TEntry", fieldbackground=ERROR_BG, foreground=ERROR_FG)
    except Exception:
        style.configure("ConsistError.TEntry", foreground=ERROR_FG)

    # -------------------------------------------------------------------------
    # Top Bar — centered Asset Tag + Batch toggle
    # -------------------------------------------------------------------------
    top = ttk.Frame(win)
    top.pack(fill="x", padx=12, pady=(12, 6))
    top.grid_columnconfigure(0, weight=1)
    top.grid_columnconfigure(1, weight=1)
    top.grid_columnconfigure(2, weight=1)

    center = ttk.Frame(top)
    center.grid(row=0, column=1, sticky="n")
    ttk.Label(center, text="Asset Tag:").grid(row=0, column=0, padx=(0, 6))

    asset_tag_var = tk.StringVar(value="")  # start blank for scanning next
    asset_entry = ttk.Entry(center, textvariable=asset_tag_var, width=18)

    def _validate_tag_key(newval):
        """Validate asset tag input for numeric length constraints."""
        logger.debug("_validate_tag_key: newval=%s", newval)
        return (newval == "") or (newval.isdigit() and len(newval) <= 5)

    asset_entry.configure(validate="key", validatecommand=(win.register(_validate_tag_key), "%P"))
    asset_entry.grid(row=0, column=1)

    # Right side: help button + batch toggle
    right = ttk.Frame(top)
    right.grid(row=0, column=2, sticky="e")

    def _help_click():
        """Open the help dialog for Consisterizer."""
        logger.debug("_help_click: help button pressed")
        _open_help(win)

    # U+20DD is COMBINING ENCLOSING CIRCLE; "?\u20DD" renders as circled ? on most fonts.
    # Fallback to '❓' if needed.
    help_label = "?\u20DD"
    try:
        _ = help_label + ""  # touch to avoid linter
    except Exception:
        help_label = "❓"  # fallback

    help_btn = ttk.Button(right, text=help_label, width=2, command=_help_click)
    help_btn.pack(side="right", padx=(6, 0))

    batch_mode_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(right, text="Batch mode", variable=batch_mode_var).pack(side="right")

    def _clear_entry_style_if_valid(*_):
        """Clear error styling when the asset tag looks valid."""
        v = asset_tag_var.get().strip()
        logger.debug("_clear_entry_style_if_valid: v=%s", v)
        if re.match(r"^\d{0,5}$", v or ""):
            logger.debug("_clear_entry_style_if_valid: clearing error style")
            try:
                asset_entry.configure(style="")
            except Exception:
                pass

    asset_tag_var.trace_add("write", _clear_entry_style_if_valid)

    # Track whether there is an active/loaded asset
    has_current_asset = tk.BooleanVar(value=True)  # we start with an asset loaded

    def _update_submit_enabled(*_):
        """Enable or disable submit/clear based on active asset state."""
        has_asset = has_current_asset.get()
        logger.debug("_update_submit_enabled: has_current_asset=%s", has_asset)
        try:
            submit_btn.configure(state=("normal" if has_asset else "disabled"))
        except Exception:
            pass
        try:
            clear_btn.configure(state=("normal" if has_asset else "disabled"))
        except Exception:
            pass

    _update_submit_enabled()
    has_current_asset.trace_add("write", _update_submit_enabled)

    # -------------------------------------------------------------------------
    # Options Row
    # -------------------------------------------------------------------------
    opts = ttk.Frame(win)
    opts.pack(fill="x", padx=12, pady=(0, 6))
    maintain_defaults_var = tk.BooleanVar(value=False)
    bypass_warnings_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(opts, text="Maintain selected defaults", variable=maintain_defaults_var).pack(side="left", anchor="w")
    ttk.Checkbutton(opts, text="Bypass default warnings", variable=bypass_warnings_var).pack(side="left", anchor="w", padx=(16, 0))

    # -------------------------------------------------------------------------
    # Grid (sticky header + scrollable body)
    # -------------------------------------------------------------------------
    grid_box = ttk.LabelFrame(win, text="Fields")
    grid_box.pack(fill="both", expand=True, padx=12, pady=6)
    grid_box.grid_columnconfigure(0, weight=1)

    def _configure_grid_columns(container):
        """Apply the shared 5-column layout (Field/Updates/Reset/Current/Result).

        Used for both the fixed header and the scrollable body so their
        columns stay pixel-aligned.
        """
        container.grid_columnconfigure(0, weight=0, minsize=FIELD_COL_PX)
        container.grid_columnconfigure(1, weight=1, uniform="flex", minsize=FLEX_MIN_UPDATES)
        container.grid_columnconfigure(2, weight=0, minsize=RESET_COL_PX)
        container.grid_columnconfigure(3, weight=1, uniform="flex", minsize=FLEX_MIN_CURRENT)
        container.grid_columnconfigure(4, weight=1, uniform="flex", minsize=FLEX_MIN_RESULT)

    # Header (fixed)
    header = tk.Frame(grid_box, bg=HEADER_BG)
    header.grid(row=0, column=0, sticky="ew")

    _configure_grid_columns(header)

    tk.Label(header, text="Field",   font=("Arial", 12, "bold"), bg=HEADER_BG, fg=HEADER_FG).grid(row=0, column=0, sticky="w", padx=6, pady=4)
    tk.Label(header, text="Updates", font=("Arial", 12, "bold"), bg=HEADER_BG, fg=HEADER_FG).grid(row=0, column=1, sticky="w", padx=6, pady=4)
    reset_selected_btn = tk.Button(header, text="Reset")
    reset_selected_btn.grid(row=0, column=2, sticky="w", padx=6, pady=4)
    tk.Label(header, text="Current", font=("Arial", 12, "bold"), bg=HEADER_BG, fg=HEADER_FG).grid(row=0, column=3, sticky="w", padx=6, pady=4)
    tk.Label(header, text="Result",  font=("Arial", 12, "bold"), bg=HEADER_BG, fg=HEADER_FG).grid(row=0, column=4, sticky="w", padx=6, pady=4)
    # Thin separator line between header and scrollable body.
    tk.Frame(header, bg=SEPARATOR_COLOR, height=1).grid(row=1, column=0, columnspan=5, sticky="ew")

    # Scrollable body
    grid_canvas = tk.Canvas(grid_box, highlightthickness=0, borderwidth=0, height=80)
    vscroll = ttk.Scrollbar(grid_box, orient="vertical", command=grid_canvas.yview)
    grid_canvas.configure(yscrollcommand=vscroll.set)

    grid_canvas.grid(row=1, column=0, sticky="nsew")
    vscroll.grid(row=0, column=1, rowspan=2, sticky="ns")
    grid_box.grid_rowconfigure(1, weight=1)

    grid_inner = tk.Frame(grid_canvas)
    inner_window = grid_canvas.create_window((0, 0), window=grid_inner, anchor="nw")

    # Body columns: must match header
    _configure_grid_columns(grid_inner)

    # Keep scroll/wrap/widths in sync
    rows_by_key = {}

    def _update_scroll_state():
        """Update scrollregion and enable/disable the scrollbar."""
        logger.debug("_update_scroll_state: updating scrollregion")
        grid_canvas.configure(scrollregion=grid_canvas.bbox("all"))
        bbox = grid_canvas.bbox("all") or (0, 0, 0, 0)
        content_h = bbox[3] - bbox[1]
        fits = content_h <= max(1, grid_canvas.winfo_height())
        logger.debug("_update_scroll_state: content_h=%s canvas_h=%s fits=%s", content_h, grid_canvas.winfo_height(), fits)
        try:
            vscroll.state(["disabled"] if fits else ["!disabled"])
        except Exception:
            vscroll.configure(state=("disabled" if fits else "normal"))
        if fits:
            grid_canvas.yview_moveto(0.0)

    def _apply_wraplengths():
        """Apply wrap lengths based on available column width."""
        total = grid_canvas.winfo_width()
        logger.debug("_apply_wraplengths: canvas_width=%s", total)
        if total <= 1:
            logger.debug("_apply_wraplengths: canvas not yet sized, skipping")
            return
        fixed = FIELD_COL_PX + RESET_COL_PX + 24
        remaining = max(0, total - fixed)
        per_col = max(100, remaining // 3)
        logger.debug("_apply_wraplengths: per_col=%s", per_col)
        for k, rr in rows_by_key.items():
            try:
                rr["res_lbl"].configure(wraplength=per_col - 12)
            except Exception:
                pass

    def _sync_layout(_e=None):
        """Sync canvas layout and wrapping when sizes change."""
        logger.debug("_sync_layout: canvas_width=%s", grid_canvas.winfo_width())
        grid_canvas.itemconfigure(inner_window, width=grid_canvas.winfo_width())
        _update_scroll_state()
        _apply_wraplengths()

    grid_inner.bind("<Configure>", lambda e: _sync_layout(), add="+")
    grid_canvas.bind("<Configure>", _sync_layout, add="+")

    # Smooth, pointer-gated wheel scrolling
    _IS_MAC = platform.system() == "Darwin"
    _SC_UNITS = 1  # slow & steady

    def _pointer_over_canvas():
        """Return True if the pointer is currently over the scrollable grid canvas.

        Used to gate wheel-scroll events so the grid only scrolls when the
        cursor is actually hovering over it.

        Returns:
            True if the pointer is over grid_canvas or grid_inner, False otherwise.
        """
        try:
            x, y = win.winfo_pointerx(), win.winfo_pointery()
            w = win.winfo_containing(x, y)
            while w is not None:
                if w is grid_canvas or w is grid_inner:
                    return True
                w = w.master
        except Exception:
            pass
        return False

    def _on_mousewheel(event):
        """Handle mousewheel scrolling with pointer gating.

        Scrolls the grid canvas only when the pointer is over it and the
        content is taller than the visible area.  Handles macOS delta events,
        Linux Button-4/5 events, and Windows delta events uniformly.

        Args:
            event: Tk event with .delta and/or .num attributes.
        """
        bbox = grid_canvas.bbox("all") or (0, 0, 0, 0)
        content_h = bbox[3] - bbox[1]
        over_canvas = _pointer_over_canvas()
        logger.debug("_on_mousewheel: over_canvas=%s content_h=%s", over_canvas, content_h)
        if not over_canvas or content_h <= max(1, grid_canvas.winfo_height()):
            return
        if _IS_MAC:
            step = -_SC_UNITS if event.delta > 0 else _SC_UNITS
            logger.debug("_on_mousewheel: mac scroll step=%s", step)
            grid_canvas.yview_scroll(step, "units")
        else:
            if getattr(event, "num", None) == 4:
                logger.debug("_on_mousewheel: linux scroll up")
                grid_canvas.yview_scroll(-_SC_UNITS, "units")
            elif getattr(event, "num", None) == 5:
                logger.debug("_on_mousewheel: linux scroll down")
                grid_canvas.yview_scroll(_SC_UNITS, "units")
            else:
                steps = int(-event.delta / 120) if event.delta else 0
                if steps:
                    logger.debug("_on_mousewheel: windows scroll steps=%s", steps)
                    grid_canvas.yview_scroll(steps * _SC_UNITS, "units")

    win.bind_all("<MouseWheel>", _on_mousewheel)
    win.bind_all("<Button-4>", _on_mousewheel)
    win.bind_all("<Button-5>", _on_mousewheel)

    def _safe_get_fg(widget, default):
        """Return a widget's foreground colour, or a fallback if unavailable."""
        try:
            return widget.cget("foreground")
        except Exception:
            return default

    def _make_simple_ac_on_change(ac_ref, cur_val, rr, field_name):
        """Build an on_change callback for a non-clearable autocomplete field.

        Reverts to the current value when blank/empty, otherwise adopts the
        typed text. Shared by the 'status' and 'model' fields, whose
        on_change logic is identical apart from the log label.
        """
        def on_change():
            txt = ac_ref.get().strip()
            logger.debug("on_change(%s): txt=%s cur_val=%s", field_name, txt, cur_val)
            rr["ac_selected"] = ac_ref.get_selected()
            if not txt or txt in {"{empty}", "{blank}"}:
                logger.debug("on_change(%s): empty/blank, reverting to current", field_name)
                rr["result_var"].set(cur_val)
            else:
                logger.debug("on_change(%s): setting result to txt=%s", field_name, txt)
                rr["result_var"].set(txt)
            recompute_all_results()
        return on_change

    # ===== Body rows =====
    for i, key in enumerate(FIELD_ORDER):
        # Current value for this field; None becomes "" for safe comparisons.
        cur = "" if current_map.get(key) is None else str(current_map.get(key, ""))

        # Alternate row background for readability.
        row_bg = ROW_BG_1 if (i % 2 == 0) else ROW_BG_2
        # Background frame spans all 5 columns so the stripe fills the full row.
        _bg = tk.Frame(grid_inner, bg=row_bg, height=1)
        _bg.grid(row=i + 1, column=0, columnspan=5, sticky="nsew")

        # Col 0: field name label; explicit fg prevents dark-mode bleed.
        field_lbl = tk.Label(grid_inner, text=key, bg=row_bg, fg=ROW_FG)
        field_lbl.grid(row=i + 1, column=0, sticky="w", padx=6, pady=3)

        # Col 2: Reset checkbox — toggling triggers a full recompute.
        reset_var = tk.BooleanVar(value=False)
        reset_var.trace_add("write", lambda *_: recompute_all_results())
        # selectcolor matches row_bg so the checkbox indicator blends into the stripe.
        reset_cb = tk.Checkbutton(grid_inner, variable=reset_var, bg=row_bg, activebackground=row_bg,
                       fg=ROW_FG, selectcolor=row_bg,
                       highlightthickness=0, bd=0)
        reset_cb.grid(row=i + 1, column=2, sticky="w", padx=6, pady=3)

        # Col 3: Current value (read-only label; updated when asset changes).
        curr_lbl = tk.Label(grid_inner, text=cur, anchor="w", justify="left", bg=row_bg, fg=ROW_FG)
        curr_lbl.grid(row=i + 1, column=3, sticky="nsew", padx=6, pady=3)

        # Col 4: Result label — shows the template-expanded final value.
        result_var = tk.StringVar(value=cur)
        res_lbl = tk.Label(grid_inner, textvariable=result_var, anchor="w", justify="left", bg=row_bg, fg=ROW_FG)
        res_lbl.grid(row=i + 1, column=4, sticky="nsew", padx=6, pady=3)

        # Capture the result-label's default foreground so highlighting can restore it.
        fg_default = _safe_get_fg(res_lbl, ROW_FG)

        row_record = {
            "key": key,
            "reset_var": reset_var,
            "reset_cb": reset_cb,
            "current": cur,
            "field_lbl": field_lbl,
            "curr_lbl": curr_lbl,
            "result_var": result_var,
            "res_lbl": res_lbl,
            "res_lbl_fg_default": fg_default,
        }

        # UPDATES column (col=1)
        if key == "status":
            ac = AutoCompleteEntry(grid_inner)
            ac.grid(row=i + 1, column=1, sticky="nsew", padx=6, pady=3)
            ac.set_options(status_options)

            ac_fg_default = _safe_get_fg(ac.entry, ENTRY_FG)

            ac.bind_change(_make_simple_ac_on_change(ac, cur, row_record, "status"))
            row_record.update({"text_widget_type": "ac", "ac": ac, "ac_fg_default": ac_fg_default})

        elif key == "assigned_to":
            ac = AutoCompleteEntry(grid_inner)
            ac.grid(row=i + 1, column=1, sticky="nsew", padx=6, pady=3)
            ac.set_options(assignee_options)

            ac_fg_default = _safe_get_fg(ac.entry, ENTRY_FG)

            def on_change(ac_ref=ac, cur_val=cur, rr=row_record):
                """Update result value and runtime username on assignee change."""
                txt = ac_ref.get().strip()
                sel = ac_ref.get_selected()
                logger.debug("on_change(assigned_to): txt=%s sel_type=%s", txt, (sel or {}).get("type"))
                rr["ac_selected"] = sel

                if txt == "{empty}":
                    logger.debug("on_change(assigned_to): explicit unassign, clearing username")
                    runtime_username.set("")
                    rr["result_var"].set("")
                elif txt == "{blank}" or not txt:
                    logger.debug("on_change(assigned_to): blank/empty, reverting to current")
                    runtime_username.set(current_map.get("_assigned_username", ""))
                    rr["result_var"].set(cur_val)
                else:
                    live_user = _username_from_option(sel)
                    logger.debug("on_change(assigned_to): setting user txt=%s live_user=%s", txt, live_user)
                    runtime_username.set(live_user or current_map.get("_assigned_username", ""))
                    rr["result_var"].set(txt if txt else cur_val)

                recompute_all_results()

            ac.bind_change(on_change)
            row_record.update({"text_widget_type": "ac", "ac": ac, "ac_fg_default": ac_fg_default})

        elif key == "model":
            ac = AutoCompleteEntry(grid_inner)
            ac.grid(row=i + 1, column=1, sticky="nsew", padx=6, pady=3)
            ac.set_options(model_options)

            ac_fg_default = _safe_get_fg(ac.entry, ENTRY_FG)

            ac.bind_change(_make_simple_ac_on_change(ac, cur, row_record, "model"))
            row_record.update({"text_widget_type": "ac", "ac": ac, "ac_fg_default": ac_fg_default})

        else:
            text = tk.Text(grid_inner, height=1, width=1, wrap="word", font=default_font, bg=ENTRY_BG, fg=ENTRY_FG)
            text.grid(row=i + 1, column=1, sticky="nsew", padx=6, pady=3)
            if key in PLACEHOLDERS:
                attach_placeholder(text, PLACEHOLDERS[key])

            def handler(_e=None, t=text):
                """Resize the text widget and recompute results."""
                logger.debug("handler(text): key event on text widget")
                try:
                    dl = int(t.count("1.0", "end-1c", "displaylines")[0])
                except Exception:
                    dl = 1
                logger.debug("handler(text): displaylines=%s", dl)
                t.configure(height=max(1, min(2, dl)))
                recompute_all_results()

            text.bind("<KeyRelease>", handler, add="+")
            text.bind("<FocusOut>",   handler, add="+")
            text.bind("<Configure>",  handler, add="+")

            row_record.update({"text_widget_type": "text", "text": text})

        rows_by_key[key] = row_record

    # Fields whose Updates widget is disabled (e.g. custom fields absent on this asset model).
    _disabled_rows: set = set()

    # -------------------------------------------------------------------------
    # Templates (load & normalize)
    # -------------------------------------------------------------------------
    def _load_templates(path=TEMPLATES_PATH):
        """Load default profiles from JSON and normalize field keys."""
        logger.debug("_load_templates: loading from path=%s", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug("_load_templates: file loaded, type=%s", type(data).__name__)
            if not isinstance(data, list):
                logger.debug("_load_templates: data is not a list, returning empty")
                return []
            rules = []
            for idx, r in enumerate(data):
                nm = r.get("name") or r.get("profile_name") or f"rule_{idx + 1}"
                raw_defaults = dict(r.get("defaults") or {})
                norm_defaults = {}
                for k, v in raw_defaults.items():
                    nk = _norm_field_key(k)
                    if nk in KNOWN_FIELDS:
                        norm_defaults[nk] = v
                rules.append(
                    {
                        "name": nm,
                        "priority": int(r.get("priority", 0)),
                        "conditions": dict(r.get("conditions") or {}),
                        "defaults": norm_defaults,
                        "_idx": idx,
                    }
                )
            rules.sort(key=lambda rr: (-rr["priority"], rr["_idx"]))
            logger.info("_load_templates: loaded %s template rules from %s", len(rules), path)
            return rules
        except Exception:
            logger.exception("_load_templates: failed to load templates from %s", path)
            return []

    template_rules = _load_templates()

    # -------------------------------------------------------------------------
    # Evaluation helpers
    # -------------------------------------------------------------------------
    def evaluate_template_string(template: str, current_key: str, visited: set):
        """Expand a template string into a computed value.

        Args:
            template: Raw template string possibly containing tokens like {today}.
            current_key: The field key being evaluated (used to avoid self-reference).
            visited: Set of field keys already being evaluated (cycle guard).

        Returns:
            Tuple of (expanded_string, is_blank) where is_blank is True for {blank}.
        """
        logger.debug("evaluate_template_string: template=%s current_key=%s", template, current_key)
        if "{blank}" in template:
            logger.debug("evaluate_template_string: template contains {blank}, returning blank sentinel")
            return "", True
        if "{empty}" in template:
            logger.debug("evaluate_template_string: template contains {empty}, returning empty string")
            return "", False

        def repl(match):
            """Replace a single token within the template string."""
            token = match.group(1).strip()
            logger.debug("repl: token=%s", token)

            if token == "today":
                val = datetime.now().strftime("%Y-%m-%d")
                logger.debug("repl: today=%s", val)
                return val
            if token == "tomorrow":
                val = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                logger.debug("repl: tomorrow=%s", val)
                return val
            if token == "username":
                val = runtime_username.get() or current_map.get("_assigned_username", "")
                logger.debug("repl: username=%s", val)
                return val
            if token.endswith("_current"):
                base = token[:-8]
                if base in FIELD_ORDER:
                    val = current_map.get(base, "")
                    logger.debug("repl: %s_current=%s", base, val)
                    return val
                return ""
            if token in FIELD_ORDER:
                if token in visited:
                    logger.debug("repl: circular ref to token=%s, using current value", token)
                    return current_map.get(token, "")
                logger.debug("repl: recursing to evaluate field token=%s", token)
                return evaluate_row(token, visited=set(visited))
            # dotted path into original assetData
            logger.debug("repl: trying dotted path for token=%s", token)
            parts = token.split(".")
            cur = assetData
            for p in parts:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    logger.debug("repl: dotted path not found for token=%s, returning raw", token)
                    return match.group(0)
            try:
                return str(cur if cur is not None else "")
            except Exception:
                logger.debug("repl: could not stringify dotted path result for token=%s", token)
                return match.group(0)

        expanded = TOKEN_RE.sub(repl, template)
        logger.debug("evaluate_template_string: expanded=%s", expanded)
        return expanded, False

    def evaluate_row(key: str, visited=None):
        """Compute the effective value for a field row.

        Args:
            key: Field key to evaluate.
            visited: Set of field keys already being evaluated (cycle guard).

        Returns:
            The evaluated string value for the field.
        """
        logger.debug("evaluate_row: key=%s visited=%s", key, visited)
        if visited is None:
            visited = set()
        if key in visited:
            logger.debug("evaluate_row: circular reference for key=%s, returning current", key)
            return current_map.get(key, "")
        visited.add(key)

        row = rows_by_key.get(key)
        if row is None:
            logger.debug("evaluate_row: no row found for key=%s", key)
            return current_map.get(key, "")

        if key in {"status", "assigned_to", "model"}:
            logger.debug("evaluate_row: autocomplete field key=%s", key)
            if row.get("text_widget_type") == "ac":
                val = row["ac"].get().strip()
                logger.debug("evaluate_row: ac val=%s", val)

                if val == "{blank}":
                    logger.debug("evaluate_row: blank sentinel, returning current")
                    return current_map.get(key, "")

                if key == "assigned_to" and val == "{empty}":
                    logger.debug("evaluate_row: assigned_to explicit clear")
                    return ""  # explicit clear

                if key in {"model", "status"} and (not val or val == "{empty}"):
                    logger.debug("evaluate_row: non-clearable field empty, returning current")
                    return current_map.get(key, "")

                return val if val else current_map.get(key, "")
            return current_map.get(key, "")

        if row.get("text_widget_type") == "text":
            logger.debug("evaluate_row: text field key=%s", key)
            if is_effective_empty(row["text"]):
                logger.debug("evaluate_row: widget is empty, returning current")
                return current_map.get(key, "")
            raw = _widget_get_text(row["text"])
            logger.debug("evaluate_row: raw text=%s", raw)
            text, is_blank = evaluate_template_string(raw, key, visited)
            if is_blank:
                logger.debug("evaluate_row: template is blank, returning current")
                return current_map.get(key, "")
            return text

        logger.debug("evaluate_row: fallback to current for key=%s", key)
        return current_map.get(key, "")

    def _asset_path_value(path: str):
        """Resolve a dotted path against the raw asset JSON.

        Args:
            path: Dot-separated path string (e.g., 'status_label.name').

        Returns:
            String value at the path, or empty string if missing.
        """
        logger.debug("_asset_path_value: path=%s", path)
        cur = assetData
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                logger.debug("_asset_path_value: path resolution failed at part=%s", part)
                return ""
        if isinstance(cur, dict) or cur is None:
            logger.debug("_asset_path_value: path=%s resolved to dict or None", path)
            return ""
        logger.debug("_asset_path_value: path=%s value=%s", path, cur)
        return str(cur)

    # -------------------------------------------------------------------------
    # Defaults computation & highlighting
    # -------------------------------------------------------------------------
    active_defaults_templ: dict[str, str] = {}
    active_defaults_eval: dict[str, str] = {}
    _applying_maintained_defaults = False

    def recompute_defaults(result_snapshot: dict):
        """Compute active defaults based on template rules.

        Args:
            result_snapshot: Dict of current evaluated field values.
        """
        logger.debug("recompute_defaults: evaluating %s rules against snapshot", len(template_rules))
        active_defaults_templ.clear()
        active_defaults_eval.clear()

        for rule in template_rules:
            ok = True
            logger.debug("recompute_defaults: checking rule=%s", rule.get("name"))
            for lhs, expected in (rule["conditions"] or {}).items():
                lhs_val = (result_snapshot.get(lhs, "") if lhs in FIELD_ORDER else _asset_path_value(lhs))
                exp_raw = str(expected).strip()
                logger.debug("recompute_defaults: condition lhs=%s lhs_val=%s exp_raw=%s", lhs, lhs_val, exp_raw)

                if exp_raw == "{has_value}":
                    if not str(lhs_val).strip():
                        logger.debug("recompute_defaults: {has_value} condition failed for lhs=%s", lhs)
                        ok = False
                        break
                    continue

                rhs, _ = evaluate_template_string(exp_raw, lhs, visited=set())
                if str(lhs_val) != str(rhs):
                    logger.debug("recompute_defaults: condition mismatch lhs_val=%s rhs=%s", lhs_val, rhs)
                    ok = False
                    break

            if not ok:
                logger.debug("recompute_defaults: rule=%s did not match, skipping", rule.get("name"))
                continue

            logger.debug("recompute_defaults: rule=%s matched, applying defaults", rule.get("name"))
            for f, templ in (rule["defaults"] or {}).items():
                if f not in FIELD_ORDER or f in active_defaults_templ:
                    continue

                raw_t = str(templ).strip()
                if raw_t == "{has_value}":
                    logger.debug("recompute_defaults: field=%s has_value sentinel", f)
                    active_defaults_templ[f] = raw_t
                    active_defaults_eval[f] = HAS_VALUE_SENTINEL
                    continue

                eval_t, is_blank = evaluate_template_string(raw_t, f, visited=set())
                if is_blank:
                    logger.debug("recompute_defaults: field=%s template is blank, skipping", f)
                    continue

                logger.debug("recompute_defaults: field=%s default=%s", f, eval_t)
                active_defaults_templ[f] = raw_t
                active_defaults_eval[f] = eval_t

    def _apply_maintained_defaults() -> bool:
        """Apply maintained defaults to rows and return True if changed.

        Returns:
            True if any widget value was changed.
        """
        logger.debug("_apply_maintained_defaults: checking rows for maintained defaults")
        changed = False
        for key, r in rows_by_key.items():
            if not r["reset_var"].get():
                continue

            raw_default = (active_defaults_templ.get(key, "") or "").strip()
            eval_default = active_defaults_eval.get(key, None)
            logger.debug("_apply_maintained_defaults: key=%s raw_default=%s eval_default=%s", key, raw_default, eval_default)

            if r.get("text_widget_type") == "ac":
                ac = r["ac"]
                if eval_default and eval_default != HAS_VALUE_SENTINEL:
                    desired = eval_default
                elif raw_default == "{empty}" and key == "assigned_to":
                    desired = "{empty}"
                else:
                    continue

                cur_text = ac.get().strip()
                logger.debug("_apply_maintained_defaults: ac key=%s cur_text=%s desired=%s", key, cur_text, desired)
                if cur_text != desired:
                    if hasattr(ac, "set_selected_by_label") and desired != "{empty}":
                        ac.set_selected_by_label(desired)
                    else:
                        ac.set(desired)
                    r["ac_selected"] = ac.get_selected()
                    r["result_var"].set("" if (key == "assigned_to" and desired == "{empty}") else desired)
                    logger.debug("_apply_maintained_defaults: updated ac key=%s to desired=%s", key, desired)
                    changed = True

            else:
                if key in _disabled_rows:
                    continue
                if not raw_default or raw_default == "{has_value}":
                    continue
                cur_text = _widget_get_text(r["text"])
                logger.debug("_apply_maintained_defaults: text key=%s cur_text=%s raw_default=%s", key, cur_text, raw_default)
                if cur_text != raw_default:
                    _widget_set_text(r["text"], raw_default)
                    logger.debug("_apply_maintained_defaults: updated text key=%s to default=%s", key, raw_default)
                    try:
                        r["text"].config(bg=ENTRY_BG)
                    except Exception:
                        pass
                    changed = True

        logger.debug("_apply_maintained_defaults: changed=%s", changed)
        return changed

    def recompute_all_results():
        """Re-evaluate all rows, refresh active defaults, and apply mismatch highlighting.

        This is the central "refresh" call — it should be invoked any time a
        widget value changes, a reset happens, or the asset switches.  It:
          1. Evaluates every field's template to produce a result snapshot.
          2. Recomputes which default-profile rules apply given the snapshot.
          3. Optionally pushes those defaults into checked rows (maintain mode).
          4. Highlights Result labels and Updates widgets red where values differ
             from their active defaults.
        """
        logger.debug("recompute_all_results: starting full recompute")
        nonlocal _applying_maintained_defaults

        snapshot = {}
        for k in FIELD_ORDER:
            snapshot[k] = evaluate_row(k, visited=set())
            rows_by_key[k]["result_var"].set(snapshot[k])
        logger.debug("recompute_all_results: snapshot computed, running defaults")

        recompute_defaults(snapshot)

        if maintain_defaults_var.get() and not _applying_maintained_defaults:
            logger.debug("recompute_all_results: maintain_defaults is on, applying maintained defaults")
            if _apply_maintained_defaults():
                _applying_maintained_defaults = True
                logger.debug("recompute_all_results: defaults changed, re-evaluating snapshot")
                try:
                    snapshot = {}
                    for k in FIELD_ORDER:
                        snapshot[k] = evaluate_row(k, visited=set())
                        rows_by_key[k]["result_var"].set(snapshot[k])
                    recompute_defaults(snapshot)
                finally:
                    _applying_maintained_defaults = False

        mismatch_count = 0
        for k in FIELD_ORDER:
            if k in _disabled_rows:
                continue  # greyed-out rows don't participate in mismatch highlighting
            row = rows_by_key[k]
            res_lbl = row["res_lbl"]
            default_fg = row["res_lbl_fg_default"]
            dval = active_defaults_eval.get(k, None)

            mismatch = False
            if dval is not None:
                if dval == HAS_VALUE_SENTINEL:
                    mismatch = (str(snapshot.get(k, "")).strip() == "")
                else:
                    mismatch = (str(snapshot.get(k, "")) != str(dval))

            if mismatch:
                mismatch_count += 1
                logger.debug("recompute_all_results: mismatch on field=%s snapshot=%s expected=%s", k, snapshot.get(k), dval)

            # Apply or clear error highlight using theme-appropriate colours.
            res_lbl.configure(foreground=ERROR_FG if mismatch else default_fg)

            if row.get("text_widget_type") == "text":
                try:
                    row["text"].configure(bg=ERROR_BG if mismatch else ENTRY_BG)
                except Exception:
                    pass
            elif row.get("text_widget_type") == "ac":
                entry = row["ac"].entry
                try:
                    entry.configure(style="ConsistError.TEntry" if mismatch else "")
                except Exception:
                    try:
                        entry.configure(
                            foreground=ERROR_FG if mismatch else row.get("ac_fg_default", ENTRY_FG)
                        )
                    except Exception:
                        pass
        logger.debug("recompute_all_results: complete, mismatch_count=%s", mismatch_count)

    maintain_defaults_var.trace_add("write", lambda *_: recompute_all_results())

    # -------------------------------------------------------------------------
    # Reset Selected
    # -------------------------------------------------------------------------
    def reset_selected():
        """Reset checked rows to defaults and recompute results."""
        logger.debug("reset_selected: resetting checked rows to defaults")
        results_snapshot = {k: evaluate_row(k, visited=set()) for k in FIELD_ORDER}
        recompute_defaults(results_snapshot)

        reset_count = 0
        for r in rows_by_key.values():
            if not r["reset_var"].get():
                continue

            key = r["key"]
            if key in _disabled_rows:
                continue
            raw_default = (active_defaults_templ.get(key, None) or "").strip()
            eval_default = active_defaults_eval.get(key, None)
            logger.debug("reset_selected: resetting key=%s raw_default=%s eval_default=%s", key, raw_default, eval_default)

            if r.get("text_widget_type") == "ac":
                ac = r["ac"]
                if eval_default and eval_default != HAS_VALUE_SENTINEL:
                    logger.debug("reset_selected: setting ac key=%s to eval_default=%s", key, eval_default)
                    if hasattr(ac, "set_selected_by_label"):
                        ac.set_selected_by_label(eval_default)
                    else:
                        ac.set(eval_default)
                    r["ac_selected"] = ac.get_selected()
                    r["result_var"].set(eval_default)
                elif raw_default == "{empty}" and key == "assigned_to":
                    logger.debug("reset_selected: setting assigned_to to {empty}")
                    ac.set("{empty}")
                    r["ac_selected"] = None
                    r["result_var"].set("")
                else:
                    logger.debug("reset_selected: clearing ac for key=%s", key)
                    ac.set("")
                    r["ac_selected"] = None
                    r["result_var"].set(r["current"])
            else:
                t = r["text"]
                if raw_default and raw_default != "{has_value}":
                    logger.debug("reset_selected: setting text key=%s to raw_default=%s", key, raw_default)
                    _widget_set_text(t, raw_default)
                else:
                    logger.debug("reset_selected: clearing text key=%s", key)
                    _widget_set_text(t, "")
                    if key in PLACEHOLDERS:
                        attach_placeholder(t, PLACEHOLDERS[key])
                try:
                    t.config(bg=ENTRY_BG)
                except Exception:
                    pass

            r["reset_var"].set(False)
            reset_count += 1

        logger.debug("reset_selected: reset %s rows, recomputing", reset_count)
        recompute_all_results()

    reset_selected_btn.configure(command=reset_selected)

    # -------------------------------------------------------------------------
    # Snipe-IT helpers (ID mapping + PATCH/CHECKIN with retry)
    # -------------------------------------------------------------------------
    def _label_id_map(options):
        """Build a label-to-ID map from autocomplete options.

        Args:
            options: List of autocomplete option dicts.

        Returns:
            Dict mapping label strings to IDs.
        """
        logger.debug("_label_id_map: building map from %s options", len(options) if options else 0)
        m = {}
        for opt in (options or []):
            label = opt.get("label") or opt.get("name") or opt.get("text") or str(opt.get("value") or opt.get("id") or "")
            label = str(label).strip()
            _id = opt.get("id") or opt.get("value") or (opt.get("meta") or {}).get("id")
            if label and _id is not None:
                m[label] = _id
        logger.debug("_label_id_map: map has %s entries", len(m))
        return m

    def _id_from_sel(sel):
        """Extract a selection ID from an autocomplete selection dict.

        Args:
            sel: Autocomplete selection dict.

        Returns:
            The ID value, or None if not found.
        """
        logger.debug("_id_from_sel: sel_type=%s", type(sel).__name__)
        if not isinstance(sel, dict):
            logger.debug("_id_from_sel: not a dict, returning None")
            return None
        for k in ("id", "value", "user_id", "model_id", "status_id"):
            if sel.get(k) is not None:
                logger.debug("_id_from_sel: found id via key=%s value=%s", k, sel[k])
                return sel[k]
        meta = sel.get("meta") or {}
        for k in ("id", "user_id", "model_id", "status_id"):
            if meta.get(k) is not None:
                logger.debug("_id_from_sel: found id in meta via key=%s value=%s", k, meta[k])
                return meta[k]
        logger.debug("_id_from_sel: no id found, returning None")
        return None

    # Pre-build reverse-lookup maps so we can resolve label strings to IDs
    # without scanning the full options lists on every submission.
    status_label_to_id = _label_id_map(status_options)
    model_label_to_id = _label_id_map(model_options)
    assignee_label_to_id = _label_id_map(assignee_options)

    def _build_patch_payload(snapshot: dict):
        """Compare snapshot vs current, return (payload, any_changes, need_checkin).

        Maps UI keys -> Snipe-IT API keys and coerces types.

        Clearing rules (all via {empty}):
          - Text fields (name, serial, order_number, notes): "" (empty string)
          - Date fields (purchase_date, expected_checkin):  "" (empty string)
          - Numeric (purchase_cost):                       "" (empty string)
          - Unassign user:                                 handled via CHECKIN (need_checkin=True)

        Args:
            snapshot: Dict of current evaluated field values.

        Returns:
            Tuple of (payload, any_changes, need_checkin, must_checkin_first,
            checkout_user_id, checkout_location_id).
        """
        logger.debug("_build_patch_payload: building patch payload from snapshot")
        payload = {}
        changed = False
        need_checkin = False
        checkout_user_id = None
        checkout_location_id = None
        must_checkin_first = False

        current_assignee_type = ((assetData.get("assigned_to") or {}).get("type") or "").strip().lower()
        logger.debug("_build_patch_payload: current_assignee_type=%s", current_assignee_type)

        for key in FIELD_ORDER:
            new = snapshot.get(key, "")
            old = rows_by_key[key]["current"]
            if str(new) == str(old):
                continue
            logger.debug("_build_patch_payload: field=%s changed old=%s new=%s", key, old, new)
            changed = True

            if key == "assigned_to":
                txt = (new or "").strip()
                sel = rows_by_key[key].get("ac_selected")
                sel_type = ((sel or {}).get("type") or "").strip().lower()
                logger.debug("_build_patch_payload: assigned_to txt=%s sel_type=%s", txt, sel_type)

                if txt in ("", "{empty}"):
                    # explicit clear
                    logger.info("_build_patch_payload: assigned_to cleared, marking need_checkin")
                    need_checkin = True

                elif sel_type == "user":
                    checkout_user_id = _id_from_sel(sel)
                    logger.info("_build_patch_payload: checkout to user_id=%s", checkout_user_id)
                    if checkout_user_id is None:
                        raise ValueError("Pick a *User* from the list (or type {empty} to clear).")
                    # if changing from location->user (or user->location below), require checkin first
                    if current_assignee_type and current_assignee_type != "user":
                        logger.debug("_build_patch_payload: assignee type change, must_checkin_first=True")
                        must_checkin_first = True

                elif sel_type == "location":
                    checkout_location_id = _id_from_sel(sel)
                    logger.info("_build_patch_payload: checkout to location_id=%s", checkout_location_id)
                    if checkout_location_id is None:
                        raise ValueError("Pick a *Location* from the list.")
                    # make default/home location match too (optional)
                    payload["location_id"] = checkout_location_id
                    if current_assignee_type and current_assignee_type != "location":
                        logger.debug("_build_patch_payload: assignee type change, must_checkin_first=True")
                        must_checkin_first = True

                else:
                    raise ValueError("Select either a User or a Location from suggestions.")
                continue

            if key in {"status", "model"}:
                txt = (new or "").strip()
                sel = rows_by_key[key].get("ac_selected")
                sel_id = _id_from_sel(sel)
                if sel_id is None:
                    label_map = status_label_to_id if key == "status" else model_label_to_id
                    sel_id = label_map.get(txt)
                logger.debug("_build_patch_payload: key=%s txt=%s sel_id=%s", key, txt, sel_id)
                if sel_id is None:
                    raise ValueError(f"Pick a {key.replace('_', ' ').title()} from the list.")
                payload_key = "status_id" if key == "status" else "model_id"
                payload[payload_key] = sel_id
                continue

            elif key == "box_number":
                # Custom field — use the same configured field key as the drop-off workflow.
                # Snipe-IT API responses don't expose the db column name, so we read it from
                # settings (dropOffBoxFieldKey) with the same hardcoded fallback dropOff uses.
                _box_db_col = (get_settings().get("dropOffBoxFieldKey", "") or "").strip() or "_snipeit_box_number_5"
                logger.debug("_build_patch_payload: box_number db_col=%s value=%s", _box_db_col, new)
                payload[_box_db_col] = new

            else:
                # Any future fields default to pass-through
                logger.debug("_build_patch_payload: passthrough field=%s value=%s", key, new)
                payload[key] = new

        logger.debug("_build_patch_payload: changed=%s need_checkin=%s must_checkin_first=%s payload_keys=%s",
                     changed, need_checkin, must_checkin_first, list(payload.keys()))
        return payload, changed, need_checkin, must_checkin_first, checkout_user_id, checkout_location_id

    def _require_snipe_config(op_name: str) -> bool:
        """Return True if SNIPE_BASE/API key are configured; else show an error.

        Shared guard for the PATCH/checkin/checkout helpers below.
        """
        if not SNIPE_BASE or not get_api_key():
            logger.error("%s: missing SNIPE_BASE or API key", op_name)
            messagebox.showerror("Snipe-IT", "Missing API_URL_Base or API key in utilities.Key.")
            return False
        return True

    def _snipe_call_with_retry(op_name: str, request_fn) -> bool:
        """Run a Snipe-IT write request through call_with_retry; True on success."""
        result = call_with_retry(op_name, request_fn, busy_widget=win)
        return result is not None

    def _api_patch_with_retry(asset_id: int, payload: dict) -> bool:
        """PATCH the asset and prompt the user to retry on failures.

        Args:
            asset_id: Numeric Snipe-IT asset ID.
            payload: Dict of field updates to send.

        Returns:
            True if the PATCH succeeded, False if cancelled.
        """
        logger.debug("_api_patch_with_retry: asset_id=%s payload_keys=%s", asset_id, list(payload.keys()))
        if not _require_snipe_config("_api_patch_with_retry"):
            return False

        url = f"{SNIPE_BASE}/hardware/{asset_id}"
        headers = get_api_headers()
        logger.info("_api_patch_with_retry: PATCH url=%s", url)

        return _snipe_call_with_retry(
            f"Update asset {asset_id}",
            lambda: requests.patch(url, json=payload, headers=headers, timeout=25),
        )

    def _api_checkin_with_retry(asset_id: int, note: str = "Consisterizer unassign", location_id: int | None = None) -> bool:
        """POST /hardware/{id}/checkin to unassign the asset.

        Args:
            asset_id: Numeric Snipe-IT asset ID.
            note: Note to include with the checkin.
            location_id: Optional location ID for the checkin.

        Returns:
            True if checkin succeeded, False if cancelled.
        """
        logger.debug("_api_checkin_with_retry: asset_id=%s note=%s location_id=%s", asset_id, note, location_id)
        if not _require_snipe_config("_api_checkin_with_retry"):
            return False

        url = f"{SNIPE_BASE}/hardware/{asset_id}/checkin"
        headers = get_api_headers()
        body = {"note": note}
        if location_id is not None:
            body["location_id"] = location_id
        logger.info("_api_checkin_with_retry: POST checkin url=%s", url)

        return _snipe_call_with_retry(
            f"Check in asset {asset_id}",
            lambda: requests.post(url, json=body, headers=headers, timeout=25),
        )

    def _api_checkout_with_retry(asset_id: int, *, user_id: int | None = None,
                                 location_id: int | None = None,
                                 note: str = "Consisterizer assign/checkout",
                                 expected_checkin: str | None = None) -> bool:
        """POST a checkout and prompt for retries on failure.

        Args:
            asset_id: Numeric Snipe-IT asset ID.
            user_id: User ID to check out to (exclusive with location_id).
            location_id: Location ID to check out to (exclusive with user_id).
            note: Note to include with the checkout.
            expected_checkin: Optional expected checkin date string YYYY-MM-DD.

        Returns:
            True if checkout succeeded, False if cancelled.
        """
        logger.debug("_api_checkout_with_retry: asset_id=%s user_id=%s location_id=%s", asset_id, user_id, location_id)
        if not _require_snipe_config("_api_checkout_with_retry"):
            return False

        url = f"{SNIPE_BASE}/hardware/{asset_id}/checkout"
        headers = get_api_headers()

        body = {"note": note}
        if user_id is not None:
            logger.debug("_api_checkout_with_retry: checkout to user_id=%s", user_id)
            body.update({"checkout_to_type": "user", "assigned_user": user_id})
        elif location_id is not None:
            logger.debug("_api_checkout_with_retry: checkout to location_id=%s", location_id)
            body.update({"checkout_to_type": "location", "assigned_location": location_id})
        else:
            logger.error("_api_checkout_with_retry: neither user_id nor location_id provided")
            messagebox.showerror("Snipe-IT", "Checkout requires user_id or location_id.")
            return False

        if expected_checkin:
            body["expected_checkin"] = expected_checkin  # "YYYY-MM-DD"
            logger.debug("_api_checkout_with_retry: expected_checkin=%s", expected_checkin)

        logger.info("_api_checkout_with_retry: POST checkout url=%s", url)

        return _snipe_call_with_retry(
            f"Check out asset {asset_id}",
            lambda: requests.post(url, json=body, headers=headers, timeout=25),
        )

    # -------------------------------------------------------------------------
    # Footer (scripts + status line)
    # -------------------------------------------------------------------------
    footer = ttk.Frame(win)
    footer.pack(fill="x", padx=12, pady=(0, 12))
    footer.grid_columnconfigure(0, weight=1)
    footer.grid_columnconfigure(1, weight=0)  # center column
    footer.grid_columnconfigure(2, weight=1)

    scripts_box = ttk.LabelFrame(footer, text="On Submit: run scripts")
    scripts_box.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
    scripts_box.grid_columnconfigure(0, weight=1)
    scripts_box.grid_columnconfigure(1, weight=1)
    scripts_box.grid_columnconfigure(2, weight=1)

    script_vars = []
    max_cols = 3
    for i, lbl in enumerate(submit_func_listTXT):
        var = tk.BooleanVar(value=False)
        script_vars.append(var)
        r, c = divmod(i, max_cols)
        ttk.Checkbutton(scripts_box, text=lbl, variable=var).grid(row=r, column=c, sticky="w", padx=6, pady=3)

    # Quiet success line
    status_var = tk.StringVar(value="")
    status_lbl = ttk.Label(footer, textvariable=status_var)
    status_lbl.grid(row=1, column=0, sticky="w", padx=6)

    # Submit/Clear buttons stub; real commands attached later after function defs
    center_btns = ttk.Frame(footer)
    center_btns.grid(row=1, column=1, padx=8)  # centered
    clear_btn = ttk.Button(center_btns, text="Clear")
    clear_btn.pack(side="left", padx=(0, 6))
    submit_btn = ttk.Button(center_btns, text="Submit & Save")
    submit_btn.pack(side="left")
    ttk.Button(footer, text="Close", command=win.destroy).grid(row=1, column=2, sticky="e")

    # --- Alias support -------------------------------------------------------
    def _to_alias_obj(a):
        """Accept dict or JSON string; return dict or {}.

        Args:
            a: Dict, JSON string, or None.

        Returns:
            Dict representation of the alias, or empty dict.
        """
        logger.debug("_to_alias_obj: input type=%s", type(a).__name__)
        if not a:
            return {}
        if isinstance(a, dict):
            return a
        if isinstance(a, str):
            try:
                result = json.loads(a)
                logger.debug("_to_alias_obj: parsed JSON string successfully")
                return result
            except Exception:
                logger.debug("_to_alias_obj: failed to parse JSON string")
                return {}
        return {}

    def _norm_alias_key(k: str) -> str:
        """Normalize alias keys for lookup."""
        logger.debug("_norm_alias_key: k=%s", k)
        return (k or "").strip().lower().replace(" ", "_")

    # reverse lookups in case alias specifies IDs
    def _label_from_id(label_to_id: dict, wanted_id):
        """Return the label matching a given ID from a lookup map.

        Args:
            label_to_id: Dict mapping label strings to IDs.
            wanted_id: The ID to search for.

        Returns:
            The matching label string, or None.
        """
        logger.debug("_label_from_id: searching for id=%s in map of size=%s", wanted_id, len(label_to_id) if label_to_id else 0)
        for lbl, _id in (label_to_id or {}).items():
            if _id == wanted_id:
                logger.debug("_label_from_id: found label=%s for id=%s", lbl, wanted_id)
                return lbl
        logger.debug("_label_from_id: no label found for id=%s", wanted_id)
        return None

    def _apply_alias(a):
        """Apply an alias payload to prefill fields and set options.

        Alias schema (all optional):
        {
          "title": "Check-in",
          "batch_mode": true/false,
          "maintain_defaults": true/false,
          "set": {
            "<field>": "<value or {empty} or template>",
            "status": "<label or {‘id’: 12} or {‘label’: ‘...’}>",
            "model":  "<label or {‘id’: 34}>",
            "assigned_to": "<label | {empty} | {‘id’: 7}>"
          },
          "reset": true | false | {"field": true/false, ...} | ["field1","field2"],
          "scripts": "all" | [0, 2, "Script Name", ...]
        }

        Args:
            a: Alias dict or JSON string.
        """
        logger.debug("_apply_alias: applying alias")
        a = _to_alias_obj(a)
        if not a:
            logger.debug("_apply_alias: alias is empty, skipping")
            return

        # 2.1 Title suffix
        title_suffix = a.get("title")
        if title_suffix:
            logger.debug("_apply_alias: setting title suffix=%s", title_suffix)
            try:
                win.title(f"{win.title()} • {title_suffix}")
            except Exception:
                pass

        # 2.2 Top-level toggles
        if "batch_mode" in a:
            logger.debug("_apply_alias: setting batch_mode=%s", a["batch_mode"])
            try:
                batch_mode_var.set(bool(a["batch_mode"]))
            except Exception:
                pass

        if "maintain_defaults" in a:
            logger.debug("_apply_alias: setting maintain_defaults=%s", a["maintain_defaults"])
            try:
                maintain_defaults_var.set(bool(a["maintain_defaults"]))
            except Exception:
                pass

        # 2.3 Scripts selection (by index or case-insensitive name)
        scr = a.get("scripts")
        if scr:
            logger.debug("_apply_alias: applying scripts=%s", scr)
            if scr == "all":
                logger.debug("_apply_alias: enabling all scripts")
                for v in script_vars:
                    v.set(True)
            else:
                wanted = set(scr if isinstance(scr, (list, tuple)) else [scr])
                # pre-normalize names
                name_to_idx = {s.lower(): i for i, s in enumerate(submit_func_listTXT)}
                for item in wanted:
                    if isinstance(item, int) and 0 <= item < len(script_vars):
                        logger.debug("_apply_alias: enabling script index=%s", item)
                        script_vars[item].set(True)
                    elif isinstance(item, str):
                        idx = name_to_idx.get(item.lower())
                        if idx is not None:
                            logger.debug("_apply_alias: enabling script name=%s index=%s", item, idx)
                            script_vars[idx].set(True)

        # 2.4 Reset checkboxes
        rst = a.get("reset")
        logger.debug("_apply_alias: applying reset=%s type=%s", rst, type(rst).__name__)
        if isinstance(rst, bool):
            for r in rows_by_key.values():
                r["reset_var"].set(rst)
        elif isinstance(rst, dict):
            for k, flag in rst.items():
                nk = _norm_alias_key(k)
                if nk in rows_by_key:
                    logger.debug("_apply_alias: setting reset key=%s flag=%s", nk, flag)
                    rows_by_key[nk]["reset_var"].set(bool(flag))
        elif isinstance(rst, (list, tuple)):
            want = { _norm_alias_key(x) for x in rst }
            logger.debug("_apply_alias: reset fields=%s", want)
            for k, r in rows_by_key.items():
                r["reset_var"].set(k in want)

        # 2.5 Pre-fill Updates column
        preset = a.get("set") or {}
        logger.debug("_apply_alias: prefilling %s fields", len(preset))
        if isinstance(preset, dict):
            for k, v in preset.items():
                fk = _norm_alias_key(k)
                if fk not in rows_by_key:
                    logger.debug("_apply_alias: unknown field key=%s, skipping", fk)
                    continue
                row = rows_by_key[fk]
                logger.debug("_apply_alias: setting field=%s value=%s", fk, v)

                # Autocomplete fields
                if fk in {"status", "assigned_to", "model"} and row.get("text_widget_type") == "ac":
                    ac = row["ac"]

                    # Accept dicts like {"id": 5} or {"label": "Ready to Deploy"}
                    if isinstance(v, dict):
                        vid = v.get("id") or v.get("value")
                        vlabel = v.get("label") or v.get("name") or v.get("text")
                        if vid is not None and not vlabel:
                            # map ID -> label via our cached dictionaries
                            if fk == "status":
                                vlabel = _label_from_id(status_label_to_id, vid)
                            elif fk == "model":
                                vlabel = _label_from_id(model_label_to_id, vid)
                            elif fk == "assigned_to":
                                vlabel = _label_from_id(assignee_label_to_id, vid)
                        v = vlabel if vlabel is not None else v  # fall back to raw dict if we must

                    v = "" if v is None else str(v)
                    logger.debug("_apply_alias: ac field=%s resolved_value=%s", fk, v)

                    # For assigned_to we support {empty}
                    if fk == "assigned_to" and v.strip() == "{empty}":
                        logger.debug("_apply_alias: setting assigned_to to {empty}")
                        ac.set("{empty}")
                        row["ac_selected"] = None
                    else:
                        # Prefer exact label selection if supported; otherwise set text
                        if hasattr(ac, "set_selected_by_label"):
                            ac.set_selected_by_label(v)
                            row["ac_selected"] = ac.get_selected()
                        else:
                            ac.set(v)
                            row["ac_selected"] = None  # mapping by label will still work later

                # Text fields
                elif row.get("text_widget_type") == "text":
                    if fk in _disabled_rows:
                        logger.debug("_apply_alias: skipping disabled field=%s", fk)
                        continue
                    txt = "" if v is None else str(v)
                    logger.debug("_apply_alias: setting text field=%s txt=%s", fk, txt)
                    _widget_set_text(row["text"], txt)
                    # ensure placeholder is considered inactive if we’ve typed something
                    try:
                        row["text"].placeholder_active = (txt == "")
                    except Exception:
                        pass

        # Recompute once after all sets
        logger.debug("_apply_alias: recomputing results after alias application")
        try:
            recompute_all_results()
        except Exception:
            pass

    # Apply alias (if any) after all widgets exist, before first compute
    if alias:
        _apply_alias(alias)


    # -------------------------------------------------------------------------
    # Submit helpers (validate, warn, save, scripts, maybe switch)
    # -------------------------------------------------------------------------
    def _collect_snapshot():
        """Collect current evaluated values for all fields.

        Returns:
            Dict mapping field keys to their current evaluated string values.
        """
        logger.debug("_collect_snapshot: collecting snapshot")
        return {k: evaluate_row(k, visited=set()) for k in FIELD_ORDER}

    def _collect_validation_errors(snapshot: dict):
        """Enforce asset_tag/date only on fields that are changing vs current.

        Empty string on DATE_FIELDS is allowed only via {empty} (clear).

        Args:
            snapshot: Dict of current evaluated field values.

        Returns:
            List of error message strings.
        """
        logger.debug("_collect_validation_errors: validating snapshot")
        errors = []
        for key, final_val in snapshot.items():
            if final_val == rows_by_key[key]["current"]:
                continue

            if key == "asset_tag" and not valid_asset_tag(final_val):
                logger.debug("_collect_validation_errors: invalid asset_tag=%s", final_val)
                errors.append(f"[asset_tag] must be 4–5 digits (got '{final_val}')")

            if key in DATE_FIELDS:
                if final_val == "":  # allow clearing dates with {empty}
                    continue
                if not valid_date(final_val):
                    logger.debug("_collect_validation_errors: invalid date key=%s value=%s", key, final_val)
                    errors.append(f"[{key}] must be YYYY-MM-DD (got '{final_val}')")
        logger.debug("_collect_validation_errors: found %s errors", len(errors))
        return errors

    def _collect_default_warnings(snapshot: dict):
        """Return warnings when values differ from active defaults.

        Args:
            snapshot: Dict of current evaluated field values.

        Returns:
            List of warning message strings.
        """
        logger.debug("_collect_default_warnings: checking for default mismatches")
        warnings = []
        for k in FIELD_ORDER:
            if k not in active_defaults_eval:
                continue
            expected = active_defaults_eval[k]
            actual = (snapshot.get(k, "") or "")
            if expected == HAS_VALUE_SENTINEL:
                if str(actual).strip() == "":
                    logger.debug("_collect_default_warnings: has_value mismatch for field=%s", k)
                    warnings.append(f"- {k}: empty, but default requires a value")
            else:
                if str(actual) != str(expected):
                    logger.debug("_collect_default_warnings: value mismatch field=%s actual=%s expected=%s", k, actual, expected)
                    warnings.append(f"- {k}: '{actual}' ≠ default '{expected}'")
        logger.debug("_collect_default_warnings: found %s warnings", len(warnings))
        return warnings

    def _update_box_number_state():
        """Grey out / re-enable the box_number row based on whether the active asset has that custom field."""
        logger.debug("_update_box_number_state: checking assetData for Box Number custom field")
        bn_row = rows_by_key.get("box_number")
        if not bn_row:
            return
        has_field = bool((assetData.get("custom_fields") or {}).get("Box Number"))
        logger.debug("_update_box_number_state: has_field=%s", has_field)

        t = bn_row.get("text")
        if t:
            if has_field:
                _disabled_rows.discard("box_number")
                try:
                    t.configure(state="normal", fg=ENTRY_FG, bg=ENTRY_BG)
                except Exception:
                    pass
            else:
                _disabled_rows.add("box_number")
                try:
                    bn_row["reset_var"].set(False)
                except Exception:
                    pass
                try:
                    t.configure(state="disabled", fg="grey")
                except Exception:
                    pass

        grey = "grey"
        for lbl_key in ("field_lbl", "curr_lbl"):
            lbl = bn_row.get(lbl_key)
            if lbl:
                try:
                    lbl.configure(fg=ROW_FG if has_field else grey)
                except Exception:
                    pass

        res_lbl = bn_row.get("res_lbl")
        if res_lbl:
            try:
                res_lbl.configure(fg=(bn_row.get("res_lbl_fg_default", ROW_FG) if has_field else grey))
            except Exception:
                pass

        cb = bn_row.get("reset_cb")
        if cb:
            try:
                cb.configure(state="normal" if has_field else "disabled")
            except Exception:
                pass

    def _run_selected_submit_scripts(asset_tag_for_scripts: str, checked_values: list | None = None):
        """Run checked submit scripts. Silent on success; dialog on any failures.

        Scripts receive (asset_tag, checked_values) where checked_values is a list
        built from the reset-checked rows (same format the main window passes to
        printSelected). Scripts that only accept asset_tag fall back via TypeError.

        Args:
            asset_tag_for_scripts: Asset tag to pass to each script.
            checked_values: List of selected field values to pass as the second arg.
        """
        logger.debug("_run_selected_submit_scripts: asset_tag=%s checked_values=%s", asset_tag_for_scripts, checked_values)
        had_error = False
        lines = []
        for i, var in enumerate(script_vars):
            if not var.get():
                continue
            logger.info("_run_selected_submit_scripts: running script=%s for asset_tag=%s", submit_func_listTXT[i], asset_tag_for_scripts)
            try:
                ret = submit_func_list[i](asset_tag_for_scripts, checked_values)
            except TypeError:
                # Script doesn't accept a second argument — fall back to tag-only call.
                logger.debug("_run_selected_submit_scripts: script=%s does not accept checked_values, retrying tag-only", submit_func_listTXT[i])
                try:
                    ret = submit_func_list[i](asset_tag_for_scripts)
                except Exception as e:
                    logger.exception("_run_selected_submit_scripts: script=%s failed", submit_func_listTXT[i])
                    had_error = True
                    lines.append(f"✗ {submit_func_listTXT[i]}: {e}")
                    continue
            except Exception as e:
                logger.exception("_run_selected_submit_scripts: script=%s failed", submit_func_listTXT[i])
                had_error = True
                lines.append(f"✗ {submit_func_listTXT[i]}: {e}")
                continue
            logger.debug("_run_selected_submit_scripts: script=%s returned=%s", submit_func_listTXT[i], ret)
            if ret not in (None, ""):
                lines.append(f"✓ {submit_func_listTXT[i]}: {ret}")
        if had_error:
            logger.error("_run_selected_submit_scripts: one or more scripts failed")
            messagebox.showerror("Script Errors", "\n".join(lines))

    def _refresh_current_after_save(saved_snapshot: dict):
        """Reload the current asset after a save completes.

        Args:
            saved_snapshot: The snapshot that was just saved.
        """
        # If asset_tag changed, reload by new tag; otherwise by existing tag
        new_tag = saved_snapshot.get("asset_tag") or current_map.get("asset_tag") or ""
        logger.debug("_refresh_current_after_save: new_tag=%s", new_tag)
        if not new_tag:
            logger.debug("_refresh_current_after_save: no tag available, skipping refresh")
            return
        logger.info("_refresh_current_after_save: reloading asset tag=%s", new_tag)
        _switch_asset_in_place(new_tag)

    def _submit_current_asset(prompt_on_warnings: bool = True) -> tuple[bool, str, dict]:
        """Validate, warn on default mismatches, push to Snipe-IT (PATCH), optionally CHECKIN to unassign, refresh, and update the status line.

        Args:
            prompt_on_warnings: Whether to show a dialog for default mismatches.

        Returns:
            Tuple of (ok, tag_for_scripts, snapshot) where ok is True on success.
        """
        logger.debug("_submit_current_asset: prompt_on_warnings=%s has_current_asset=%s", prompt_on_warnings, has_current_asset.get())
        if not has_current_asset.get():
            logger.debug("_submit_current_asset: no current asset, showing info dialog")
            messagebox.showinfo("Consisterizer", "Enter or scan an asset tag first.")
            return False, "", {}

        status_var.set("")  # clear previous message
        logger.debug("_submit_current_asset: collecting snapshot")
        snapshot = _collect_snapshot()

        # Local validations (only for changed fields)
        errors = _collect_validation_errors(snapshot)
        if errors:
            logger.debug("_submit_current_asset: validation errors=%s", errors)
            messagebox.showerror("Validation Errors", "Please fix the following:\n\n" + "\n".join(errors))
            return False, (current_map.get("asset_tag") or ""), {}

        warnings = _collect_default_warnings(snapshot) if prompt_on_warnings else []
        if warnings:
            logger.debug("_submit_current_asset: default warnings count=%s", len(warnings))
            show = warnings[:10]
            extra = len(warnings) - len(show)
            if extra > 0:
                show.append(f"... and {extra} more.")
            proceed = messagebox.askyesno(
                "Defaults Warning",
                "Some values differ from the current defaults:\n\n" + "\n".join(show) + "\n\nProceed anyway?"
            )
            if not proceed:
                logger.debug("_submit_current_asset: user declined to proceed past warnings")
                return False, (current_map.get("asset_tag") or ""), {}

        # Build PATCH payload
        logger.debug("_submit_current_asset: building patch payload")
        try:
            (payload, any_changes, need_checkin, must_checkin_first,
             to_user_id, to_loc_id) = _build_patch_payload(snapshot)
        except ValueError as ve:
            logger.error("_submit_current_asset: validation error building payload: %s", ve)
            messagebox.showerror("Validation", str(ve))
            return False, (current_map.get("asset_tag") or ""), {}

        asset_id = assetData.get("id")
        logger.debug("_submit_current_asset: asset_id=%s any_changes=%s need_checkin=%s", asset_id, any_changes, need_checkin)
        if any_changes and payload:
            logger.info("_submit_current_asset: PATCHing asset_id=%s", asset_id)
            if not _api_patch_with_retry(asset_id, payload):
                return False, (current_map.get("asset_tag") or ""), {}

        # Assignment transitions
        if need_checkin:
            # explicit unassign
            logger.info("_submit_current_asset: checking in asset_id=%s to unassign", asset_id)
            if not _api_checkin_with_retry(asset_id, note="Consisterizer: unassign"):
                return False, (current_map.get("asset_tag") or ""), {}

        # type change needs a checkin before the checkout
        if must_checkin_first and not need_checkin:
            logger.info("_submit_current_asset: must_checkin_first, checking in asset_id=%s", asset_id)
            if not _api_checkin_with_retry(asset_id, note="Consisterizer: switch assignee type"):
                return False, (current_map.get("asset_tag") or ""), {}

        if to_user_id is not None or to_loc_id is not None:
            # optionally pass a desired expected_checkin date from snapshot
            logger.info("_submit_current_asset: checking out asset_id=%s user_id=%s loc_id=%s", asset_id, to_user_id, to_loc_id)
            if not _api_checkout_with_retry(asset_id,
                                            user_id=to_user_id,
                                            location_id=to_loc_id,
                                            note="Consisterizer: assign"):
                return False, (current_map.get("asset_tag") or ""), {}

        if any_changes or need_checkin or to_user_id is not None or to_loc_id is not None:
            logger.debug("_submit_current_asset: refreshing UI after save")
            _refresh_current_after_save(snapshot)

        # Quiet status line with asset tag
        tag_for_scripts = snapshot.get("asset_tag") or current_map.get("asset_tag") or ""
        if any_changes or need_checkin:
            logger.info("_submit_current_asset: saved tag=%s", tag_for_scripts)
            status_var.set(f"Saved {tag_for_scripts}.")
        else:
            logger.debug("_submit_current_asset: no changes detected")
            status_var.set("No changes.")

        # IMPORTANT: do NOT run scripts here anymore.
        return True, tag_for_scripts, snapshot

    def _switch_asset_in_place(new_tag: str) -> bool:
        """Reload asset data and refresh the UI for a new tag.

        Args:
            new_tag: Asset tag to load.

        Returns:
            True if asset loaded successfully, False on error.
        """
        logger.debug("_switch_asset_in_place: new_tag=%s", new_tag)
        nonlocal assetData, current_map

        logger.info("_switch_asset_in_place: fetching asset info for tag=%s", new_tag)
        try:
            _vl, new_assetData = getAssetInfo(new_tag)
        except Exception as e:
            logger.exception("_switch_asset_in_place: failed to load tag=%s", new_tag)
            messagebox.showerror("Load Failed", f"Could not fetch asset '{new_tag}'.\n{e}")
            return False

        if not new_assetData.get("id"):
            # getAssetInfo() already showed the user an error dialog (asset not
            # found, API error, etc). Bail out here WITHOUT touching assetData/
            # current_map so the currently-loaded asset stays intact instead of
            # getting replaced by a blank/phantom one with no id — that phantom
            # state is what previously made every later save/switch attempt
            # keep failing until the window was closed and reopened.
            logger.warning("_switch_asset_in_place: no asset found for tag=%s, keeping current asset", new_tag)
            return False

        assetData = new_assetData
        current_map = extract_current_values(assetData)
        logger.debug("_switch_asset_in_place: asset loaded, updating UI rows")

        try:
            win.title(f"Consisterizer — {new_tag}")
        except Exception:
            pass

        for k in FIELD_ORDER:
            new_cur = "" if current_map.get(k) is None else str(current_map.get(k, ""))
            row = rows_by_key[k]
            row["current"] = new_cur
            try:
                row["curr_lbl"].configure(text=new_cur)
            except Exception:
                pass

        # refresh {username} runtime based on assigned_to
        logger.debug("_switch_asset_in_place: refreshing runtime_username")
        ar = rows_by_key.get("assigned_to")
        if ar and ar.get("text_widget_type") == "ac":
            ac_txt = ar["ac"].get().strip()
            sel = ar.get("ac_selected")
            logger.debug("_switch_asset_in_place: ac_txt=%s sel_type=%s", ac_txt, (sel or {}).get("type"))
            if ac_txt == "{empty}":
                logger.debug("_switch_asset_in_place: assigned_to is {empty}, clearing username")
                runtime_username.set("")
            elif sel and sel.get("type") == "user":
                def _from_sel(s):
                    """Extract a username from a selection dict.

                    Args:
                        s: Selection dict from autocomplete.

                    Returns:
                        Username string, or empty string if none found.
                    """
                    logger.debug("_from_sel: extracting username from sel")
                    u = (s.get("username") or "").strip()
                    if u:
                        return u
                    em = (s.get("email") or "").strip()
                    if "@" in em:
                        return em.split("@", 1)[0]
                    meta = s.get("meta") or {}
                    u = (meta.get("username") or "").strip()
                    if u:
                        return u
                    em = (s.get("email") or "").strip()
                    if "@" in em:
                        return em.split("@", 1)[0]
                    return ""
                uname = _from_sel(sel) or current_map.get("_assigned_username", "")
                logger.debug("_switch_asset_in_place: setting runtime_username=%s", uname)
                runtime_username.set(uname)
            else:
                logger.debug("_switch_asset_in_place: using current_map username")
                runtime_username.set(current_map.get("_assigned_username", ""))
        else:
            logger.debug("_switch_asset_in_place: no ac assigned_to widget, using current_map username")
            runtime_username.set(current_map.get("_assigned_username", ""))

        logger.debug("_switch_asset_in_place: recomputing results after switch")
        recompute_all_results()
        _update_box_number_state()
        return True

    def _clear_to_wait_for_next(saved_tag: str | None = None, cleared: bool = False):
        """Clear only CURRENT/RESULT and go to a 'waiting' state.

        Keeps all Updates inputs and Reset checkboxes intact.

        Args:
            saved_tag: Optional tag that was just saved, for the status line.
            cleared: True if this is an explicit abandon-without-saving (Clear
                button) rather than a post-submit clear.
        """
        logger.debug("_clear_to_wait_for_next: saved_tag=%s cleared=%s", saved_tag, cleared)
        nonlocal assetData, current_map
        assetData = {}
        current_map = {k: "" for k in FIELD_ORDER}

        # Recompute runtime {username} from the Updates 'assigned_to' (if user picked one).
        logger.debug("_clear_to_wait_for_next: recalculating runtime_username")
        ar = rows_by_key.get("assigned_to")
        if ar and ar.get("text_widget_type") == "ac":
            ac_txt = ar["ac"].get().strip()
            sel = ar.get("ac_selected")
            logger.debug("_clear_to_wait_for_next: ac_txt=%s", ac_txt)
            if ac_txt == "{empty}":
                runtime_username.set("")
            else:
                uname = _username_from_option(sel) or ""
                logger.debug("_clear_to_wait_for_next: setting runtime_username=%s", uname)
                runtime_username.set(uname)
        else:
            runtime_username.set("")

        # Clear ONLY the Current + Result columns; do NOT touch Updates widgets or reset checkboxes.
        logger.debug("_clear_to_wait_for_next: clearing current and result columns")
        for k, r in rows_by_key.items():
            r["current"] = ""
            try:
                r["curr_lbl"].configure(text="")
            except Exception:
                pass
            try:
                r["result_var"].set("")
            except Exception:
                pass
            # Don't modify:
            # - r["text"] contents
            # - r["ac"] contents / selection
            # - r["reset_var"]

        # Reset defaults highlight state against the empty current map
        logger.debug("_clear_to_wait_for_next: clearing defaults and recomputing")
        try:
            active_defaults_templ.clear()
            active_defaults_eval.clear()
            recompute_all_results()
        except Exception:
            pass
        _update_box_number_state()

        # Title + status + focus + submit gating
        try:
            win.title("Consisterizer — (waiting)")
        except Exception:
            pass
        if saved_tag:
            logger.info("_clear_to_wait_for_next: saved tag=%s, entering waiting state", saved_tag)
            status_var.set(f"Saved {saved_tag}. Ready for next asset.")
        elif cleared:
            logger.info("_clear_to_wait_for_next: cleared without saving, entering waiting state")
            status_var.set("Cleared (nothing saved). Ready for next asset.")
        else:
            logger.info("_clear_to_wait_for_next: entering waiting state")
            status_var.set("Ready for next asset.")
        has_current_asset.set(False)
        asset_entry.focus_set()

    def _clear_active_asset():
        """Abandon the current asset without saving or editing it.

        Purges the loaded asset from the screen/active state (like after a
        submit) but never touches Snipe-IT — lets the user skip an asset
        without being forced to either save unwanted edits or discard the
        Updates/Reset selections they want to reuse on the next asset.
        """
        logger.info("_clear_active_asset: clearing active asset without saving")
        if not has_current_asset.get():
            logger.debug("_clear_active_asset: no current asset loaded, nothing to clear")
            return
        _clear_to_wait_for_next(cleared=True)

    def _show_invalid_tag_error(tag: str, log_prefix: str):
        """Show the invalid-asset-tag error, mark the entry, and refocus it."""
        pattern = get_settings().get("assetTagRegex", r"^\d{4,5}$")
        logger.debug("%s: invalid tag=%s pattern=%s", log_prefix, tag, pattern)
        messagebox.showerror("Asset Tag", f"Asset tag does not match pattern: {pattern}")
        try:
            asset_entry.configure(style="ConsistError.TEntry")
        except Exception:
            pass
        asset_entry.focus_set()

    def _load_asset_from_entry() -> bool:
        """Load whatever is typed in the centered Asset Tag box.

        Returns:
            True if asset was loaded successfully, False otherwise.
        """
        tag = asset_tag_var.get().strip()
        logger.debug("_load_asset_from_entry: tag=%s", tag)
        if not valid_asset_tag(tag):
            _show_invalid_tag_error(tag, "_load_asset_from_entry")
            return False
        logger.info("_load_asset_from_entry: loading asset tag=%s", tag)
        ok = _switch_asset_in_place(tag)
        if ok:
            logger.debug("_load_asset_from_entry: asset loaded successfully, clearing entry")
            has_current_asset.set(True)
            try:
                asset_tag_var.set("")
                asset_entry.configure(style="")
            except Exception:
                pass
            status_var.set(f"Loaded {tag}.")
            asset_entry.focus_set()
            return True
        logger.debug("_load_asset_from_entry: _switch_asset_in_place failed for tag=%s", tag)
        return False


    def _submit_and_maybe_switch() -> bool:
        """Submit flow with correct order of operations.

        Batch mode:
          1) Validate the *next* Asset Tag entry (must be 4–5 digits).
          2) Save/update the current asset to Snipe-IT (PATCH/CHECKIN).
          3) Run selected scripts for the asset we just saved.
          4) Switch the UI to the validated next asset and prep for the following scan.

        Non-batch mode:
          1) Save/update the current asset.
          2) Run selected scripts.
          3) Clear to waiting state.

        Returns:
            True if the submit flow completed successfully.
        """
        logger.debug("_submit_and_maybe_switch: batch_mode=%s", batch_mode_var.get())
        # --- 1) (Batch only) validate the next asset tag up front ---
        new_tag = None
        if batch_mode_var.get():
            new_tag = asset_tag_var.get().strip()
            logger.debug("_submit_and_maybe_switch: batch mode, next_tag=%s", new_tag)
            if not valid_asset_tag(new_tag):
                _show_invalid_tag_error(new_tag, "_submit_and_maybe_switch")
                return False

        # --- 2) Save/update current asset in Snipe-IT ---
        logger.info("_submit_and_maybe_switch: submitting current asset")
        ok, tag_for_scripts, snapshot = _submit_current_asset(prompt_on_warnings=not bypass_warnings_var.get())
        if not ok:
            logger.debug("_submit_and_maybe_switch: submit failed, aborting")
            return False

        # --- 3) Run scripts for the asset we just saved ---
        # Build checked_values from reset-checked rows (mirrors the main window's printSelected format).
        checked_values = [tag_for_scripts]
        for k in FIELD_ORDER:
            if k == "asset_tag":
                continue  # printSelected always prepends the tag; skip to avoid printing it twice
            row = rows_by_key.get(k)
            if row and row["reset_var"].get() and snapshot.get(k):
                checked_values.append(snapshot[k])
        logger.debug("_submit_and_maybe_switch: running submit scripts tag=%s checked_values=%s", tag_for_scripts, checked_values)
        _run_selected_submit_scripts(tag_for_scripts, checked_values)

        # --- 4) Switch UI to next asset (batch) or close (non-batch) ---
        if batch_mode_var.get():
            logger.info("_submit_and_maybe_switch: switching to next asset tag=%s", new_tag)
            if not _switch_asset_in_place(new_tag):
                # _switch_asset_in_place already shows an error; keep user on current asset.
                logger.debug("_submit_and_maybe_switch: switch to next asset failed")
                return False
            try:
                asset_tag_var.set("")
                asset_entry.configure(style="")
                asset_entry.focus_set()
            except Exception:
                pass
            return True
        else:
            # In one-at-a-time mode, clear to waiting state instead of closing.
            logger.debug("_submit_and_maybe_switch: non-batch mode, clearing to waiting state")
            _clear_to_wait_for_next(tag_for_scripts)
            return True

    # Bind Enter on the “next asset tag” box to same submit flow
    def _on_asset_tag_return(_e=None):
        """Handle Enter to submit or load the next asset tag."""
        has_asset = has_current_asset.get()
        logger.debug("_on_asset_tag_return: has_current_asset=%s", has_asset)
        # If there is an asset loaded, Enter should submit; if we’re waiting, Enter loads the tag
        if has_asset:
            logger.debug("_on_asset_tag_return: triggering submit flow")
            _submit_and_maybe_switch()
        else:
            logger.debug("_on_asset_tag_return: triggering asset load from entry")
            _load_asset_from_entry()
        return "break"

    asset_entry.bind("<Return>", _on_asset_tag_return, add="+")
    asset_entry.focus_set()

    # Wire up the submit/clear now that functions exist
    submit_btn.configure(command=_submit_and_maybe_switch)
    clear_btn.configure(command=_clear_active_asset)

    # -------------------------------------------------------------------------
    # Initial compute
    # -------------------------------------------------------------------------
    # Force the inner frame to lay out so the scrollregion is correct on open.
    grid_inner.update_idletasks()
    grid_canvas.configure(scrollregion=grid_canvas.bbox("all"))

    # Defer a synthetic Configure event so column widths and wrap-lengths are
    # computed after Tkinter finishes its first geometry pass.
    win.after_idle(lambda: grid_canvas.event_generate("<Configure>"))

    # Run the first full template evaluation to populate all Result labels.
    win.update_idletasks()
    recompute_all_results()
    _update_box_number_state()

    # Re-apply geometry to ensure the window stays at the intended size/position.
    center_window(win, width=W, height=H)
    win.minsize(MIN_W, MIN_H)
    return f"Consisterizer opened for {asset_tag}."
