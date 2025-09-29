# Handler
from otherManagementFunctions.scriptSplitOutHandler import handler

# Functions
from otherManagementFunctions.jamfSync import run_snipe_to_jamf_sync
from otherManagementFunctions.scriptSplitOutHandler import example_task




other_func_list = [
    lambda: handler(run_snipe_to_jamf_sync),
    lambda: handler(example_task)
]
other_func_listTXT = [
    "Sync Jamf Asset Tags",
    "test"
]