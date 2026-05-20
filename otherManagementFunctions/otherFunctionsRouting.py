"""Routing table for non-asset automation functions.

Defines callable functions and display labels for long-running scripts.
"""

# Handler for background script windows.
from otherManagementFunctions.scriptSplitOutHandler import handler

# Functions executed through the handler.
from otherManagementFunctions.jamfSync import run_snipe_to_jamf_sync
from otherManagementFunctions.batteryDataSync import run_jamf_battery_sync

# Functions executed without the handler.
from otherManagementFunctions.chargerLiveHistory import show_connected_charger_history
## example for handler since not currently used: lambda: handler(run_snipe_to_jamf_sync)


# Callable functions in display order (wrapped for log streaming).
other_func_list = [
    # Wrap each long-running script in the log window handler.
    run_snipe_to_jamf_sync,
    run_jamf_battery_sync,
    show_connected_charger_history,
]
# Display labels aligned with other_func_list.
other_func_listTXT = [
    "Sync Jamf Asset Tags",
    "Sync Snipe Battery Data",
    "Connected Charger Data"
]
