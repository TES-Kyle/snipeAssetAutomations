"""Charger history lookup via Jamf Pro EA values."""

import logging
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk
from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider
from jamf_pro_sdk.clients.pro_api.pagination import SortField
from utilities.otherApiBits import getAssetInfoSerialAssignedTo, getAssetInfo
from utilities import Key
from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings

jamfURL = Key.jamfURL # No trailing slash

CHARGER_EA_NAME_DEFAULT = "chargerSerial"
CHARGER_PAGE_SIZE_DEFAULT = 700

logger = logging.getLogger(__name__)

def get_computer_inventory_results():
    """Fetch Jamf computer inventory records using the Jamf Pro SDK.

    Returns:
        List of Jamf computer inventory objects (may be empty on failure).
    """
    configure_logging()
    settings = get_settings()
    try:
        # Allow page size override via settings for large Jamf tenants.
        page_size = int(settings.get("chargerSerialPageSize", CHARGER_PAGE_SIZE_DEFAULT))
    except Exception:
        page_size = CHARGER_PAGE_SIZE_DEFAULT
    logger.debug("get_computer_inventory_results called, page_size=%s", page_size)

    # Build a Jamf client using OAuth credentials.
    jamfClient = JamfProClient(
        server=jamfURL,
        credentials=ApiClientCredentialsProvider(Key.jamfClientID, Key.jamfClientSecret),
        session_config=SessionConfig(timeout=30, max_retries=5, max_concurrency=25),
    )

    try:
        response = jamfClient.pro_api.get_computer_inventory_v1(
            sections=["HARDWARE"],
            page_size=page_size,
            sort_expression=SortField("general.name").asc(),
        )
    except Exception as e:
        logger.exception("Failed to fetch Jamf computer inventory")
        messagebox.showerror("Jamf Error", f"Failed to fetch computer inventory.\n\n{e}")
        return []

    # response is a list of Computer objects
    return response

def parse_charger_info(values_str):
    """Parse charger history values into (datetime, serial) tuples.

    Args:
        values_str: String containing charger history lines from Jamf EA.

    Returns:
        List of (datetime, charger_serial) tuples parsed from the input.
    """
    configure_logging()
    logger.debug("parse_charger_info: parsing %s chars of history", len(values_str or ""))
    entries = []
    lines = values_str.split('\n')
    logger.debug("parse_charger_info: processing %s lines", len(lines))
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Split into date/time parts and charger serial.
        parts = line.rsplit(maxsplit=1)
        if len(parts) != 2:
            logger.debug("parse_charger_info: skipping line with unexpected part count: %s", line[:50])
            continue
        date_part = parts[0]
        charger_serial = parts[1]

        tokens = date_part.split()
        # If we have 6 tokens, assume the 5th is a timezone and remove it.
        if len(tokens) == 6:
            logger.debug("parse_charger_info: stripping timezone token from %s", date_part)
            tokens.pop(4)

        # Zero-pad the day if needed to match the expected format.
        day = tokens[2]
        if len(day) == 1:
            day = f"0{day}"
            tokens[2] = day

        # Parse the normalized timestamp into a datetime.
        date_str = " ".join(tokens)
        logger.debug("parse_charger_info: parsing date_str=%s serial=%s", date_str, charger_serial)
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %Y")

        # Add the parsed entry for later sorting.
        entries.append((dt, charger_serial))
    logger.debug("parse_charger_info: parsed %s entries", len(entries))
    return entries

