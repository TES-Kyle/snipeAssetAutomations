"""Create charger assets via Snipe-IT with optional checkout."""

# makeCharger.py (full-width layout + YYYY-MM-DD entry + inline "loading…" placeholders)
import logging
from utilities.otherApiBits import (
    getAssetInfo,
    getAllStatusOptions,
    getAllAssigneeOptions,
    getAllModelOptions,
)
from utilities.autocomplete import AutoCompleteEntry
from utilities.Key import API_URL_Base
from utilities.api_user import get_api_headers, get_api_key
from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings

import tkinter as tk
from tkinter import ttk, messagebox

import requests
import subprocess
import platform
import threading
import time
import re


SNIPE_BASE = (API_URL_Base or "").rstrip("/")  # e.g., https://host/api/v1

CHARGER_CATEGORY_ID_DEFAULT = 35  # prefer this; fall back to name “charger”

logger = logging.getLogger(__name__)


def makeCharger(asset_tag):
    """Create a charger asset and optionally assign it.

    Args:
        asset_tag: Asset tag passed from the main UI (may be unused in flow).

    Returns:
        Status message string for the main UI.
    """
    configure_logging()
    settings = get_settings()
    try:
        charger_category_id = int(settings.get("chargerCategoryId", CHARGER_CATEGORY_ID_DEFAULT))
    except Exception:
        charger_category_id = CHARGER_CATEGORY_ID_DEFAULT
    name_prefix = settings.get("chargerNamePrefix", "Charger-")
    name_default = settings.get("chargerNameDefault", "Charger")
    # ------------------------ serial autodetect (macOS) ------------------------
    def get_charger_serial_number():
        """Return the local charger serial number on macOS, if available."""
        if platform.system() != "Darwin":
            raise OSError("Unsupported operating system")
        try:
            result = subprocess.run(
                "system_profiler SPPowerDataType | awk '/AC Charger Information:/,/Charging/' | grep 'Serial Number'",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            return (result.stdout.strip().split(': ', 1)[-1] or "").strip()
        except Exception:
            return ""

    def serial_updater():
        """Continuously refresh the serial number entry from the system."""
        while True:
            try:
                serial_number.set(get_charger_serial_number())
                time.sleep(0.25)
            except Exception as e:
                messagebox.showerror(title="Error", message=str(e))
                break

    def start_serial_update():
        """Launch the background serial updater thread."""
        threading.Thread(target=serial_updater, daemon=True).start()

    # ------------------------ helpers ------------------------
    def _id_from_sel(sel: dict | None):
        """Extract an ID value from a selection dict."""
        if not isinstance(sel, dict):
            return None
        for k in ("id", "value", "user_id", "model_id", "status_id", "location_id"):
            if sel.get(k) is not None:
                return sel[k]
        meta = sel.get("meta") or {}
        for k in ("id", "user_id", "model_id", "status_id", "location_id"):
            if meta.get(k) is not None:
                return meta[k]
        return None

    def _api_headers():
        """Return Snipe-IT headers using the active API user."""
        return get_api_headers()

    def _busy_cursor(on=True):
        """Toggle the busy cursor for the charger window."""
        try:
            charger_window.config(cursor="watch" if on else "")
            charger_window.update_idletasks()
        except Exception:
            pass

    def _require_api_creds():
        """Validate that API URL and key are available."""
        if not SNIPE_BASE or not get_api_key():
            logger.error("Missing API_URL_Base or API key in utilities.Key")
            messagebox.showerror("Snipe-IT", "Missing API_URL_Base or API key in utilities.Key.")
            return False
        return True

    def _serial_exists_in_snipe(serial: str) -> tuple[bool | None, str | None]:
        """Return (exists, asset_tag) for a serial lookup, or (None, None) on errors."""
        url = f"{SNIPE_BASE}/hardware/byserial/{serial}"
        try:
            r = requests.get(url, headers=_api_headers(), timeout=20)
            r.raise_for_status()
            data = r.json() or {}
        except Exception as e:
            logger.exception("Serial lookup failed for %s", serial)
            messagebox.showerror("Serial Lookup Failed", f"Could not verify serial {serial}.\n\n{e}")
            return None, None

        if not isinstance(data, dict):
            logger.error("Unexpected serial lookup response for %s: %r", serial, data)
            messagebox.showerror("Serial Lookup Failed", "Unexpected response from Snipe-IT.")
            return None, None

        msg = data.get("messages") or data.get("message") or ""
        if isinstance(msg, list):
            msg = "; ".join(str(item) for item in msg if item is not None)

        if str(data.get("status", "")).lower() == "error" and "does not exist" in str(msg):
            return False, None

        rows = data.get("rows")
        if isinstance(rows, list) and rows:
            row0 = rows[0] or {}
            tag = str(row0.get("asset_tag") or row0.get("assetTag") or "").strip()
            return True, (tag or None)

        tag = str(data.get("asset_tag") or data.get("assetTag") or "").strip()
        if tag or data.get("serial"):
            return True, (tag or None)

        total = data.get("total")
        if total == 0:
            return False, None

        if str(msg).strip() == "Asset does not exist.":
            return False, None

        logger.warning("Serial lookup ambiguous for %s: %s", serial, data)
        messagebox.showerror("Serial Lookup Failed", "Could not determine if the serial is already in use.")
        return None, None

    def _sel_label(sel: dict | None) -> str:
        """Return the display label for a selection dict."""
        if not isinstance(sel, dict):
            return ""
        return (sel.get("label") or sel.get("name") or str(sel.get("id") or "")).strip()

    def _require_ac_pick(ac: AutoCompleteEntry, field_name: str) -> tuple[int | None, bool]:
        """
        Returns (id_or_None, ok_bool).
        ok only if entry text is non-empty AND matches the selected option label.
        """
        txt = (ac.get() or "").strip()
        sel = ac.get_selected()
        lbl = _sel_label(sel)
        if not txt or not sel or (lbl and txt != lbl):
            messagebox.showerror("Validation", f"{field_name} is required — pick from the suggestions.")
            return None, False
        return _id_from_sel(sel), True

    logger.debug("Using chargerCategoryId=%s for model filtering", charger_category_id)

    # ---- Model filter (charger-only) ----
    def _is_charger_model(opt: dict) -> bool:
        """Return True when a model option looks like a charger."""
        label = (opt.get("label") or opt.get("name") or "").lower()
        meta = opt.get("meta") or {}
        if isinstance(meta.get("category"), dict):
            cat_id = meta["category"].get("id")
            cat_name = (meta["category"].get("name") or "").lower()
        else:
            cat_id = meta.get("category_id")
            cat_name = (meta.get("category_name") or "").lower()
        if charger_category_id is not None and cat_id == charger_category_id:
            return True
        if "charger" in cat_name:
            return True
        return "charger" in label

    # ------------------------ async preload ------------------------
    status_options_ready = threading.Event()
    assignee_options_ready = threading.Event()
    model_options_ready = threading.Event()

    status_options_data = []
    assignee_options_data = []
    model_options_data = []

    # Inline placeholder support for AutoCompleteEntry
    def _set_loading_placeholder(ac: AutoCompleteEntry, text="loading…", disable=True):
        """Apply a disabled placeholder to an autocomplete entry."""
        try:
            ac.entry.configure(foreground="#666")
            ac.entry.delete(0, tk.END)
            ac.entry.insert(0, text)
            ac._placeholder_active = True  # mark
            if disable:
                ac.entry.state(["disabled"])
        except Exception:
            pass

    def _clear_placeholder_if_loading(ac: AutoCompleteEntry):
        """Remove loading placeholder state if it is active."""
        # clear only if we set our loading placeholder
        if getattr(ac, "_placeholder_active", False):
            try:
                ac.entry.state(["!disabled"])
                ac.entry.delete(0, tk.END)
                ac.entry.configure(foreground="black")
            except Exception:
                pass
            ac._placeholder_active = False

    def _apply_preloaded_options_to_widgets():
        """Push preloaded options into autocomplete widgets."""
        # Runs on Tk thread
        if status_options_ready.is_set():
            _clear_placeholder_if_loading(status_ac)
            status_ac.set_options(status_options_data)
        if assignee_options_ready.is_set():
            _clear_placeholder_if_loading(assignee_ac)
            assignee_ac.set_options(assignee_options_data)
        if model_options_ready.is_set():
            _clear_placeholder_if_loading(model_ac)
            model_ac.set_options(model_options_data)

    def _preload_options_thread():
        """Fetch options in the background and notify the UI."""
        nonlocal status_options_data, assignee_options_data, model_options_data
        try:
            status_options_data = getAllStatusOptions() or []
        except Exception:
            status_options_data = []
        status_options_ready.set()

        try:
            assignee_options_data = getAllAssigneeOptions() or []
        except Exception:
            assignee_options_data = []
        assignee_options_ready.set()

        try:
            m_opts = getAllModelOptions() or []
            model_options_data = sorted([o for o in m_opts if _is_charger_model(o)],
                                        key=lambda o: (o.get("label") or "").lower())
        except Exception:
            model_options_data = []
        model_options_ready.set()

        try:
            charger_window.after(0, _apply_preloaded_options_to_widgets)
        except Exception:
            pass

    # ------------------------ submit flow ------------------------
    def submit(_e=None):
        """Validate entries and create/check out the charger asset."""
        if not _require_api_creds():
            return
        logger.info("Starting makeCharger submit for %s", asset_number.get())

        # Don't allow submit while required pickers still "loading…"
        if getattr(status_ac, "_placeholder_active", False) or getattr(model_ac, "_placeholder_active", False):
            messagebox.showinfo("Please wait", "Still loading options. Try again in a moment.")
            return

        # Validate "doesn't exist yet" by checking Snipe for current tag.
        _, assetData = getAssetInfo(asset_number.get(), allow_missing=True)
        if not assetData:
            logger.error("Asset lookup failed; aborting makeCharger for %s", asset_number.get())
            return

        msg = assetData.get("messages") or ""
        if isinstance(msg, list):
            msg = "; ".join(str(item) for item in msg if item is not None)
        exists = msg != "Asset does not exist."
        logger.debug("Asset existence check for %s: msg=%r exists=%s", asset_number.get(), msg, exists)
        if exists:
            logger.warning("Charger asset tag already exists: %s", asset_number.get())
            messagebox.showerror(
                "Process Failed",
                f"Asset tag {asset_number.get().strip()} already exists.",
            )
            return

        # Gather and normalize user-entered values.
        tag = asset_number.get().strip()
        serial = serial_number.get().strip()
        name_suffix = name_var.get().strip()
        purchase_date_val = purchase_date_var.get().strip()
        purchase_cost = cost_var.get().strip()
        order_number = order_var.get().strip()

        # Date validation (allow blank or YYYY-MM-DD)
        if purchase_date_val and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", purchase_date_val):
            messagebox.showerror("Validation", "Purchase Date must be YYYY-MM-DD or blank.")
            return

        # Status (must be a real picked row).
        status_id, ok = _require_ac_pick(status_ac, "Status")
        if not ok:
            return

        # Model (must be a real picked row).
        model_id, ok = _require_ac_pick(model_ac, "Model")
        if not ok:
            return

        # Assigned To (optional) with validation of type.
        assn_sel = assignee_ac.get_selected()
        assn_type = (assn_sel or {}).get("type", "").strip().lower() if assn_sel else ""
        user_id = None
        location_id = None
        if assn_sel:
            if assn_type == "user":
                user_id = _id_from_sel(assn_sel)
            elif assn_type == "location":
                location_id = _id_from_sel(assn_sel)
            else:
                messagebox.showerror("Checkout To", "Pick a *User* or *Location* from suggestions, or leave blank.")
                return

        # Field checks for required inputs.
        if not status_id:
            messagebox.showerror("Validation", "Status is required (pick from list).")
            return
        if not model_id:
            messagebox.showerror("Validation", "Model is required (pick from list).")
            return
        if not serial:
            messagebox.showerror("Validation", "Serial number is required.")
            return

        exists_serial, existing_tag = _serial_exists_in_snipe(serial)
        logger.debug(
            "Serial existence check for %s: exists=%s tag=%r",
            serial,
            exists_serial,
            existing_tag,
        )
        if exists_serial is None:
            return
        if exists_serial:
            tag_msg = f" (asset tag {existing_tag})" if existing_tag else ""
            logger.warning("Charger serial already exists: %s%s", serial, tag_msg)
            messagebox.showerror(
                "Process Failed",
                f"Serial {serial} already exists in Snipe-IT{tag_msg}.",
            )
            return

        # Build payload for the new asset record.
        payload = {
            "asset_tag": tag,
            "status_id": status_id,
            "model_id": model_id,
            "name": (f"{name_prefix}{name_suffix}") if name_suffix else name_default,
            "serial": serial,
        }
        logger.debug("Create charger payload: %s", payload)
        if purchase_date_val:
            payload["purchase_date"] = purchase_date_val
        if purchase_cost:
            try:
                payload["purchase_cost"] = float(purchase_cost)
            except Exception:
                messagebox.showerror("Validation", "Purchase Cost must be a number (e.g., 19.99).")
                return
        if order_number:
            payload["order_number"] = order_number

        # POST /hardware with retry loop.
        create_url = f"{SNIPE_BASE}/hardware"
        while True:
            try:
                _busy_cursor(True)
                r = requests.post(create_url, json=payload, headers=_api_headers(), timeout=25)
            except requests.RequestException as e:
                _busy_cursor(False)
                logger.exception("Network error creating charger asset")
                if not messagebox.askretrycancel("Network Error", f"{e}\n\nRetry?"):
                    return
                continue
            finally:
                _busy_cursor(False)

            if 200 <= r.status_code < 300:
                try:
                    data = r.json()
                except Exception:
                    data = {}
                if str(data.get("status", "")).lower() == "error":
                    msgs = data.get("messages")
                    msg = "; ".join(msgs) if isinstance(msgs, list) else str(msgs or data)
                    logger.error("Create charger asset failed: %s", msg)
                    if not messagebox.askretrycancel("Create failed", f"Snipe-IT error:\n{msg}\n\nRetry?"):
                        return
                    continue
                asset_id = (data.get("payload") or {}).get("id")
                if not asset_id:
                    logger.error("Charger asset created but ID missing in response")
                    messagebox.showerror("Create", "Asset created but ID missing in response.")
                    return
                logger.info("Charger asset created: %s", asset_id)
                break
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            logger.error("Create charger asset HTTP %s: %s", r.status_code, detail)
            if not messagebox.askretrycancel("HTTP Error", f"POST {r.status_code}\n{detail}\n\nRetry?"):
                return

        # Optional checkout when a user or location was selected.
        if user_id is not None or location_id is not None:
            co_url = f"{SNIPE_BASE}/hardware/{asset_id}/checkout"
            body = {"note": "makeCharger: assign/checkout"}
            if user_id is not None:
                body.update({"checkout_to_type": "user", "assigned_user": user_id})
            else:
                body.update({"checkout_to_type": "location", "assigned_location": location_id})
            logger.debug("Charger checkout payload: %s", body)

            while True:
                try:
                    _busy_cursor(True)
                    r = requests.post(co_url, json=body, headers=_api_headers(), timeout=25)
                except requests.RequestException as e:
                    _busy_cursor(False)
                    logger.exception("Network error during charger checkout")
                    if not messagebox.askretrycancel("Network Error", f"{e}\n\nRetry?"):
                        break
                    continue
                finally:
                    _busy_cursor(False)

                if 200 <= r.status_code < 300:
                    try:
                        data = r.json()
                        if str(data.get("status")).lower() == "error":
                            msg = "; ".join(data.get("messages") or []) or str(data)
                            logger.error("Charger checkout failed: %s", msg)
                            if not messagebox.askretrycancel("Checkout failed", f"Snipe-IT error:\n{msg}\n\nRetry?"):
                                break
                            continue
                    except Exception:
                        pass
                    break
                try:
                    detail = r.json()
                except Exception:
                    detail = r.text
                logger.error("Charger checkout HTTP %s: %s", r.status_code, detail)
                if not messagebox.askretrycancel("HTTP Error", f"CHECKOUT {r.status_code}\n{detail}\n\nRetry?"):
                    break

        # Done → batch handling or close
        if batch_var.get():
            soft_message.set(f"Asset Created: tag={tag}, name={payload['name']}")
            # increment tag
            try:
                asset_number.set(str(int(tag) + 1))
            except Exception:
                pass

            # Only clear Name + Assignee (keep status/model/date/cost/order as-is)
            name_var.set("")
            try:
                assignee_ac.set("")  # clear text
                assignee_ac._selected = None  # clear selection (safe no-op if attr missing)
            except Exception:
                pass

            # focus next tag for fast scanning
            try:
                asset_entry.focus_set()
                asset_entry.selection_range(0, tk.END)
            except Exception:
                pass
        else:
            charger_window.destroy()

    # ------------------------ UI ------------------------
    try:
        serial_number = tk.StringVar(value=get_charger_serial_number())
    except OSError:
        messagebox.showerror(title="Process Failed", message="Unsupported Operating System")
        return "makeCharger failed due to unsupported operating system"

    charger_window = tk.Toplevel()
    charger_window.title("Make Charger")

    # Use grid + weights everywhere so entries fill horizontally
    # ---------- Asset Tag Row ----------
    asset_frame = ttk.Frame(charger_window)
    asset_frame.pack(fill="x", padx=10, pady=6)
    asset_frame.grid_columnconfigure(0, weight=0)  # label
    asset_frame.grid_columnconfigure(1, weight=1)  # entry (fills)
    asset_frame.grid_columnconfigure(2, weight=0)  # batch

    ttk.Label(asset_frame, text="Asset Tag:").grid(row=0, column=0, sticky="w")

    asset_number = tk.StringVar(value=str(asset_tag))
    asset_entry = ttk.Entry(asset_frame, textvariable=asset_number)
    asset_entry.grid(row=0, column=1, sticky="ew")
    asset_entry.bind("<Return>", submit)

    batch_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(asset_frame, text="Batch", variable=batch_var)\
        .grid(row=0, column=2, sticky="e", padx=(10, 0))

    # ---------- Serial Row ----------
    serial_frame = ttk.Frame(charger_window)
    serial_frame.pack(fill="x", padx=10, pady=6)
    serial_frame.grid_columnconfigure(0, weight=0)
    serial_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(serial_frame, text="Serial Number:").grid(row=0, column=0, sticky="w")
    serial_entry = ttk.Entry(serial_frame, textvariable=serial_number, state="readonly")
    serial_entry.grid(row=0, column=1, sticky="ew")
    start_serial_update()

    # ---------- Model ----------
    model_frame = ttk.Frame(charger_window)
    model_frame.pack(fill="x", padx=10, pady=6)
    model_frame.grid_columnconfigure(0, weight=0)
    model_frame.grid_columnconfigure(1, weight=1)  # entry fills
    ttk.Label(model_frame, text="Model:").grid(row=0, column=0, sticky="w")
    model_ac = AutoCompleteEntry(model_frame, width=20)
    model_ac.grid(row=0, column=1, sticky="ew")
    _set_loading_placeholder(model_ac, "loading…", disable=True)

    # ---------- Status ----------
    status_frame = ttk.Frame(charger_window)
    status_frame.pack(fill="x", padx=10, pady=6)
    status_frame.grid_columnconfigure(0, weight=0)
    status_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky="w")
    status_ac = AutoCompleteEntry(status_frame, width=20)
    status_ac.grid(row=0, column=1, sticky="ew")
    _set_loading_placeholder(status_ac, "loading…", disable=True)

    # ---------- Assigned To (optional) ----------
    assignee_frame = ttk.Frame(charger_window)
    assignee_frame.pack(fill="x", padx=10, pady=6)
    assignee_frame.grid_columnconfigure(0, weight=0)
    assignee_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(assignee_frame, text="Checkout To (optional):").grid(row=0, column=0, sticky="w")
    assignee_ac = AutoCompleteEntry(assignee_frame, width=20)
    assignee_ac.grid(row=0, column=1, sticky="ew")
    _set_loading_placeholder(assignee_ac, "loading…", disable=True)

    # ---------- Name ----------
    name_frame = ttk.Frame(charger_window)
    name_frame.pack(fill="x", padx=10, pady=6)
    name_frame.grid_columnconfigure(0, weight=0)
    name_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(name_frame, text="Asset Name: Charger-").grid(row=0, column=0, sticky="w")
    name_var = tk.StringVar()
    name_entry = ttk.Entry(name_frame, textvariable=name_var)
    name_entry.grid(row=0, column=1, sticky="ew")
    name_entry.bind("<Return>", submit)

    # ---------- Purchase Cost ----------
    def _validate_float(P):
        """Allow empty or float-like text for purchase cost."""
        if P == "":
            return True
        try:
            float(P)
            return True
        except ValueError:
            return False

    cost_frame = ttk.Frame(charger_window)
    cost_frame.pack(fill="x", padx=10, pady=6)
    cost_frame.grid_columnconfigure(0, weight=0)
    cost_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(cost_frame, text="Purchase Cost:").grid(row=0, column=0, sticky="w")
    cost_var = tk.StringVar()
    ttk.Entry(cost_frame, textvariable=cost_var,
              validate="key", validatecommand=(charger_window.register(_validate_float), "%P"))\
        .grid(row=0, column=1, sticky="ew")

    # ---------- Purchase Date (Entry, YYYY-MM-DD or blank) ----------
    date_partial_re = re.compile(r"^\d{0,4}(-\d{0,2}(-\d{0,2})?)?$")

    def _validate_date(P: str) -> bool:
        """Allow partial/complete YYYY-MM-DD input."""
        # Permit deletion
        if P == "":
            return True
        # Disallow anything longer than 10
        if len(P) > 10:
            return False
        # Only digits and hyphens in allowed positions, with partials OK
        return bool(date_partial_re.fullmatch(P))

    date_frame = ttk.Frame(charger_window)
    date_frame.pack(fill="x", padx=10, pady=6)
    date_frame.grid_columnconfigure(0, weight=0)
    date_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(date_frame, text="Purchase Date (YYYY-MM-DD):").grid(row=0, column=0, sticky="w")
    purchase_date_var = tk.StringVar()
    ttk.Entry(date_frame, textvariable=purchase_date_var,
              validate="key", validatecommand=(charger_window.register(_validate_date), "%P"))\
        .grid(row=0, column=1, sticky="ew")

    # ---------- Order Number ----------
    order_frame = ttk.Frame(charger_window)
    order_frame.pack(fill="x", padx=10, pady=6)
    order_frame.grid_columnconfigure(0, weight=0)
    order_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(order_frame, text="Order Number:").grid(row=0, column=0, sticky="w")
    order_var = tk.StringVar()
    ttk.Entry(order_frame, textvariable=order_var).grid(row=0, column=1, sticky="ew")

    # ---------- Submit ----------
    submit_btn = ttk.Button(charger_window, text="Submit", command=submit)
    submit_btn.pack(pady=10)

    # ---------- Soft status line ----------
    soft_message_frame = ttk.Frame(charger_window)
    soft_message_frame.pack(fill="x", padx=10, pady=6)
    soft_message = tk.StringVar()
    ttk.Label(soft_message_frame, textvariable=soft_message).pack(anchor="w")

    # Center the window
    charger_window.update_idletasks()
    sw, sh = charger_window.winfo_screenwidth(), charger_window.winfo_screenheight()
    ww, wh = charger_window.winfo_width(), charger_window.winfo_height()
    cx = int((sw - ww) / 2)
    cy = int((sh - wh) / 2)
    charger_window.geometry(f"+{cx}+{cy}")

    # Ensure API user prompt (if needed) happens on the main thread.
    get_api_key()

    # Kick off async loads after showing window
    threading.Thread(target=_preload_options_thread, daemon=True).start()
    return f"Make Charger window opened for {asset_tag}."
