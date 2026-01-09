"""Routing table for Consisterizer submit scripts.

Defines optional scripts that can run after Consisterizer saves an asset.
"""

# Handler

# Scripts to run on submit.
from assetManagementFunctions.jamfDeleteAndPreStage import jamf_remove_prestage_and_delete

# Callable scripts in display order (must align with labels below).
submit_func_list = [
    jamf_remove_prestage_and_delete
]

# Display labels aligned with submit_func_list.
submit_func_listTXT = [
    "Remove PreStage and Delete in Jamf"
]
