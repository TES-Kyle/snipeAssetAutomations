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
    logger.debug("_get_charger_serial_number: platform=%s", platform.system())
    if platform.system() != "Darwin":
        logger.debug("_get_charger_serial_number: non-Darwin platform, raising OSError")
        raise OSError("Unsupported operating system")
    logger.debug("_get_charger_serial_number: running system_profiler command")
    try:
        result = subprocess.run(
            "system_profiler SPPowerDataType | awk '/AC Charger Information:/,/Charging/' | grep 'Serial Number'",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        serial = (result.stdout.strip().split(": ", 1)[-1] or "").strip()
        logger.debug("_get_charger_serial_number: detected serial=%s", serial)
        return serial
    except Exception:
        logger.debug("_get_charger_serial_number: subprocess failed, returning empty string")
        return ""


def _build_history(charger_serial: str, computers) -> str:
    """Build a history string for the connected charger serial.

    Args:
        charger_serial: The serial number of the connected charger.
        computers: Iterable of computer inventory objects from Jamf.

    Returns:
        A formatted multi-line string listing recent charger uses.
    """
    logger.debug("_build_history: serial=%s, computer_count=%s", charger_serial, len(computers) if computers else 0)
    if not charger_serial:
        logger.debug("_build_history: no charger serial, returning default message")
        return "No charger serial detected."

    settings = get_settings()
    charger_ea_name = settings.get("chargerEaName", CHARGER_EA_NAME_DEFAULT).strip()
    logger.debug("_build_history: using ea_name=%s", charger_ea_name)
    if not charger_ea_name:
        charger_ea_name = CHARGER_EA_NAME_DEFAULT
        logger.debug("_build_history: ea_name was empty, falling back to default=%s", charger_ea_name)

    matches = []
    for comp in computers:
        hardware = getattr(comp, "hardware", None)
        if not hardware:
            logger.debug("_build_history: skipping computer with no hardware attribute")
            continue
        comp_serial = hardware.serialNumber or "UNKNOWN"
        logger.debug("_build_history: scanning computer serial=%s", comp_serial)
        if hardware.extensionAttributes:
            for ea in hardware.extensionAttributes:
                if ea.name == charger_ea_name:
                    logger.debug("_build_history: found matching EA on computer=%s", comp_serial)
                    values = ea.values or []
                    if not values:
                        logger.debug("_build_history: EA has no values for computer=%s", comp_serial)
                        continue
                    all_values_str = "\n".join(values)
                    entries = parse_charger_info(all_values_str)
                    logger.debug("_build_history: parsed %s charger entries for computer=%s", len(entries), comp_serial)
                    for dt, cserial in entries:
                        if cserial == charger_serial:
                            logger.info("_build_history: charger match found on computer=%s at %s", comp_serial, dt)
                            assigned_to = getAssetInfoSerialAssignedTo(comp_serial)
                            logger.debug("_build_history: assigned_to=%s for computer=%s", assigned_to, comp_serial)
                            matches.append((dt, comp_serial, assigned_to))

    matches.sort(key=lambda x: x[0], reverse=True)
    logger.debug("_build_history: total matches=%s, showing top 5", len(matches))

    result = f"5 Most Recent Uses of Charger {charger_serial}:\n\n"
    for dt, dev_serial, assigned in matches[:5]:
        result += f"{dt} - Device Serial: {dev_serial} - Last Used By: {assigned}\n"
    if not matches:
        logger.debug("_build_history: no matches found for serial=%s", charger_serial)
        result += "No recent uses found."
    return result


def show_connected_charger_history():
    """Open a window showing connected charger serial and history."""
    logger.debug("show_connected_charger_history: starting")
    configure_logging()

    logger.debug("show_connected_charger_history: detecting charger serial")
    try:
        serial_var = tk.StringVar(value=_get_charger_serial_number())
    except OSError:
        logger.error("show_connected_charger_history: unsupported OS, aborting")
        messagebox.showerror("Charger History", "Unsupported Operating System")
        return "Charger history failed due to unsupported OS"

    logger.info("show_connected_charger_history: opening window, serial=%s", serial_var.get())
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
        """Replace the history text box contents.

        Args:
            text: The text to display in the history area.
        """
        logger.debug("_set_history: updating history text, length=%s", len(text))
        history_text.config(state="normal")
        history_text.delete("1.0", tk.END)
        history_text.insert("1.0", text)
        history_text.config(state="disabled")

    def _refresh_history(serial: str):
        """Fetch and display history for the given serial in background.

        Args:
            serial: The charger serial number to look up history for.
        """
        logger.debug("_refresh_history: serial=%s", serial)
        if not serial:
            logger.debug("_refresh_history: no serial, showing default message")
            charger_window.after(0, lambda: _set_history("No charger serial detected."))
            return
        # Ensure API prompt (if needed) happens on the UI thread.
        logger.debug("_refresh_history: ensuring API key is available")
        get_api_key()

        def worker(target_serial: str):
            """Background thread that fetches Jamf inventory and builds charger history.

            Args:
                target_serial: The charger serial to build history for.
            """
            logger.debug("worker: starting background history fetch for serial=%s", target_serial)
            configure_logging()
            status_var.set("Loading charger history...")
            logger.info("worker: fetching Jamf computer inventory for charger serial=%s", target_serial)
            try:
                computers = get_computer_inventory_results()
            except Exception as exc:
                logger.exception("worker: failed to load Jamf inventory")
                charger_window.after(0, lambda: _set_history(f"Failed to load Jamf inventory:\n{exc}"))
                status_var.set("")
                return

            logger.debug("worker: building history for serial=%s", target_serial)
            history = _build_history(target_serial, computers)

            def apply():
                """Apply fetched history to the UI if serial is still current."""
                current_serial = serial_var.get().strip()
                logger.debug("apply: checking serial match current=%s target=%s", current_serial, target_serial)
                if current_serial != target_serial:
                    logger.debug("apply: serial changed since fetch, skipping update")
                    return
                logger.debug("apply: updating UI with history result")
                _set_history(history)
                status_var.set("")

            charger_window.after(0, apply)

        logger.debug("_refresh_history: spawning worker thread for serial=%s", serial)
        threading.Thread(target=worker, args=(serial,), daemon=True).start()

    def _poll_serial():
        """Poll the charger serial periodically and refresh history on change."""
        logger.debug("_poll_serial: background polling thread started")
        while True:
            try:
                current = _get_charger_serial_number()
            except Exception:
                logger.debug("_poll_serial: exception reading serial, using empty string")
                current = ""
            with history_lock:
                if current != last_serial["value"]:
                    logger.info("_poll_serial: charger serial changed from %s to %s", last_serial["value"], current)
                    last_serial["value"] = current
                    charger_window.after(0, lambda s=current: serial_var.set(s))
                    charger_window.after(0, lambda s=current: _refresh_history(s))
            time.sleep(0.5)

    # Ensure API prompt happens on main thread if needed.
    logger.debug("show_connected_charger_history: ensuring API key on main thread")
    get_api_key()

    # Initialize history for the current serial.
    last_serial["value"] = serial_var.get().strip()
    logger.info("show_connected_charger_history: loading initial history for serial=%s", last_serial["value"])
    _refresh_history(last_serial["value"])

    # Start background serial polling.
    logger.debug("show_connected_charger_history: starting serial poll thread")
    threading.Thread(target=_poll_serial, daemon=True).start()

    logger.info("show_connected_charger_history: window opened successfully")
    return "Connected charger history window opened."


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    show_connected_charger_history()
    root.mainloop()
