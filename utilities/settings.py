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


def safe_read_json(path: str) -> dict:
    """Read a JSON file and return a dict, or {} on failure.

    Shared by other utilities modules that need a best-effort JSON read
    without duplicating this try/except.

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
    settings.update(safe_read_json(DEFAULTS_PATH))
    settings.update(safe_read_json(SETTINGS_PATH))
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


def update_settings(updates: dict) -> bool:
    """Merge `updates` into settings.json and write it back atomically.

    Reads the current settings.json only (not the merged defaults+overrides
    view from get_settings()), applies `updates` on top, and writes the
    result to a temp file followed by os.replace() so a crash mid-write
    can't corrupt the settings.json the app reads on every launch. Writing
    only settings.json (not the merged view) keeps default values out of
    the user's override file.

    Args:
        updates: Dict of key/value pairs to merge into settings.json.

    Returns:
        True on success, False if the write failed (logged, not raised).
    """
    logger.debug("update_settings: merging %s keys into settings.json", len(updates))
    current = safe_read_json(SETTINGS_PATH)
    current.update(updates)
    tmp_path = SETTINGS_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as fh:
            json.dump(current, fh)
        os.replace(tmp_path, SETTINGS_PATH)
        logger.info("update_settings: wrote %s keys to %s", len(current), SETTINGS_PATH)
        return True
    except Exception as exc:
        logger.exception("update_settings: failed to write %s: %s", SETTINGS_PATH, exc)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def set_setting(key, value) -> bool:
    """Set a single settings.json key, leaving all others untouched.

    Args:
        key: Settings key to set.
        value: Value to store for that key.

    Returns:
        True on success, False if the write failed.
    """
    return update_settings({key: value})
