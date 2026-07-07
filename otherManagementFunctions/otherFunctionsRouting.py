"""Routing table for non-asset automation functions.

Defines callable functions and display labels for long-running scripts.
"""

import logging

logger = logging.getLogger(__name__)

# Handler for background script windows.
# from utilities.scriptRunner import handler ## Not currently used

## example for handler since not currently used: lambda: handler(run_snipe_to_jamf_sync)


# Functions executed without the handler.
from otherManagementFunctions.chargerLiveHistory import show_connected_charger_history
from utilities.windmill import run_windmill_job


# Callable functions in display order (wrapped for log streaming).
other_func_list = [
    # Wrap each long-running script in the log window handler.
    lambda: run_windmill_job("https://app.windmill.dev/api/w/trinity-it-dept-test-space/jobs/run/f/u/john/asset_tag_sync"),
    lambda: run_windmill_job("https://app.windmill.dev/api/w/trinity-it-dept-test-space/jobs/run/f/u/john/sync_battery_data_from_jamf_to_snipe_it"),
    show_connected_charger_history,
]
logger.info("otherFunctionsRouting: %s functions registered", len(other_func_list))

# Display labels aligned with other_func_list.
other_func_listTXT = [
    "Sync Jamf Asset Tags",
    "Sync Snipe Battery Data",
    "Connected Charger Data"
]
