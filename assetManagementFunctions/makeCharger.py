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
from utilities.tk_geometry import center_window
from utilities.tk_date_entry import build_date_entry_frame
from utilities.api_retry import call_with_retry

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
    logger.info("makeCharger: starting for asset_tag=%s", asset_tag)
    settings = get_settings()
    try:
        charger_category_id = int(settings.get("chargerCategoryId", CHARGER_CATEGORY_ID_DEFAULT))
    except Exception:
        charger_category_id = CHARGER_CATEGORY_ID_DEFAULT
    name_prefix = settings.get("chargerNamePrefix", "Charger-")
    name_default = settings.get("chargerNameDefault", "Charger")
    logger.debug("makeCharger: charger_category_id=%s name_prefix=%s name_default=%s", charger_category_id, name_prefix, name_default)
    # ------------------------ serial autodetect (macOS) ------------------------
    def get_charger_serial_number():
        """Return the local charger serial number on macOS, if available."""
        logger.debug("get_charger_serial_number: platform=%s", platform.system())
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
            serial = (result.stdout.strip().split(': ', 1)[-1] or "").strip()
            logger.debug("get_charger_serial_number: detected serial=%s", serial)
            return serial
        except Exception:
            logger.debug("get_charger_serial_number: failed to detect serial, returning empty")
            return ""

    def serial_updater():
        """Continuously refresh the serial number entry from the system."""
        logger.debug("serial_updater: starting continuous serial refresh loop")
        while True:
            try:
                new_serial = get_charger_serial_number()
                logger.debug("serial_updater: refreshed serial=%s", new_serial)
                serial_number.set(new_serial)
                time.sleep(0.25)
            except Exception as e:
                logger.exception("serial_updater: error during serial refresh")
                messagebox.showerror(title="Error", message=str(e))
                break

    def start_serial_update():
        """Launch the background serial updater thread."""
        logger.debug("start_serial_update: launching serial updater daemon thread")
        threading.Thread(target=serial_updater, daemon=True).start()

    # ------------------------ helpers ------------------------
    def _id_from_sel(sel: dict | None):
        """Extract an ID value from a selection dict.

        Args:
            sel: Selection dict from an AutoCompleteEntry widget.

        Returns:
            ID value or None if not found.
        """
        logger.debug("_id_from_sel: sel=%s", sel)
        if not isinstance(sel, dict):
            return None
        for k in ("id", "value", "user_id", "model_id", "status_id", "location_id"):
            if sel.get(k) is not None:
                logger.debug("_id_from_sel: found id via key=%s value=%s", k, sel[k])
                return sel[k]
        meta = sel.get("meta") or {}
        for k in ("id", "user_id", "model_id", "status_id", "location_id"):
            if meta.get(k) is not None:
                logger.debug("_id_from_sel: found id via meta key=%s value=%s", k, meta[k])
                return meta[k]
        logger.debug("_id_from_sel: no id found in sel")
        return None

    def _api_headers():
        """Return Snipe-IT headers using the active API user."""
        logger.debug("_api_headers: returning API headers")
        return get_api_headers()

    def _require_api_creds():
        """Validate that API URL and key are available.

        Returns:
            True if credentials are present, False otherwise.
        """
        logger.debug("_require_api_creds: checking SNIPE_BASE=%s", bool(SNIPE_BASE))
        if not SNIPE_BASE or not get_api_key():
            logger.error("Missing API_URL_Base or API key in utilities.Key")
            messagebox.showerror("Snipe-IT", "Missing API_URL_Base or API key in utilities.Key.")
            return False
        return True

    def _serial_exists_in_snipe(serial: str) -> tuple[bool | None, str | None]:
        """Return (exists, asset_tag) for a serial lookup, or (None, None) on errors.

        Args:
            serial: Serial number string to look up in Snipe-IT.

        Returns:
            Tuple of (exists, asset_tag); exists is None on API errors.
        """
        logger.debug("_serial_exists_in_snipe: serial=%s", serial)
        url = f"{SNIPE_BASE}/hardware/byserial/{serial}"
        try:
            logger.info("_serial_exists_in_snipe: querying Snipe-IT for serial=%s", serial)
            r = requests.get(url, headers=_api_headers(), timeout=20)
            r.raise_for_status()
            data = r.json() or {}
            logger.debug("_serial_exists_in_snipe: response data keys=%s", list(data.keys()) if isinstance(data, dict) else type(data).__name__)
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
            logger.debug("_serial_exists_in_snipe: serial=%s does not exist in Snipe-IT", serial)
            return False, None

        rows = data.get("rows")
        if isinstance(rows, list) and rows:
            row0 = rows[0] or {}
            tag = str(row0.get("asset_tag") or row0.get("assetTag") or "").strip()
            logger.debug("_serial_exists_in_snipe: serial=%s exists, tag=%s", serial, tag)
            return True, (tag or None)

        tag = str(data.get("asset_tag") or data.get("assetTag") or "").strip()
        if tag or data.get("serial"):
            logger.debug("_serial_exists_in_snipe: serial=%s exists (direct), tag=%s", serial, tag)
            return True, (tag or None)

        total = data.get("total")
        if total == 0:
            logger.debug("_serial_exists_in_snipe: total=0 for serial=%s", serial)
            return False, None

        if str(msg).strip() == "Asset does not exist.":
            logger.debug("_serial_exists_in_snipe: 'Asset does not exist' for serial=%s", serial)
            return False, None

        logger.warning("Serial lookup ambiguous for %s: %s", serial, data)
        messagebox.showerror("Serial Lookup Failed", "Could not determine if the serial is already in use.")
        return None, None

    def _sel_label(sel: dict | None) -> str:
        """Return the display label for a selection dict.

        Args:
            sel: Selection dict from an AutoCompleteEntry widget.

        Returns:
            Display label string, or empty string if not found.
        """
        if not isinstance(sel, dict):
            return ""
        label = (sel.get("label") or sel.get("name") or str(sel.get("id") or "")).strip()
        logger.debug("_sel_label: label=%s", label)
        return label

    def _require_ac_pick(ac: AutoCompleteEntry, field_name: str) -> tuple[int | None, bool]:
        """Validate that an AutoCompleteEntry has a valid selection.

        Args:
            ac: The AutoCompleteEntry widget to validate.
            field_name: Human-readable field name for error messages.

        Returns:
            (id, ok) tuple; ok is False and id is None when validation fails.
        """
        txt = (ac.get() or "").strip()
        sel = ac.get_selected()
        lbl = _sel_label(sel)
        logger.debug("_require_ac_pick: field=%s txt=%s sel=%s lbl=%s", field_name, txt, sel, lbl)
        if not txt or not sel or (lbl and txt != lbl):
            logger.warning("_require_ac_pick: validation failed for field=%s txt=%s", field_name, txt)
            messagebox.showerror("Validation", f"{field_name} is required — pick from the suggestions.")
            return None, False
        resolved_id = _id_from_sel(sel)
        logger.debug("_require_ac_pick: resolved id=%s for field=%s", resolved_id, field_name)
        return resolved_id, True

    logger.debug("Using chargerCategoryId=%s for model filtering", charger_category_id)

    # ---- Model filter (charger-only) ----
    def _is_charger_model(opt: dict) -> bool:
        """Return True when a model option looks like a charger.

        Args:
            opt: Model option dict from the API results.

        Returns:
            True if the option matches the charger category or label.
        """
        label = (opt.get("label") or opt.get("name") or "").lower()
        meta = opt.get("meta") or {}
        if isinstance(meta.get("category"), dict):
            cat_id = meta["category"].get("id")
            cat_name = (meta["category"].get("name") or "").lower()
        else:
            cat_id = meta.get("category_id")
            cat_name = (meta.get("category_name") or "").lower()
        logger.debug("_is_charger_model: label=%s cat_id=%s cat_name=%s", label, cat_id, cat_name)
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

    def _apply_preloaded_options_to_widgets():
        """Push preloaded options into autocomplete widgets."""
        # Runs on Tk thread
        logger.debug("_apply_preloaded_options_to_widgets: status_ready=%s assignee_ready=%s model_ready=%s",
                     status_options_ready.is_set(), assignee_options_ready.is_set(), model_options_ready.is_set())
        if status_options_ready.is_set():
            logger.debug("_apply_preloaded_options_to_widgets: applying %s status options", len(status_options_data))
            status_ac.set_loading(False)
            status_ac.set_options(status_options_data)
        if assignee_options_ready.is_set():
            logger.debug("_apply_preloaded_options_to_widgets: applying %s assignee options", len(assignee_options_data))
            assignee_ac.set_loading(False)
            assignee_ac.set_options(assignee_options_data)
        if model_options_ready.is_set():
            logger.debug("_apply_preloaded_options_to_widgets: applying %s model options", len(model_options_data))
            model_ac.set_loading(False)
            model_ac.set_options(model_options_data)

    def _preload_options_thread():
        """Fetch options in the background and notify the UI."""
        nonlocal status_options_data, assignee_options_data, model_options_data
        logger.debug("_preload_options_thread: starting background preload")
        try:
            status_options_data = getAllStatusOptions() or []
            logger.debug("_preload_options_thread: loaded %s status options", len(status_options_data))
        except Exception:
            logger.exception("_preload_options_thread: failed to load status options")
            status_options_data = []
        status_options_ready.set()

        try:
            assignee_options_data = getAllAssigneeOptions() or []
            logger.debug("_preload_options_thread: loaded %s assignee options", len(assignee_options_data))
        except Exception:
            logger.exception("_preload_options_thread: failed to load assignee options")
            assignee_options_data = []
        assignee_options_ready.set()

        try:
            m_opts = getAllModelOptions() or []
            model_options_data = sorted([o for o in m_opts if _is_charger_model(o)],
                                        key=lambda o: (o.get("label") or "").lower())
            logger.debug("_preload_options_thread: loaded %s charger model options", len(model_options_data))
        except Exception:
            logger.exception("_preload_options_thread: failed to load model options")
            model_options_data = []
        model_options_ready.set()

        try:
            logger.debug("_preload_options_thread: scheduling UI update on Tk thread")
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
        if status_ac.is_loading() or model_ac.is_loading():
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
        assn_type = assn_sel.get("type", "").strip().lower() if assn_sel else ""
        user_id = None
        location_id = None
        logger.debug("submit: assn_sel=%s assn_type=%s", assn_sel, assn_type)
        if assn_sel:
            if assn_type == "user":
                user_id = _id_from_sel(assn_sel)
                logger.debug("submit: assigning to user_id=%s", user_id)
            elif assn_type == "location":
                location_id = _id_from_sel(assn_sel)
                logger.debug("submit: assigning to location_id=%s", location_id)
            else:
                logger.warning("submit: unknown assn_type=%s", assn_type)
                messagebox.showerror("Checkout To", "Pick a *User* or *Location* from suggestions, or leave blank.")
                return

        # Field checks for required inputs.
        if not status_id:
            logger.warning("submit: no status_id; aborting")
            messagebox.showerror("Validation", "Status is required (pick from list).")
            return
        if not model_id:
            logger.warning("submit: no model_id; aborting")
            messagebox.showerror("Validation", "Model is required (pick from list).")
            return
        if not serial:
            logger.warning("submit: no serial; aborting")
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

        # POST /hardware with retry.
        create_url = f"{SNIPE_BASE}/hardware"
        data = call_with_retry(
            "Create charger asset",
            lambda: requests.post(create_url, json=payload, headers=_api_headers(), timeout=25),
            busy_widget=charger_window,
        )
        if data is None:
            return
        # Extract the new asset ID from the response payload.
        asset_id = (data.get("payload") or {}).get("id")
        if not asset_id:
            logger.error("Charger asset created but ID missing in response")
            messagebox.showerror("Create", "Asset created but ID missing in response.")
            return
        logger.info("Charger asset created: %s", asset_id)

        # Optional checkout when a user or location was selected.
        if user_id is not None or location_id is not None:
            co_url = f"{SNIPE_BASE}/hardware/{asset_id}/checkout"
            body = {"note": "makeCharger: assign/checkout"}
            if user_id is not None:
                body.update({"checkout_to_type": "user", "assigned_user": user_id})
            else:
                body.update({"checkout_to_type": "location", "assigned_location": location_id})
            logger.debug("Charger checkout payload: %s", body)

            # Result intentionally not checked further -- a cancelled/failed
            # checkout still falls through to batch handling/close below,
            # matching the original loop's break-not-return on cancel.
            call_with_retry(
                "Charger checkout",
                lambda: requests.post(co_url, json=body, headers=_api_headers(), timeout=25),
                busy_widget=charger_window,
            )

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
    model_ac.set_loading(True)

    # ---------- Status ----------
    status_frame = ttk.Frame(charger_window)
    status_frame.pack(fill="x", padx=10, pady=6)
    status_frame.grid_columnconfigure(0, weight=0)
    status_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky="w")
    status_ac = AutoCompleteEntry(status_frame, width=20)
    status_ac.grid(row=0, column=1, sticky="ew")
    status_ac.set_loading(True)

    # ---------- Assigned To (optional) ----------
    assignee_frame = ttk.Frame(charger_window)
    assignee_frame.pack(fill="x", padx=10, pady=6)
    assignee_frame.grid_columnconfigure(0, weight=0)
    assignee_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(assignee_frame, text="Checkout To (optional):").grid(row=0, column=0, sticky="w")
    assignee_ac = AutoCompleteEntry(assignee_frame, width=20)
    assignee_ac.grid(row=0, column=1, sticky="ew")
    assignee_ac.set_loading(True)

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
        """Allow empty or float-like text for purchase cost.

        Args:
            P: Proposed new value of the entry widget.

        Returns:
            True if the value is acceptable, False otherwise.
        """
        if P == "":
            return True
        try:
            float(P)
            return True
        except ValueError:
            logger.debug("_validate_float: invalid float input: %s", P)
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
    date_frame, purchase_date_var, _purchase_date_entry = build_date_entry_frame(
        charger_window, "Purchase Date (YYYY-MM-DD):"
    )

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
    center_window(charger_window)

    # Ensure API user prompt (if needed) happens on the main thread.
    get_api_key()

    # Kick off async loads after showing window
    threading.Thread(target=_preload_options_thread, daemon=True).start()
    return f"Make Charger window opened for {asset_tag}."
