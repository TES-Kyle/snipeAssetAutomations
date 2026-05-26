"""Settings loader for the Asset Automations application.

Merges settings.json over defaultSettings.json and returns the combined dict.
All modules should call get_settings() rather than reading JSON directly.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

UTILITIES_DIR = os.path.dirname(os.path.realpath(__file__))
SETTINGS_PATH = os.path.join(UTILITIES_DIR, "settings.json")
DEFAULTS_PATH = os.path.join(UTILITIES_DIR, "defaultSettings.json")


def _safe_read_json(path: str) -> dict:
    """Read a JSON file and return a dict, or {} on failure.

    Args:
        path: JSON file path to read.

    Returns:
        Parsed dict or empty dict when read/parse fails.
    """
    try:
        # Read JSON from disk; return empty dict on any error.
        with open(path, "r") as fh:
            data = json.load(fh)
        logger.debug("Loaded JSON from %s (%s keys)", path, len(data))
        return data
    except Exception as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return {}


def _load_settings() -> dict:
    """Load settings.json over defaults, returning a merged dict.

    Returns:
        Merged settings dict with defaults overridden by settings.json.
    """
    # Start with defaults, then override with settings.json values.
    settings = {}
    settings.update(_safe_read_json(DEFAULTS_PATH))
    settings.update(_safe_read_json(SETTINGS_PATH))
    logger.debug("Settings merged: %s keys total", len(settings))
    return settings


def get_settings() -> dict:
    """Return merged settings.json/defaultSettings.json for callers.

    Returns:
        Combined settings dict (settings.json overrides defaults).
    """
    logger.debug("get_settings: loading merged settings")
    settings = _load_settings()
    logger.debug("get_settings: returning %s keys", len(settings))
    return settings
