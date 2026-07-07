"""Shared asset-tag validation.

Asset tags are validated against a configurable regex (settings key
assetTagRegex), falling back to a safe default if the setting is missing
or the configured pattern doesn't compile.
"""

import logging
import re

from utilities.settings import get_settings

logger = logging.getLogger(__name__)

ASSET_TAG_RE_DEFAULT = re.compile(r"^\d{4,5}$")


def valid_asset_tag(value: str, settings: dict = None) -> bool:
    """Validate an asset tag string against the configured regex.

    Args:
        value: Asset tag string to validate.
        settings: Optional pre-loaded settings dict, to avoid a redundant
            get_settings() call when the caller already has one loaded.
            Falls back to get_settings() when omitted.

    Returns:
        True if the tag matches the configured regex, False otherwise.
    """
    logger.debug("valid_asset_tag: value=%s", value)
    if settings is None:
        settings = get_settings()
    pattern = settings.get("assetTagRegex", r"^\d{4,5}$")
    logger.debug("valid_asset_tag: pattern=%s", pattern)
    try:
        regex = re.compile(pattern)
    except re.error:
        logger.error("Invalid assetTagRegex setting: %s", pattern)
        regex = ASSET_TAG_RE_DEFAULT
    result = bool(regex.match(value or ""))
    logger.debug("valid_asset_tag: value=%s result=%s", value, result)
    return result
