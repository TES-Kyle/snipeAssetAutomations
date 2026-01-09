"""Print label workflow for selected asset data."""

import logging

from utilities.logging_utils import configure_logging
from utilities.otherApiBits import *
from utilities.labelPrinting import createImage

logger = logging.getLogger(__name__)


def printSelected(asset_tag, *args):
    """Print a label using provided values or fall back to asset defaults.

    Args:
        asset_tag: Asset tag for lookup when no print data is provided.
        *args: Optional list of values to print on the label.

    Returns:
        Status message string for the main UI.
    """
    configure_logging()
    if args:
        # Use the provided print payload when custom fields are supplied.
        printVar = args[0]
        logger.debug("Print selected args for %s: %s", asset_tag, args)
        createImage(printVar)
        return f"Label printed for {asset_tag} (custom fields)."
    else:
        # Fall back to asset lookup and print the asset tag only.
        logger.debug("No print args provided for %s; using asset tag only", asset_tag)
        junk, genericValues = getAssetInfo(asset_tag)
        # Build the single-line label payload for the printer.
        printData = list()
        printData.append(genericValues["asset_tag"])
        createImage(printData)
        return f"Label printed for {asset_tag} (asset tag only)."
