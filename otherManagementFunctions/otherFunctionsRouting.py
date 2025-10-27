# Handler
from otherManagementFunctions.scriptSplitOutHandler import handler

# Functions
from otherManagementFunctions.jamfSync import run_snipe_to_jamf_sync
from otherManagementFunctions.batteryDataSync import run_jamf_battery_sync




other_func_list = [
    lambda: handler(run_snipe_to_jamf_sync),
    lambda: handler(run_jamf_battery_sync)
]
other_func_listTXT = [
    "Sync Jamf Asset Tags",
    "Sync Snipe Battery Data"
]