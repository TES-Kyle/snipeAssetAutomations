"""Show connected charger serial and recent usage history."""

import logging
import os
import platform
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

# Allow running as a standalone script by ensuring repo root is on sys.path.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from assetManagementFunctions.chargerSerial import get_computer_inventory_results, parse_charger_info
from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings
from utilities.otherApiBits import getAssetInfoSerialAssignedTo
from utilities.api_user import get_api_key

logger = logging.getLogger(__name__)

CHARGER_EA_NAME_DEFAULT = "chargerSerial"


def _get_charger_serial_number():
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
        return (result.stdout.strip().split(": ", 1)[-1] or "").strip()
    except Exception:
        return ""


def _build_history(charger_serial: str, computers) -> str:
    """Build a history string for the connected charger serial."""
    if not charger_serial:
        return "No charger serial detected."

    settings = get_settings()
    charger_ea_name = settings.get("chargerEaName", CHARGER_EA_NAME_DEFAULT).strip()
    if not charger_ea_name:
        charger_ea_name = CHARGER_EA_NAME_DEFAULT

    matches = []
    for comp in computers:
        hardware = getattr(comp, "hardware", None)
        if not hardware:
            continue
        comp_serial = hardware.serialNumber or "UNKNOWN"
        if hardware.extensionAttributes:
            for ea in hardware.extensionAttributes:
                if ea.name == charger_ea_name:
                    values = ea.values or []
                    if not values:
                        continue
                    all_values_str = "\n".join(values)
                    entries = parse_charger_info(all_values_str)
                    for dt, cserial in entries:
                        if cserial == charger_serial:
                            assigned_to = getAssetInfoSerialAssignedTo(comp_serial)
                            matches.append((dt, comp_serial, assigned_to))

    matches.sort(key=lambda x: x[0], reverse=True)

    result = f"5 Most Recent Uses of Charger {charger_serial}:\n\n"
    for dt, dev_serial, assigned in matches[:5]:
        result += f"{dt} - Device Serial: {dev_serial} - Last Used By: {assigned}\n"
    if not matches:
        result += "No recent uses found."
    return result


def show_connected_charger_history():
    """Open a window showing connected charger serial and history."""
    configure_logging()

    try:
        serial_var = tk.StringVar(value=_get_charger_serial_number())
    except OSError:
        messagebox.showerror("Charger History", "Unsupported Operating System")
        return "Charger history failed due to unsupported OS"

    charger_window = tk.Toplevel()
    charger_window.title("Connected Charger History")

    # Serial row (copyable).
    serial_frame = ttk.Frame(charger_window)
    serial_frame.pack(fill="x", padx=10, pady=6)
    serial_frame.grid_columnconfigure(0, weight=0)
    serial_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(serial_frame, text="Connected Charger Serial:").grid(row=0, column=0, sticky="w")
    serial_entry = ttk.Entry(serial_frame, textvariable=serial_var, state="readonly")
    serial_entry.grid(row=0, column=1, sticky="ew")

    # History output.
    history_frame = ttk.Frame(charger_window)
    history_frame.pack(fill="both", expand=True, padx=10, pady=6)
    history_text = tk.Text(history_frame, wrap="word", width=90, height=18)
    history_text.pack(fill="both", expand=True)

    status_var = tk.StringVar(value="")
    ttk.Label(charger_window, textvariable=status_var).pack(anchor="w", padx=10, pady=(0, 8))

    last_serial = {"value": None}
    history_lock = threading.Lock()

    def _set_history(text: str):
        """Replace the history text box contents."""
        history_text.config(state="normal")
        history_text.delete("1.0", tk.END)
        history_text.insert("1.0", text)
        history_text.config(state="disabled")

    def _refresh_history(serial: str):
        """Fetch and display history for the given serial in background."""
        if not serial:
            charger_window.after(0, lambda: _set_history("No charger serial detected."))
            return
        # Ensure API prompt (if needed) happens on the UI thread.
        get_api_key()

        def worker(target_serial: str):
            configure_logging()
            status_var.set("Loading charger history...")
            try:
                computers = get_computer_inventory_results()
            except Exception as exc:
                logger.exception("Failed to load Jamf inventory")
                charger_window.after(0, lambda: _set_history(f"Failed to load Jamf inventory:\n{exc}"))
                status_var.set("")
                return

            history = _build_history(target_serial, computers)

            def apply():
                if serial_var.get().strip() != target_serial:
                    return
                _set_history(history)
                status_var.set("")

            charger_window.after(0, apply)

        threading.Thread(target=worker, args=(serial,), daemon=True).start()

    def _poll_serial():
        """Poll the charger serial periodically and refresh history on change."""
        while True:
            try:
                current = _get_charger_serial_number()
            except Exception:
                current = ""
            with history_lock:
                if current != last_serial["value"]:
                    last_serial["value"] = current
                    charger_window.after(0, lambda s=current: serial_var.set(s))
                    charger_window.after(0, lambda s=current: _refresh_history(s))
            time.sleep(0.5)

    # Ensure API prompt happens on main thread if needed.
    get_api_key()

    # Initialize history for the current serial.
    last_serial["value"] = serial_var.get().strip()
    _refresh_history(last_serial["value"])

    # Start background serial polling.
    threading.Thread(target=_poll_serial, daemon=True).start()

    return "Connected charger history window opened."


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    show_connected_charger_history()
    root.mainloop()