def build_charger_history(target_charger_serial, computers):
    """Scan Jamf computer inventory EA history for a charger serial match.

    Shared by chargerSerial() (resolves the target via a Snipe-IT asset tag
    lookup) and otherManagementFunctions.chargerLiveHistory (uses the
    locally-detected connected charger serial directly).

    Args:
        target_charger_serial: Charger serial number to search for.
        computers: Iterable of Jamf computer inventory objects.

    Returns:
        Multi-line string listing recent charger uses, or a not-found message.
    """
    if not target_charger_serial:
        return "No charger serial detected."

    settings = get_settings()
    # Use the configured EA name, with a safe default fallback.
    charger_ea_name = settings.get("chargerEaName", CHARGER_EA_NAME_DEFAULT).strip()
    if not charger_ea_name:
        charger_ea_name = CHARGER_EA_NAME_DEFAULT
    logger.debug("build_charger_history: using charger EA name: %s", charger_ea_name)

    charger_matches = []
    logger.debug("build_charger_history: scanning %s computers for charger matches", len(computers))
    for comp in computers:
        # Only consider records with a hardware section.
        hardware = getattr(comp, "hardware", None)
        if not hardware:
            continue
        comp_serial = hardware.serialNumber or "UNKNOWN"

        if hardware.extensionAttributes:
            for ea in hardware.extensionAttributes:
                # Match the EA that contains charger usage history.
                if ea.name == charger_ea_name:
                    values = ea.values or []
                    if not values:
                        continue
                    logger.debug("build_charger_history: found EA '%s' on comp_serial=%s with %s values", charger_ea_name, comp_serial, len(values))
                    # Parse all history entries and capture matches for this charger.
                    all_values_str = "\n".join(values)
                    entries = parse_charger_info(all_values_str)
                    for (dt, cserial) in entries:
                        if cserial == target_charger_serial:
                            logger.debug("build_charger_history: match found on comp_serial=%s at %s", comp_serial, dt)
                            assignedTo = getAssetInfoSerialAssignedTo(comp_serial)
                            charger_matches.append((dt, comp_serial, assignedTo))
    logger.info("build_charger_history: found %s charger matches for %s", len(charger_matches), target_charger_serial)

    # Sort by datetime descending to show most recent activity first.
    charger_matches.sort(key=lambda x: x[0], reverse=True)

    # Build a result string capped to the five most recent uses.
    result_str = f"5 Most Recent Uses of Charger {target_charger_serial}:\n\n"
    for dt, dev_serial, assigned in charger_matches[:5]:
        result_str += f"{dt} - Device Serial: {dev_serial} - Last Used By: {assigned}\n"

    if not charger_matches:
        result_str += "No recent uses found."

    return result_str


def chargerSerial(assetTag):
    """Retrieve and format the most recent uses of a charger.

    Args:
        assetTag: Asset tag of the charger to look up.

    Returns:
        Multi-line string listing recent charger uses or a not-found message.
    """
    configure_logging()
    # This function now returns the formatted result string instead of printing directly
    # Fetch Jamf inventory once to avoid repeated API calls.
    computers = get_computer_inventory_results()
    if not computers:
        return "No Jamf inventory results available."
    # Resolve the target charger serial from Snipe-IT.
    _, assetInfo = getAssetInfo(assetTag)
    TARGET_CHARGER_SERIAL = assetInfo["serial"]
    logger.info("Checking charger history for asset %s (serial=%s)", assetTag, TARGET_CHARGER_SERIAL)
    return build_charger_history(TARGET_CHARGER_SERIAL, computers)

def show_charger_results_tk(assetTag):
    """Display charger usage results in a new Tkinter window.

    Args:
        assetTag: The asset tag for which to fetch and display charger usage results.
    """
    configure_logging()
    logger.debug("show_charger_results_tk: assetTag=%s", assetTag)
    # Create a new window (Toplevel) so it doesn't block the main window
    logger.debug("show_charger_results_tk: creating Toplevel window")
    top = tk.Toplevel()
    top.title("Charger Usage Results")

    # Get the charger usage info
    logger.info("show_charger_results_tk: fetching charger results for %s", assetTag)
    results = chargerSerial(assetTag)
    logger.debug("show_charger_results_tk: results length=%s", len(results))

    # Use a Text widget to display results.
    text_widget = tk.Text(top, wrap="word", width=80, height=20)
    text_widget.insert("1.0", results)
    text_widget.config(state="disabled")  # make read-only
    text_widget.pack(padx=10, pady=10)
    logger.debug("show_charger_results_tk: results displayed in text widget")

    # Add a close button for explicit dismissal.
    close_button = ttk.Button(top, text="Close", command=top.destroy)
    close_button.pack(pady=5)

    # The user can also close the window using the window's close button

# Example usage:
# Suppose this is triggered by another tkinter window passing an assetTag:
# show_charger_results_tk("6245")
