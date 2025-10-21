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
import os
import re
import platform
import requests
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont
from datetime import datetime, timedelta

from utilities.autocomplete import AutoCompleteEntry
from utilities.otherApiBits import (
    getAssetInfo,
    getAllStatusOptions,
    getAllAssigneeOptions,
    getAllModelOptions,
)
from utilities.Key import API_Key, API_URL_Base  # API creds

from consisterizer.consisterizerScriptsRouting import (
    submit_func_list,
    submit_func_listTXT,
)

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
  • {empty}           → Explicit empty-string (for text fields) OR special clear for Assigned To
  • {blank}           → Keep current (no change) for text-y fields
- You can also reference dotted paths from the raw Snipe asset payload (e.g., {status_label.name}, {model.name}). Unknown tokens are left as-is.
- Special default marker {has_value} (in defaults): requires the field to be non-empty; mismatches are highlighted.

RESULT & HIGHLIGHTING
- “Result” shows the final value that will be sent, after templates/tokens resolve.
- If a field’s Result doesn’t match the active default (or a {has_value} default is empty), it highlights red.

VALIDATION / CLEARING
- Asset Tag must be 4–5 digits when you change it.
- Dates must be YYYY-MM-DD (empty clears).
- Clear rules:
  • Text fields (name, serial, order_number, notes): empty string clears
  • Date fields (purchase_date, expected_checkin): literal "null" string clears
  • purchase_cost: JSON null clears
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


FIELD_COL_PX = 180
RESET_COL_PX = 90
MIN_W = 700
MIN_H = 400

FLEX_MIN_UPDATES = 140
FLEX_MIN_CURRENT = 120
FLEX_MIN_RESULT = 120

TEMPLATES_PATH = os.path.join("consisterizer", "defaultProfiles.json")

KNOWN_FIELDS = set(FIELD_ORDER)

TOKEN_RE = re.compile(r"\{([^{}]+)\}")
ASSET_TAG_RE = re.compile(r"^\d{4,5}$")

HAS_VALUE_SENTINEL = "<<HAS_VALUE>>"

# API base normalization (accepts with/without trailing slash)
SNIPE_BASE = API_URL_Base.rstrip("/")  # e.g., https://host/api/v1
SNIPE_TOKEN = API_Key


# =============================================================================
# Small Helpers (module-level)
# =============================================================================

def _norm_field_key(k: str) -> str:
    if not isinstance(k, str):
        return ""
    return k.strip().lower().replace(" ", "_")


def valid_asset_tag(value: str) -> bool:
    return bool(ASSET_TAG_RE.match(value or ""))


def valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _widget_get_text(widget: tk.Widget) -> str:
    if isinstance(widget, tk.Text):
        return widget.get("1.0", "end-1c")
    return widget.get()


def _widget_set_text(widget: tk.Widget, value: str):
    if isinstance(widget, tk.Text):
        widget.delete("1.0", "end")
        if value:
            widget.insert("1.0", value)
    else:
        widget.delete(0, tk.END)
        if value:
            widget.insert(0, value)


def attach_placeholder(widget: tk.Widget, text: str):
    if not isinstance(widget, (tk.Entry, tk.Text)):
        return

    widget.placeholder_text = text
    widget.placeholder_active = True
    _widget_set_text(widget, text)
    try:
        widget.config(fg="grey")
    except Exception:
        pass

    def _on_focus_in(_e):
        if getattr(widget, "placeholder_active", False):
            _widget_set_text(widget, "")
            try:
                widget.config(fg="black")
            except Exception:
                pass
            widget.placeholder_active = False

    def _on_focus_out(_e):
        if _widget_get_text(widget).strip() == "":
            widget.placeholder_active = True
            _widget_set_text(widget, widget.placeholder_text)
            try:
                widget.config(fg="grey")
            except Exception:
                pass

    widget.bind("<FocusIn>", _on_focus_in)
    widget.bind("<FocusOut>", _on_focus_out)


def is_effective_empty(widget: tk.Widget) -> bool:
    return getattr(widget, "placeholder_active", False) or _widget_get_text(widget).strip() == ""


def extract_current_values(assetData: dict) -> dict:
    asset_tag = assetData.get("asset_tag") or ""
    name = assetData.get("name") or ""
    serial = assetData.get("serial") or ""
    notes = assetData.get("notes") or ""
    purchase_cost = assetData.get("purchase_cost") or ""
    order_number = assetData.get("order_number") or ""
    model_name = (assetData.get("model") or {}).get("name") or ""
    status_name = (assetData.get("status_label") or {}).get("name") or ""
    assigned_obj = (assetData.get("assigned_to") or {})
    assigned_to = assigned_obj.get("name") or ""
    assigned_username = assigned_obj.get("username") or ""
    if not assigned_username:
        email = assigned_obj.get("email") or ""
        if "@" in email:
            assigned_username = email.split("@", 1)[0]
    purchase_date = (assetData.get("purchase_date") or {}).get("date") or ""
    expected_checkin = (assetData.get("expected_checkin") or {}).get("date") or ""

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
        "notes": notes,
        "_assigned_username": assigned_username,
    }
    return base


def _open_help(parent):
    """Open (or focus) a simple read-only help window."""
    # Reuse a single help window if already open
    existing = getattr(parent, "_help_win", None)
    if existing and existing.winfo_exists():
        try:
            existing.lift()
            existing.focus_force()
        except Exception:
            pass
        return

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

