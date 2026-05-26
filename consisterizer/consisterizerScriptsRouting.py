"""Routing table for Consisterizer submit scripts.

Defines optional scripts that can run after Consisterizer saves an asset.
"""

import logging

logger = logging.getLogger(__name__)

# Scripts to run on submit.
from assetManagementFunctions.jamfDeleteAndUnprestage import jamf_remove_prestage_and_delete

# Callable scripts in display order (must align with labels below).
submit_func_list = [
    jamf_remove_prestage_and_delete
]

logger.info("consisterizerScriptsRouting: %s submit scripts registered", len(submit_func_list))

# Display labels aligned with submit_func_list.
submit_func_listTXT = [
    "Remove PreStage and Delete in Jamf"
]
