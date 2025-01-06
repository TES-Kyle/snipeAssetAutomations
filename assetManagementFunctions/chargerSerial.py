import os
import json
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider
from jamf_pro_sdk.clients.pro_api.pagination import FilterField, SortField
from Utilities.otherApiBits import getAssetInfoSerialAssignedTo, getAssetInfo
from Utilities import Key

JAMF_URL = "https://trinityes.jamfcloud.com"  # No trailing slash
jamfURL = "trinityes.jamfcloud.com"

CHARGER_EA_NAME = "chargerSerial"

def get_computer_inventory_results():
    """
    Fetches a set of computer inventory records from Jamf Pro using the Jamf Pro SDK.
    """
    jamfClient = JamfProClient(
        server=jamfURL,
        credentials=ApiClientCredentialsProvider(Key.jamfClientID, Key.jamfClientSecret),
        session_config=SessionConfig(timeout=30, max_retries=5, max_concurrency=25),
    )

    response = jamfClient.pro_api.get_computer_inventory_v1(
        sections=["HARDWARE"],
        page_size=700,  # Adjust as needed
        sort_expression=SortField("general.name").asc()
    )
    # response is a list of Computer objects
    return response

def parse_charger_info(values_str):
    """
    Parses a string containing charger information and returns a list of tuples with datetime objects and charger serial numbers.
    Args:
        values_str (str): A string containing charger information with each entry on a new line. Each line should contain a date/time string followed by a charger serial number.
    Returns:
        list of tuples: A list where each tuple contains a datetime object and a charger serial number.
    Example:
        Input:
            "Mon Jan 1 12:34:56 2023 ABC123\nTue Feb 2 23:45:01 2023 XYZ789"
        Output:
            [(datetime.datetime(2023, 1, 1, 12, 34, 56), 'ABC123'), 
             (datetime.datetime(2023, 2, 2, 23, 45, 1), 'XYZ789')]
    """
    entries = []
    lines = values_str.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Split into date/time parts and charger serial
        parts = line.rsplit(maxsplit=1)
        if len(parts) != 2:
            continue
        date_part = parts[0]
        charger_serial = parts[1]

        tokens = date_part.split()
        # If we have 6 tokens, assume the 5th is a timezone and remove it
        if len(tokens) == 6:
            tokens.pop(4)

        # Zero-pad the day if needed
        day = tokens[2]
        if len(day) == 1:
            day = f"0{day}"
            tokens[2] = day

        date_str = " ".join(tokens)
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %Y")

        entries.append((dt, charger_serial))
    return entries

def chargerSerial(assetTag):
    """
    Retrieves and formats the 5 most recent uses of a charger based on the given asset tag.
    Args:
        assetTag (str): The asset tag of the charger to look up.
    Returns:
        str: A formatted string listing the 5 most recent uses of the charger, including the date/time,
             device serial number, and the user assigned to the device. If no recent uses are found,
             a message indicating this is included in the result.
    """
    # This function now returns the formatted result string instead of printing directly
    computers = get_computer_inventory_results()
    _, assetInfo = getAssetInfo(assetTag)
    TARGET_CHARGER_SERIAL = assetInfo["serial"]

    charger_matches = []
    for comp in computers:
        hardware = comp.hardware
        if not hardware:
            continue
        comp_serial = hardware.serialNumber or "UNKNOWN"
        
        if hardware.extensionAttributes:
            for ea in hardware.extensionAttributes:
                if ea.name == CHARGER_EA_NAME:
                    values = ea.values or []
                    if not values:
                        continue
                    all_values_str = "\n".join(values)
                    entries = parse_charger_info(all_values_str)
                    for (dt, cserial) in entries:
                        if cserial == TARGET_CHARGER_SERIAL:
                            assignedTo = getAssetInfoSerialAssignedTo(comp_serial)
                            charger_matches.append((dt, comp_serial, assignedTo))

    # Sort by datetime descending
    charger_matches.sort(key=lambda x: x[0], reverse=True)

    # Build a result string
    result_str = f"5 Most Recent Uses of Charger {TARGET_CHARGER_SERIAL}:\n\n"
    for dt, dev_serial, assigned in charger_matches[:5]:
        result_str += f"{dt} - Device Serial: {dev_serial} - Last Used By: {assigned}\n"

    if not charger_matches:
        result_str += "No recent uses found."

    return result_str

def show_charger_results_tk(assetTag):
    """
    Display charger usage results in a new Tkinter window.
    This function creates a new Toplevel window to display the charger usage
    results for a given asset tag. The results are fetched using the 
    `chargerSerial` function and displayed in a read-only Text widget. 
    A close button is also provided to close the window.
    Parameters:
    assetTag (str): The asset tag for which to fetch and display charger usage results.
    Returns:
    None
    """
    # Create a new window (Toplevel) so it doesn't block the main window
    top = tk.Toplevel()
    top.title("Charger Usage Results")

    # Get the charger usage info
    results = chargerSerial(assetTag)

    # Use a Text widget to display results
    text_widget = tk.Text(top, wrap="word", width=80, height=20)
    text_widget.insert("1.0", results)
    text_widget.config(state="disabled")  # make read-only
    text_widget.pack(padx=10, pady=10)

    # Optionally add a close button
    close_button = ttk.Button(top, text="Close", command=top.destroy)
    close_button.pack(pady=5)

    # The user can also close the window using the window's close button

# Example usage:
# Suppose this is triggered by another tkinter window passing an assetTag:
# show_charger_results_tk("6245")