# was: def consisterizer(asset_tag, _checked_values=None):
def consisterizer(asset_tag, alias=None, _checked_values=None):
    """
    Open the Consisterizer window for a given asset tag.
    Saves to Snipe-IT via PATCH and runs optional scripts.
    """

    # -------------------------------------------------------------------------
    # Window
    # -------------------------------------------------------------------------
    win = tk.Toplevel()
    win.title(f"Consisterizer — {asset_tag}")
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    W = max(MIN_W, sw)
    H = max(MIN_H, sh)
    x = (sw - W) // 2
    y = (sh - H) // 2
    win.geometry(f"{W}x{H}+{x}+{y}")
    win.minsize(MIN_W, MIN_H)
    win.lift()
    win.bind("<F1>", lambda e: _open_help(win))
    try:
        win.focus_force()
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # Data & Options (preload once)
    # -------------------------------------------------------------------------
    _vl, assetData = getAssetInfo(asset_tag)
    current_map = extract_current_values(assetData)
    default_font = tkfont.nametofont("TkDefaultFont")

    status_options = getAllStatusOptions()
    assignee_options = getAllAssigneeOptions()
    model_options = getAllModelOptions()

    # live value for {username} token
    runtime_username = tk.StringVar(value=current_map.get("_assigned_username", ""))

    def _username_from_option(sel: dict | None) -> str:
        if not sel or sel.get("type") != "user":
            return ""
        u = (sel.get("username") or "").strip()
        if u:
            return u
        em = (sel.get("email") or "").strip()
        if "@" in em:
            return em.split("@", 1)[0]
        meta = sel.get("meta") or {}
        u = (meta.get("username") or "").strip()
        if u:
            return u
        em = (meta.get("email") or "").strip()
        if "@" in em:
            return em.split("@", 1)[0]
        return ""

    # -------------------------------------------------------------------------
    # Styles
    # -------------------------------------------------------------------------
    style = ttk.Style(win)
    try:
        style.configure("ConsistError.TEntry", fieldbackground="#fff1f1", foreground="#b22222")
    except Exception:
        style.configure("ConsistError.TEntry", foreground="#b22222")

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
        return (newval == "") or (newval.isdigit() and len(newval) <= 5)

    asset_entry.configure(validate="key", validatecommand=(win.register(_validate_tag_key), "%P"))
    asset_entry.grid(row=0, column=1)

    # Right side: help button + batch toggle
    right = ttk.Frame(top)
    right.grid(row=0, column=2, sticky="e")

    def _help_click():
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
        v = asset_tag_var.get().strip()
        if re.match(r"^\d{0,5}$", v or ""):
            try:
                asset_entry.configure(style="")
            except Exception:
                pass

    asset_tag_var.trace_add("write", _clear_entry_style_if_valid)

    # Track whether there is an active/loaded asset
    has_current_asset = tk.BooleanVar(value=True)  # we start with an asset loaded

    def _update_submit_enabled(*_):
        try:
            submit_btn.configure(state=("normal" if has_current_asset.get() else "disabled"))
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
    ttk.Checkbutton(opts, text="Maintain selected defaults", variable=maintain_defaults_var).pack(anchor="w")

    # -------------------------------------------------------------------------
    # Grid (sticky header + scrollable body)
    # -------------------------------------------------------------------------
    HEADER_BG = "#e9edf3"
    ROW_BG_1 = "#ffffff"
    ROW_BG_2 = "#f6f8fb"

    grid_box = ttk.LabelFrame(win, text="Fields")
    grid_box.pack(fill="both", expand=True, padx=12, pady=6)
    grid_box.grid_columnconfigure(0, weight=1)

    # Header (fixed)
    header = tk.Frame(grid_box, bg=HEADER_BG)
    header.grid(row=0, column=0, sticky="ew")

    header.grid_columnconfigure(0, weight=0, minsize=FIELD_COL_PX)
    header.grid_columnconfigure(1, weight=1, uniform="flex", minsize=FLEX_MIN_UPDATES)
    header.grid_columnconfigure(2, weight=0, minsize=RESET_COL_PX)
    header.grid_columnconfigure(3, weight=1, uniform="flex", minsize=FLEX_MIN_CURRENT)
    header.grid_columnconfigure(4, weight=1, uniform="flex", minsize=FLEX_MIN_RESULT)

    tk.Label(header, text="Field",   font=("Arial", 12, "bold"), bg=HEADER_BG).grid(row=0, column=0, sticky="w", padx=6, pady=4)
    tk.Label(header, text="Updates", font=("Arial", 12, "bold"), bg=HEADER_BG).grid(row=0, column=1, sticky="w", padx=6, pady=4)
    reset_selected_btn = tk.Button(header, text="Reset")
    reset_selected_btn.grid(row=0, column=2, sticky="w", padx=6, pady=4)
    tk.Label(header, text="Current", font=("Arial", 12, "bold"), bg=HEADER_BG).grid(row=0, column=3, sticky="w", padx=6, pady=4)
    tk.Label(header, text="Result",  font=("Arial", 12, "bold"), bg=HEADER_BG).grid(row=0, column=4, sticky="w", padx=6, pady=4)
    tk.Frame(header, bg="#d6dce5", height=1).grid(row=1, column=0, columnspan=5, sticky="ew")

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
    grid_inner.grid_columnconfigure(0, weight=0, minsize=FIELD_COL_PX)
    grid_inner.grid_columnconfigure(1, weight=1, uniform="flex", minsize=FLEX_MIN_UPDATES)
    grid_inner.grid_columnconfigure(2, weight=0, minsize=RESET_COL_PX)
    grid_inner.grid_columnconfigure(3, weight=1, uniform="flex", minsize=FLEX_MIN_CURRENT)
    grid_inner.grid_columnconfigure(4, weight=1, uniform="flex", minsize=FLEX_MIN_RESULT)

    # Keep scroll/wrap/widths in sync
    rows_by_key = {}

    def _update_scroll_state():
        grid_canvas.configure(scrollregion=grid_canvas.bbox("all"))
        bbox = grid_canvas.bbox("all") or (0, 0, 0, 0)
        content_h = bbox[3] - bbox[1]
        fits = content_h <= max(1, grid_canvas.winfo_height())
        try:
            vscroll.state(["disabled"] if fits else ["!disabled"])
        except Exception:
            vscroll.configure(state=("disabled" if fits else "normal"))
        if fits:
            grid_canvas.yview_moveto(0.0)

    def _apply_wraplengths():
        total = grid_canvas.winfo_width()
        if total <= 1:
            return
        fixed = FIELD_COL_PX + RESET_COL_PX + 24
        remaining = max(0, total - fixed)
        per_col = max(100, remaining // 3)
        for k, rr in rows_by_key.items():
            try:
                rr["res_lbl"].configure(wraplength=per_col - 12)
            except Exception:
                pass

    def _sync_layout(_e=None):
        grid_canvas.itemconfigure(inner_window, width=grid_canvas.winfo_width())
        _update_scroll_state()
        _apply_wraplengths()

    grid_inner.bind("<Configure>", lambda e: _sync_layout(), add="+")
    grid_canvas.bind("<Configure>", _sync_layout, add="+")

    # Smooth, pointer-gated wheel scrolling
    _IS_MAC = platform.system() == "Darwin"
    _SC_UNITS = 1  # slow & steady

    def _pointer_over_canvas():
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
        bbox = grid_canvas.bbox("all") or (0, 0, 0, 0)
        content_h = bbox[3] - bbox[1]
        if not _pointer_over_canvas() or content_h <= max(1, grid_canvas.winfo_height()):
            return
        if _IS_MAC:
            step = -_SC_UNITS if event.delta > 0 else _SC_UNITS
            grid_canvas.yview_scroll(step, "units")
        else:
            if getattr(event, "num", None) == 4:
                grid_canvas.yview_scroll(-_SC_UNITS, "units")
            elif getattr(event, "num", None) == 5:
                grid_canvas.yview_scroll(_SC_UNITS, "units")
            else:
                steps = int(-event.delta / 120) if event.delta else 0
                if steps:
                    grid_canvas.yview_scroll(steps * _SC_UNITS, "units")

    win.bind_all("<MouseWheel>", _on_mousewheel)
    win.bind_all("<Button-4>", _on_mousewheel)
    win.bind_all("<Button-5>", _on_mousewheel)

    # ===== Body rows =====
    for i, key in enumerate(FIELD_ORDER):
        cur = "" if current_map.get(key) is None else str(current_map.get(key, ""))

        row_bg = ROW_BG_1 if (i % 2 == 0) else ROW_BG_2
        _bg = tk.Frame(grid_inner, bg=row_bg, height=1)
        _bg.grid(row=i + 1, column=0, columnspan=5, sticky="nsew")

        tk.Label(grid_inner, text=key, bg=row_bg).grid(row=i + 1, column=0, sticky="w", padx=6, pady=3)

        reset_var = tk.BooleanVar(value=False)
        reset_var.trace_add("write", lambda *_: recompute_all_results())
        tk.Checkbutton(grid_inner, variable=reset_var, bg=row_bg, activebackground=row_bg,
                       highlightthickness=0, bd=0).grid(row=i + 1, column=2, sticky="w", padx=6, pady=3)

        curr_lbl = tk.Label(grid_inner, text=cur, anchor="w", justify="left", bg=row_bg)
        curr_lbl.grid(row=i + 1, column=3, sticky="nsew", padx=6, pady=3)

        result_var = tk.StringVar(value=cur)
        res_lbl = tk.Label(grid_inner, textvariable=result_var, anchor="w", justify="left", bg=row_bg)
        res_lbl.grid(row=i + 1, column=4, sticky="nsew", padx=6, pady=3)

        try:
            fg_default = res_lbl.cget("foreground")
        except Exception:
            fg_default = ""

        row_record = {
            "key": key,
            "reset_var": reset_var,
            "current": cur,
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

            try:
                ac_fg_default = ac.entry.cget("foreground")
            except Exception:
                ac_fg_default = "black"

            def on_change(ac_ref=ac, cur_val=cur, rr=row_record):
                txt = ac_ref.get().strip()
                rr["ac_selected"] = ac_ref.get_selected()
                rr["result_var"].set(txt if txt else cur_val)
                recompute_all_results()

            ac.bind_change(on_change)
            row_record.update({"text_widget_type": "ac", "ac": ac, "ac_fg_default": ac_fg_default})

        elif key == "assigned_to":
            ac = AutoCompleteEntry(grid_inner)
            ac.grid(row=i + 1, column=1, sticky="nsew", padx=6, pady=3)
            ac.set_options(assignee_options)

            try:
                ac_fg_default = ac.entry.cget("foreground")
            except Exception:
                ac_fg_default = "black"

            def on_change(ac_ref=ac, cur_val=cur, rr=row_record):
                txt = ac_ref.get().strip()
                sel = ac_ref.get_selected()
                rr["ac_selected"] = sel

                if txt == "{empty}":
                    runtime_username.set("")
                    rr["result_var"].set("")
                else:
                    live_user = _username_from_option(sel)
                    runtime_username.set(live_user or current_map.get("_assigned_username", ""))
                    rr["result_var"].set(txt if txt else cur_val)

                recompute_all_results()

            ac.bind_change(on_change)
            row_record.update({"text_widget_type": "ac", "ac": ac, "ac_fg_default": ac_fg_default})

        elif key == "model":
            ac = AutoCompleteEntry(grid_inner)
            ac.grid(row=i + 1, column=1, sticky="nsew", padx=6, pady=3)
            ac.set_options(model_options)

            try:
                ac_fg_default = ac.entry.cget("foreground")
            except Exception:
                ac_fg_default = "black"

            def on_change(ac_ref=ac, cur_val=cur, rr=row_record):
                txt = ac_ref.get().strip()
                sel = ac_ref.get_selected()
                rr["ac_selected"] = sel
                if not txt or txt == "{empty}":
                    rr["result_var"].set(cur_val)  # non-clearable
                else:
                    rr["result_var"].set(txt)
                recompute_all_results()

            ac.bind_change(on_change)
            row_record.update({"text_widget_type": "ac", "ac": ac, "ac_fg_default": ac_fg_default})

        else:
            text = tk.Text(grid_inner, height=1, width=1, wrap="word", font=default_font, bg="white")
            text.grid(row=i + 1, column=1, sticky="nsew", padx=6, pady=3)
            if key in PLACEHOLDERS:
                attach_placeholder(text, PLACEHOLDERS[key])

            def handler(_e=None, t=text):
                try:
                    dl = int(t.count("1.0", "end-1c", "displaylines")[0])
                except Exception:
                    dl = 1
                t.configure(height=max(1, min(2, dl)))
                recompute_all_results()

            text.bind("<KeyRelease>", handler, add="+")
            text.bind("<FocusOut>",   handler, add="+")
            text.bind("<Configure>",  handler, add="+")

            row_record.update({"text_widget_type": "text", "text": text})

        rows_by_key[key] = row_record

    # -------------------------------------------------------------------------
    # Templates (load & normalize)
    # -------------------------------------------------------------------------
    def _load_templates(path=TEMPLATES_PATH):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
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
            return rules
        except Exception:
            return []

    template_rules = _load_templates()

    # -------------------------------------------------------------------------
    # Evaluation helpers
    # -------------------------------------------------------------------------
    def evaluate_template_string(template: str, current_key: str, visited: set):
        if "{blank}" in template:
            return "", True
        if "{empty}" in template:
            return "", False

        def repl(match):
            token = match.group(1).strip()

            if token == "today":
                return datetime.now().strftime("%Y-%m-%d")
            if token == "tomorrow":
                return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            if token == "username":
                return runtime_username.get() or current_map.get("_assigned_username", "")
            if token.endswith("_current"):
                base = token[:-8]
                if base in FIELD_ORDER:
                    return current_map.get(base, "")
                return ""
            if token in FIELD_ORDER:
                if token in visited:
                    return current_map.get(token, "")
                return evaluate_row(token, visited=set(visited))
            # dotted path into original assetData
            parts = token.split(".")
            cur = assetData
            for p in parts:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    return match.group(0)
            try:
                return str(cur if cur is not None else "")
            except Exception:
                return match.group(0)

        expanded = TOKEN_RE.sub(repl, template)
        return expanded, False

    def evaluate_row(key: str, visited=None):
        if visited is None:
            visited = set()
        if key in visited:
            return current_map.get(key, "")
        visited.add(key)

        row = rows_by_key.get(key)
        if row is None:
            return current_map.get(key, "")

        if key in {"status", "assigned_to", "model"}:
            if row.get("text_widget_type") == "ac":
                val = row["ac"].get().strip()

                if key == "assigned_to" and val == "{empty}":
                    return ""  # explicit clear

                if key in {"model", "status"} and (not val or val == "{empty}"):
                    return current_map.get(key, "")

                return val if val else current_map.get(key, "")
            return current_map.get(key, "")

        if row.get("text_widget_type") == "text":
            if is_effective_empty(row["text"]):
                return current_map.get(key, "")
            raw = _widget_get_text(row["text"])
            text, is_blank = evaluate_template_string(raw, key, visited)
            if is_blank:
                return current_map.get(key, "")
            return text

        return current_map.get(key, "")

    def _asset_path_value(path: str):
        cur = assetData
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return ""
        if isinstance(cur, dict) or cur is None:
            return ""
        return str(cur)

    # -------------------------------------------------------------------------
    # Defaults computation & highlighting
    # -------------------------------------------------------------------------
    active_defaults_templ: dict[str, str] = {}
    active_defaults_eval: dict[str, str] = {}
    _applying_maintained_defaults = False

    def recompute_defaults(result_snapshot: dict):
        active_defaults_templ.clear()
        active_defaults_eval.clear()

        for rule in template_rules:
            ok = True
            for lhs, expected in (rule["conditions"] or {}).items():
                lhs_val = (result_snapshot.get(lhs, "") if lhs in FIELD_ORDER else _asset_path_value(lhs))
                exp_raw = str(expected).strip()

                if exp_raw == "{has_value}":
                    if not str(lhs_val).strip():
                        ok = False
                        break
                    continue

                rhs, _ = evaluate_template_string(exp_raw, lhs, visited=set())
                if str(lhs_val) != str(rhs):
                    ok = False
                    break

            if not ok:
                continue

            for f, templ in (rule["defaults"] or {}).items():
                if f not in FIELD_ORDER or f in active_defaults_templ:
                    continue

                raw_t = str(templ).strip()
                if raw_t == "{has_value}":
                    active_defaults_templ[f] = raw_t
                    active_defaults_eval[f] = HAS_VALUE_SENTINEL
                    continue

                eval_t, is_blank = evaluate_template_string(raw_t, f, visited=set())
                if is_blank:
                    continue

                active_defaults_templ[f] = raw_t
                active_defaults_eval[f] = eval_t

    def _apply_maintained_defaults() -> bool:
        changed = False
        for key, r in rows_by_key.items():
            if not r["reset_var"].get():
                continue

            raw_default = (active_defaults_templ.get(key, "") or "").strip()
            eval_default = active_defaults_eval.get(key, None)

            if r.get("text_widget_type") == "ac":
                ac = r["ac"]
                if eval_default and eval_default != HAS_VALUE_SENTINEL:
                    desired = eval_default
                elif raw_default == "{empty}" and key == "assigned_to":
                    desired = "{empty}"
                else:
                    continue

                cur_text = ac.get().strip()
                if cur_text != desired:
                    if hasattr(ac, "set_selected_by_label") and desired != "{empty}":
                        ac.set_selected_by_label(desired)
                    else:
                        ac.set(desired)
                    r["ac_selected"] = ac.get_selected()
                    r["result_var"].set("" if (key == "assigned_to" and desired == "{empty}") else desired)
                    changed = True

            else:
                if not raw_default or raw_default == "{has_value}":
                    continue
                cur_text = _widget_get_text(r["text"])
                if cur_text != raw_default:
                    _widget_set_text(r["text"], raw_default)
                    try:
                        r["text"].config(bg="white")
                    except Exception:
                        pass
                    changed = True

        return changed

    def recompute_all_results():
        nonlocal _applying_maintained_defaults

        snapshot = {}
        for k in FIELD_ORDER:
            snapshot[k] = evaluate_row(k, visited=set())
            rows_by_key[k]["result_var"].set(snapshot[k])

        recompute_defaults(snapshot)

        if maintain_defaults_var.get() and not _applying_maintained_defaults:
            if _apply_maintained_defaults():
                _applying_maintained_defaults = True
                try:
                    snapshot = {}
                    for k in FIELD_ORDER:
                        snapshot[k] = evaluate_row(k, visited=set())
                        rows_by_key[k]["result_var"].set(snapshot[k])
                    recompute_defaults(snapshot)
                finally:
                    _applying_maintained_defaults = False

        for k in FIELD_ORDER:
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

            res_lbl.configure(foreground="#b22222" if mismatch else default_fg)

            if row.get("text_widget_type") == "text":
                try:
                    row["text"].configure(bg="#fff1f1" if mismatch else "white")
                except Exception:
                    pass
            elif row.get("text_widget_type") == "ac":
                entry = row["ac"].entry
                try:
                    entry.configure(style="ConsistError.TEntry" if mismatch else "")
                except Exception:
                    try:
                        entry.configure(
                            foreground="#b22222" if mismatch else row.get("ac_fg_default", "black")
                        )
                    except Exception:
                        pass

    maintain_defaults_var.trace_add("write", lambda *_: recompute_all_results())

    # -------------------------------------------------------------------------
    # Reset Selected
    # -------------------------------------------------------------------------
    def reset_selected():
        results_snapshot = {k: evaluate_row(k, visited=set()) for k in FIELD_ORDER}
        recompute_defaults(results_snapshot)

        for r in rows_by_key.values():
            if not r["reset_var"].get():
                continue

            key = r["key"]
            raw_default = (active_defaults_templ.get(key, None) or "").strip()
            eval_default = active_defaults_eval.get(key, None)

            if r.get("text_widget_type") == "ac":
                ac = r["ac"]
                if eval_default and eval_default != HAS_VALUE_SENTINEL:
                    if hasattr(ac, "set_selected_by_label"):
                        ac.set_selected_by_label(eval_default)
                    else:
                        ac.set(eval_default)
                    r["ac_selected"] = ac.get_selected()
                    r["result_var"].set(eval_default)
                elif raw_default == "{empty}" and key == "assigned_to":
                    ac.set("{empty}")
                    r["ac_selected"] = None
                    r["result_var"].set("")
                else:
                    ac.set("")
                    r["ac_selected"] = None
                    r["result_var"].set(r["current"])
            else:
                t = r["text"]
                if raw_default and raw_default != "{has_value}":
                    _widget_set_text(t, raw_default)
                else:
                    _widget_set_text(t, "")
                    if key in PLACEHOLDERS:
                        attach_placeholder(t, PLACEHOLDERS[key])
                try:
                    t.config(bg="white")
                except Exception:
                    pass

            r["reset_var"].set(False)

        recompute_all_results()

    reset_selected_btn.configure(command=reset_selected)

    # -------------------------------------------------------------------------
    # Snipe-IT helpers (ID mapping + PATCH/CHECKIN with retry)
    # -------------------------------------------------------------------------
    def _label_id_map(options):
        m = {}
        for opt in (options or []):
            label = opt.get("label") or opt.get("name") or opt.get("text") or str(opt.get("value") or opt.get("id") or "")
            label = str(label).strip()
            _id = opt.get("id") or opt.get("value") or (opt.get("meta") or {}).get("id")
            if label and _id is not None:
                m[label] = _id
        return m

    def _id_from_sel(sel):
        if not isinstance(sel, dict):
            return None
        for k in ("id", "value", "user_id", "model_id", "status_id"):
            if sel.get(k) is not None:
                return sel[k]
        meta = sel.get("meta") or {}
        for k in ("id", "user_id", "model_id", "status_id"):
            if meta.get(k) is not None:
                return meta[k]
        return None

    status_label_to_id = _label_id_map(status_options)
    model_label_to_id = _label_id_map(model_options)
    assignee_label_to_id = _label_id_map(assignee_options)

    def _build_patch_payload(snapshot: dict):
        """
        Compare snapshot vs current, return (payload, any_changes, need_checkin).
        Maps UI keys -> Snipe-IT API keys and coerces types.

        Clearing rules:
          - Text fields (name, serial, order_number, notes): "" (empty string)
          - Date fields (purchase_date, expected_checkin):  "null" (string)
          - Numeric (purchase_cost):                       None (JSON null)
          - Unassign user:                                 handled via CHECKIN (need_checkin=True)
        """
        NULL_STR = "null"
        TEXT_CLEAR_EMPTY = {"name", "serial", "order_number", "notes"}
        DATE_CLEAR_NULLSTR = {"purchase_date", "expected_checkin"}

        payload = {}
        changed = False
        need_checkin = False
        checkout_user_id = None
        checkout_location_id = None
        must_checkin_first = False  # <<<<< NEW

        current_assignee_type = ((assetData.get("assigned_to") or {}).get("type") or "").strip().lower()

        for key in FIELD_ORDER:
            new = snapshot.get(key, "")
            old = rows_by_key[key]["current"]
            if str(new) == str(old):
                continue
            changed = True

            if key == "assigned_to":
                txt = (new or "").strip()
                sel = rows_by_key[key].get("ac_selected")
                sel_type = ((sel or {}).get("type") or "").strip().lower()

                if txt in ("", "{empty}"):
                    # explicit clear
                    need_checkin = True

                elif sel_type == "user":
                    checkout_user_id = _id_from_sel(sel)
                    if checkout_user_id is None:
                        raise ValueError("Pick a *User* from the list (or type {empty} to clear).")
                    # if changing from location->user (or user->location below), require checkin first
                    if current_assignee_type and current_assignee_type != "user":
                        must_checkin_first = True

                elif sel_type == "location":
                    checkout_location_id = _id_from_sel(sel)
                    if checkout_location_id is None:
                        raise ValueError("Pick a *Location* from the list.")
                    # make default/home location match too (optional)
                    payload["location_id"] = checkout_location_id
                    if current_assignee_type and current_assignee_type != "location":
                        must_checkin_first = True

                else:
                    raise ValueError("Select either a User or a Location from suggestions.")
                continue

            else:
                # Any future fields default to pass-through
                payload[key] = new

        return payload, changed, need_checkin, must_checkin_first, checkout_user_id, checkout_location_id

    def _api_patch_with_retry(asset_id: int, payload: dict) -> bool:
        if not SNIPE_BASE or not SNIPE_TOKEN:
            messagebox.showerror("Snipe-IT", "Missing API_URL_Base or API_Key in utilities.Key.")
            return False

        url = f"{SNIPE_BASE}/hardware/{asset_id}"
        headers = {
            "Authorization": f"Bearer {SNIPE_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        def _cursor_busy(on=True):
            try:
                win.config(cursor="watch" if on else "")
                win.update_idletasks()
            except Exception:
                pass

        while True:
            try:
                _cursor_busy(True)
                r = requests.patch(url, json=payload, headers=headers, timeout=25)
            except requests.RequestException as e:
                _cursor_busy(False)
                if not messagebox.askretrycancel("Network Error", f"{e}\n\nRetry?"):
                    return False
                continue
            finally:
                _cursor_busy(False)

            if 200 <= r.status_code < 300:
                try:
                    data = r.json()
                    if str(data.get("status")).lower() == "error":
                        msgs = data.get("messages")
                        if isinstance(msgs, list):
                            msg = "; ".join(msgs)
                        elif isinstance(msgs, dict):
                            msg = "; ".join(str(v) for v in msgs.values())
                        else:
                            msg = str(msgs or data)
                        if not messagebox.askretrycancel("Update failed", f"Snipe-IT error:\n{msg}\n\nRetry?"):
                            return False
                        continue
                except Exception:
                    pass
                return True

            try:
                detail = r.json()
            except Exception:
                detail = r.text
            if not messagebox.askretrycancel("HTTP Error", f"PATCH {r.status_code}\n{detail}\n\nRetry?"):
                return False

    def _api_checkin_with_retry(asset_id: int, note: str = "Consisterizer unassign", location_id: int | None = None) -> bool:
        """POST /hardware/{id}/checkin to unassign the asset."""
        if not SNIPE_BASE or not SNIPE_TOKEN:
            messagebox.showerror("Snipe-IT", "Missing API_URL_Base or API_Key in utilities.Key.")
            return False

        url = f"{SNIPE_BASE}/hardware/{asset_id}/checkin"
        headers = {
            "Authorization": f"Bearer {SNIPE_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = {"note": note}
        if location_id is not None:
            body["location_id"] = location_id

        def _cursor_busy(on=True):
            try:
                win.config(cursor="watch" if on else "")
                win.update_idletasks()
            except Exception:
                pass

        while True:
            try:
                _cursor_busy(True)
                r = requests.post(url, json=body, headers=headers, timeout=25)
            except requests.RequestException as e:
                _cursor_busy(False)
                if not messagebox.askretrycancel("Network Error", f"{e}\n\nRetry?"):
                    return False
                continue
            finally:
                _cursor_busy(False)

            if 200 <= r.status_code < 300:
                try:
                    data = r.json()
                    if str(data.get("status")).lower() == "error":
                        msg = "; ".join(data.get("messages") or []) or str(data)
                        if not messagebox.askretrycancel("Check-in failed", f"Snipe-IT error:\n{msg}\n\nRetry?"):
                            return False
                        continue
                except Exception:
                    pass
                return True

            try:
                detail = r.json()
            except Exception:
                detail = r.text
            if not messagebox.askretrycancel("HTTP Error", f"CHECKIN {r.status_code}\n{detail}\n\nRetry?"):
                return False

    def _api_checkout_with_retry(asset_id: int, *, user_id: int | None = None,
                                 location_id: int | None = None,
                                 note: str = "Consisterizer assign/checkout",
                                 expected_checkin: str | None = None) -> bool:
        if not SNIPE_BASE or not SNIPE_TOKEN:
            messagebox.showerror("Snipe-IT", "Missing API_URL_Base or API_Key in utilities.Key.")
            return False

        url = f"{SNIPE_BASE}/hardware/{asset_id}/checkout"
        headers = {
            "Authorization": f"Bearer {SNIPE_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        body = {"note": note}
        if user_id is not None:
            body.update({"checkout_to_type": "user", "assigned_user": user_id})
        elif location_id is not None:
            body.update({"checkout_to_type": "location", "assigned_location": location_id})
        else:
            messagebox.showerror("Snipe-IT", "Checkout requires user_id or location_id.")
            return False

        if expected_checkin:
            body["expected_checkin"] = expected_checkin  # "YYYY-MM-DD"

        def _cursor_busy(on=True):
            try:
                win.config(cursor="watch" if on else "")
                win.update_idletasks()
            except Exception:
                pass

        while True:
            try:
                _cursor_busy(True)
                r = requests.post(url, json=body, headers=headers, timeout=25)
            except requests.RequestException as e:
                _cursor_busy(False)
                if not messagebox.askretrycancel("Network Error", f"{e}\n\nRetry?"):
                    return False
                continue
            finally:
                _cursor_busy(False)

            if 200 <= r.status_code < 300:
                try:
                    data = r.json()
                    if str(data.get("status")).lower() == "error":
                        msg = "; ".join(data.get("messages") or []) or str(data)
                        if not messagebox.askretrycancel("Checkout failed", f"Snipe-IT error:\n{msg}\n\nRetry?"):
                            return False
                        continue
                except Exception:
                    pass
                return True

            try:
                detail = r.json()
            except Exception:
                detail = r.text
            if not messagebox.askretrycancel("HTTP Error", f"CHECKOUT {r.status_code}\n{detail}\n\nRetry?"):
                return False

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

    # Submit button stub; real command attached later after function defs
    submit_btn = ttk.Button(footer, text="Submit & Save")
    submit_btn.grid(row=1, column=1, padx=8)  # centered
    ttk.Button(footer, text="Close", command=win.destroy).grid(row=1, column=2, sticky="e")

    # --- Alias support -------------------------------------------------------
    def _to_alias_obj(a):
        """Accept dict or JSON string; return dict or {}."""
        if not a:
            return {}
        if isinstance(a, dict):
            return a
        if isinstance(a, str):
            try:
                return json.loads(a)
            except Exception:
                return {}
        return {}

    def _norm_alias_key(k: str) -> str:
        return (k or "").strip().lower().replace(" ", "_")

    # reverse lookups in case alias specifies IDs
    def _label_from_id(label_to_id: dict, wanted_id):
        for lbl, _id in (label_to_id or {}).items():
            if _id == wanted_id:
                return lbl
        return None

    def _apply_alias(a):
        """
        Alias schema (all optional):
        {
          "title": "Check-in",
          "batch_mode": true/false,
          "maintain_defaults": true/false,
          "set": {
            "<field>": "<value or {empty} or template>",       # text fields
            "status": "<label or {'id': 12} or {'label': '...'}>",
            "model":  "<label or {'id': 34}>",
            "assigned_to": "<label | {empty} | {'id': 7}>"
          },
          "reset": true | false | {"field": true/false, ...} | ["field1","field2"],
          "scripts": "all" | [0, 2, "Script Name", ...]
        }
        """
        a = _to_alias_obj(a)
        if not a:
            return

        # 2.1 Title suffix
        title_suffix = a.get("title")
        if title_suffix:
            try:
                win.title(f"{win.title()} • {title_suffix}")
            except Exception:
                pass

        # 2.2 Top-level toggles
        if "batch_mode" in a:
            try:
                batch_mode_var.set(bool(a["batch_mode"]))
            except Exception:
                pass

        if "maintain_defaults" in a:
            try:
                maintain_defaults_var.set(bool(a["maintain_defaults"]))
            except Exception:
                pass

        # 2.3 Scripts selection (by index or case-insensitive name)
        scr = a.get("scripts")
        if scr:
            if scr == "all":
                for v in script_vars:
                    v.set(True)
            else:
                wanted = set(scr if isinstance(scr, (list, tuple)) else [scr])
                # pre-normalize names
                name_to_idx = {s.lower(): i for i, s in enumerate(submit_func_listTXT)}
                for item in wanted:
                    if isinstance(item, int) and 0 <= item < len(script_vars):
                        script_vars[item].set(True)
                    elif isinstance(item, str):
                        idx = name_to_idx.get(item.lower())
                        if idx is not None:
                            script_vars[idx].set(True)

        # 2.4 Reset checkboxes
        rst = a.get("reset")
        if isinstance(rst, bool):
            for r in rows_by_key.values():
                r["reset_var"].set(rst)
        elif isinstance(rst, dict):
            for k, flag in rst.items():
                nk = _norm_alias_key(k)
                if nk in rows_by_key:
                    rows_by_key[nk]["reset_var"].set(bool(flag))
        elif isinstance(rst, (list, tuple)):
            want = { _norm_alias_key(x) for x in rst }
            for k, r in rows_by_key.items():
                r["reset_var"].set(k in want)

        # 2.5 Pre-fill Updates column
        preset = a.get("set") or {}
        if isinstance(preset, dict):
            for k, v in preset.items():
                fk = _norm_alias_key(k)
                if fk not in rows_by_key:
                    continue
                row = rows_by_key[fk]

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

                    # For assigned_to we support {empty}
                    if fk == "assigned_to" and v.strip() == "{empty}":
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
                    txt = "" if v is None else str(v)
                    _widget_set_text(row["text"], txt)
                    # ensure placeholder is considered inactive if we’ve typed something
                    try:
                        row["text"].placeholder_active = (txt == "")
                    except Exception:
                        pass

        # Recompute once after all sets
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
        return {k: evaluate_row(k, visited=set()) for k in FIELD_ORDER}

    def _collect_validation_errors(snapshot: dict):
        """Enforce asset_tag/date only on fields that are changing vs current.
           Empty string on DATE_FIELDS is allowed to mean 'clear'. """
        errors = []
        for key, final_val in snapshot.items():
            if final_val == rows_by_key[key]["current"]:
                continue

            if key == "asset_tag" and not valid_asset_tag(final_val):
                errors.append(f"[asset_tag] must be 4–5 digits (got '{final_val}')")

            if key in DATE_FIELDS:
                if final_val == "":  # allow clearing dates with {empty}
                    continue
                if not valid_date(final_val):
                    errors.append(f"[{key}] must be YYYY-MM-DD (got '{final_val}')")
        return errors

    def _collect_default_warnings(snapshot: dict):
        warnings = []
        for k in FIELD_ORDER:
            if k not in active_defaults_eval:
                continue
            expected = active_defaults_eval[k]
            actual = (snapshot.get(k, "") or "")
            if expected == HAS_VALUE_SENTINEL:
                if str(actual).strip() == "":
                    warnings.append(f"- {k}: empty, but default requires a value")
            else:
                if str(actual) != str(expected):
                    warnings.append(f"- {k}: '{actual}' ≠ default '{expected}'")
        return warnings

    def _run_selected_submit_scripts(asset_tag_for_scripts: str):
        """Run checked submit scripts. Silent on success; dialog on any failures."""
        had_error = False
        lines = []
        for i, var in enumerate(script_vars):
            if not var.get():
                continue
            try:
                ret = submit_func_list[i](asset_tag_for_scripts)
                if ret not in (None, ""):
                    lines.append(f"✓ {submit_func_listTXT[i]}: {ret}")
            except Exception as e:
                had_error = True
                lines.append(f"✗ {submit_func_listTXT[i]}: {e}")
        if had_error:
            messagebox.showerror("Script Errors", "\n".join(lines))

    def _refresh_current_after_save(saved_snapshot: dict):
        # If asset_tag changed, reload by new tag; otherwise by existing tag
        new_tag = saved_snapshot.get("asset_tag") or current_map.get("asset_tag") or ""
        if not new_tag:
            return
        _switch_asset_in_place(new_tag)

    def _submit_current_asset(prompt_on_warnings: bool = True) -> tuple[bool, str]:
        """
        Validate, warn on default mismatches, push to Snipe-IT (PATCH),
        optionally CHECKIN to unassign, refresh, and update the status line.

        Returns:
          (ok, tag_for_scripts)
            ok: True if the save/checkin flow succeeded
            tag_for_scripts: the asset tag we just operated on (for script runner)
        """
        if not has_current_asset.get():
            messagebox.showinfo("Consisterizer", "Enter or scan an asset tag first.")
            return False, ""

        status_var.set("")  # clear previous message
        snapshot = _collect_snapshot()

        # Local validations (only for changed fields)
        errors = _collect_validation_errors(snapshot)
        if errors:
            messagebox.showerror("Validation Errors", "Please fix the following:\n\n" + "\n".join(errors))
            return False, (current_map.get("asset_tag") or "")

        warnings = _collect_default_warnings(snapshot) if prompt_on_warnings else []
        if warnings:
            show = warnings[:10]
            extra = len(warnings) - len(show)
            if extra > 0:
                show.append(f"... and {extra} more.")
            proceed = messagebox.askyesno(
                "Defaults Warning",
                "Some values differ from the current defaults:\n\n" + "\n".join(show) + "\n\nProceed anyway?"
            )
            if not proceed:
                return False, (current_map.get("asset_tag") or "")

        # Build PATCH payload
        try:
            (payload, any_changes, need_checkin, must_checkin_first,
             to_user_id, to_loc_id) = _build_patch_payload(snapshot)
        except ValueError as ve:
            messagebox.showerror("Validation", str(ve))
            return False, (current_map.get("asset_tag") or "")

        asset_id = assetData.get("id")
        if any_changes and payload:
            if not _api_patch_with_retry(asset_id, payload):
                return False, (current_map.get("asset_tag") or "")

        # Assignment transitions
        if need_checkin:
            # explicit unassign
            if not _api_checkin_with_retry(asset_id, note="Consisterizer: unassign"):
                return False, (current_map.get("asset_tag") or "")

        # type change needs a checkin before the checkout
        if must_checkin_first and not need_checkin:
            if not _api_checkin_with_retry(asset_id, note="Consisterizer: switch assignee type"):
                return False, (current_map.get("asset_tag") or "")

        if to_user_id is not None or to_loc_id is not None:
            # optionally pass a desired expected_checkin date from snapshot
            if not _api_checkout_with_retry(asset_id,
                                            user_id=to_user_id,
                                            location_id=to_loc_id,
                                            note="Consisterizer: assign"):
                return False, (current_map.get("asset_tag") or "")

        if any_changes or need_checkin or to_user_id is not None or to_loc_id is not None:
            _refresh_current_after_save(snapshot)

        # Quiet status line with asset tag
        tag_for_scripts = snapshot.get("asset_tag") or current_map.get("asset_tag") or ""
        if any_changes or need_checkin:
            status_var.set(f"Saved {tag_for_scripts}.")
        else:
            status_var.set("No changes.")

        # IMPORTANT: do NOT run scripts here anymore.
        return True, tag_for_scripts

    def _switch_asset_in_place(new_tag: str) -> bool:
        nonlocal assetData, current_map

        try:
            _vl, new_assetData = getAssetInfo(new_tag)
        except Exception as e:
            messagebox.showerror("Load Failed", f"Could not fetch asset '{new_tag}'.\n{e}")
            return False

        assetData = new_assetData
        current_map = extract_current_values(assetData)

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
        ar = rows_by_key.get("assigned_to")
        if ar and ar.get("text_widget_type") == "ac":
            ac_txt = ar["ac"].get().strip()
            sel = ar.get("ac_selected")
            if ac_txt == "{empty}":
                runtime_username.set("")
            elif sel and sel.get("type") == "user":
                def _from_sel(s):
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
                runtime_username.set(_from_sel(sel) or current_map.get("_assigned_username", ""))
            else:
                runtime_username.set(current_map.get("_assigned_username", ""))
        else:
            runtime_username.set(current_map.get("_assigned_username", ""))

        recompute_all_results()
        return True

    def _clear_to_wait_for_next(saved_tag: str | None = None):
        """Clear only CURRENT/RESULT and go to a 'waiting' state.
           Keep all Updates inputs and Reset checkboxes intact."""
        nonlocal assetData, current_map
        assetData = {}
        current_map = {k: "" for k in FIELD_ORDER}

        # Recompute runtime {username} from the Updates 'assigned_to' (if user picked one).
        ar = rows_by_key.get("assigned_to")
        if ar and ar.get("text_widget_type") == "ac":
            ac_txt = ar["ac"].get().strip()
            sel = ar.get("ac_selected")
            if ac_txt == "{empty}":
                runtime_username.set("")
            else:
                runtime_username.set(_username_from_option(sel) or "")
        else:
            runtime_username.set("")

        # Clear ONLY the Current + Result columns; do NOT touch Updates widgets or reset checkboxes.
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
        try:
            active_defaults_templ.clear()
            active_defaults_eval.clear()
            recompute_all_results()
        except Exception:
            pass

        # Title + status + focus + submit gating
        try:
            win.title("Consisterizer — (waiting)")
        except Exception:
            pass
        if saved_tag:
            status_var.set(f"Saved {saved_tag}. Ready for next asset.")
        else:
            status_var.set("Ready for next asset.")
        has_current_asset.set(False)
        asset_entry.focus_set()

    def _load_asset_from_entry() -> bool:
        """Load whatever is typed in the centered Asset Tag box."""
        tag = asset_tag_var.get().strip()
        if not valid_asset_tag(tag):
            messagebox.showerror("Asset Tag", "Asset tag must be 4–5 digits.")
            try:
                asset_entry.configure(style="ConsistError.TEntry")
            except Exception:
                pass
            asset_entry.focus_set()
            return False
        ok = _switch_asset_in_place(tag)
        if ok:
            has_current_asset.set(True)
            try:
                asset_tag_var.set("")
                asset_entry.configure(style="")
            except Exception:
                pass
            status_var.set(f"Loaded {tag}.")
            asset_entry.focus_set()
            return True
        return False


    def _submit_and_maybe_switch() -> bool:
        """
        Submit flow with correct order of operations.

        Batch mode:
          1) Validate the *next* Asset Tag entry (must be 4–5 digits).
          2) Save/update the current asset to Snipe-IT (PATCH/CHECKIN).
          3) Run selected scripts for the asset we just saved.
          4) Switch the UI to the validated next asset and prep for the following scan.

        Non-batch mode:
          1) Save/update the current asset.
          2) Run selected scripts.
          3) Close the window.
        """
        # --- 1) (Batch only) validate the next asset tag up front ---
        new_tag = None
        if batch_mode_var.get():
            new_tag = asset_tag_var.get().strip()
            if not valid_asset_tag(new_tag):
                messagebox.showerror("Asset Tag", "Asset tag must be 4–5 digits.")
                try:
                    asset_entry.configure(style="ConsistError.TEntry")
                except Exception:
                    pass
                asset_entry.focus_set()
                return False

        # --- 2) Save/update current asset in Snipe-IT ---
        ok, tag_for_scripts = _submit_current_asset(prompt_on_warnings=True)
        if not ok:
            return False

        # --- 3) Run scripts for the asset we just saved ---
        _run_selected_submit_scripts(tag_for_scripts)

        # --- 4) Switch UI to next asset (batch) or close (non-batch) ---
        if batch_mode_var.get():
            if not _switch_asset_in_place(new_tag):
                # _switch_asset_in_place already shows an error; keep user on current asset.
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
            _clear_to_wait_for_next(tag_for_scripts)
            return True

    # Bind Enter on the “next asset tag” box to same submit flow
    def _on_asset_tag_return(_e=None):
        # If there is an asset loaded, Enter should submit; if we’re waiting, Enter loads the tag
        if has_current_asset.get():
            _submit_and_maybe_switch()
        else:
            _load_asset_from_entry()
        return "break"

    asset_entry.bind("<Return>", _on_asset_tag_return, add="+")
    asset_entry.focus_set()

    # Wire up the submit now that functions exist
    submit_btn.configure(command=_submit_and_maybe_switch)

    # -------------------------------------------------------------------------
    # Initial compute
    # -------------------------------------------------------------------------
    grid_inner.update_idletasks()
    grid_canvas.configure(scrollregion=grid_canvas.bbox("all"))

    win.after_idle(lambda: grid_canvas.event_generate("<Configure>"))

    win.update_idletasks()
    recompute_all_results()

    win.geometry(f"{W}x{H}+{x}+{y}")
    win.minsize(MIN_W, MIN_H)
    return f"Consisterizer opened for {asset_tag}"
