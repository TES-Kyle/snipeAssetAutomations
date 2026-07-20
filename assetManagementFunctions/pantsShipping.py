"""Pants shipping workflow for Snipe-IT assets."""

import logging
from tkinter import messagebox

from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings
from utilities.otherApiBits import *

logger = logging.getLogger(__name__)


def pantsShipping(asset_tag, *args):
    """Perform pants shipping workflow for an asset.

    Args:
        asset_tag: Asset tag to check in and update.
        *args: Unused extra arguments from UI.

    Returns:
        Status message string for the main UI.
    """
    configure_logging()
    logger.debug("pantsShipping: asset_tag=%s extra_args=%s", asset_tag, args)
    # Fetch asset info to build check-in/update payloads.
    logger.debug("pantsShipping: fetching asset info for %s", asset_tag)
    junk, genericValues = getAssetInfo(asset_tag)
    logger.debug("pantsShipping: asset fetched id=%s name=%s", genericValues.get("id"), genericValues.get("name"))

    putURL = Key.API_URL_Base + "hardware/" + str(genericValues["id"])
    logger.info("Pants shipping started for %s", asset_tag)
    logger.debug("Pants shipping URL: %s", putURL)
    # First payload: check-in with current status.
    payload1 = {
        "status_id": genericValues["status_label"]["id"]
    }
    settings = get_settings()
    try:
        # Allow the target status to be configured in settings.
        target_status_id = int(settings.get("pantsShippingStatusId", 9))
    except Exception:
        target_status_id = 9

    # Second payload: update status + model assignment.
    payload2 = {
        "asset_tag": asset_tag,
        "model_id": genericValues["model"]["id"],
        "status_id": target_status_id,
    }
    logger.debug("Pants shipping check-in payload for %s: %s", asset_tag, payload1)
    logger.debug(
        "Pants shipping update payload for %s (status_id=%s): %s",
        asset_tag,
        target_status_id,
        payload2,
    )
    # Step 1: check-in the asset.
    response = requests.post(putURL + "/checkin", json=payload1, headers=get_headers())
    if response.status_code >= 400:
        logger.error("Check-in failed for %s: %s", asset_tag, response.text)
        messagebox.showerror("Check-in Failed", f"Check-in failed for {asset_tag}.\n\n{response.text}")
        return f"Pants shipping failed for {asset_tag}: check-in failed."

    # Step 2: update status/model on the asset.
    response2 = requests.put(putURL, json=payload2, headers=get_headers())
    if response2.status_code >= 400:
        logger.error("Update failed for %s: %s", asset_tag, response2.text)
        messagebox.showerror("Update Failed", f"Update failed for {asset_tag}.\n\n{response2.text}")
        return f"Pants shipping failed for {asset_tag}: update failed."

    logger.info("Pants shipping update complete for %s", asset_tag)
    logger.debug("pantsShipping: refreshing asset data for %s after update", asset_tag)
    junk, genericValues = getAssetInfo(asset_tag)
    logger.debug("pantsShipping: refreshed asset status=%s", genericValues.get("status_label", {}).get("name"))

    return f"Pants shipping complete for {asset_tag}."
