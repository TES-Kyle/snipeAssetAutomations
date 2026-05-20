
import json
import os

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
            return json.load(fh)
    except Exception:
        return {}


def _load_settings() -> dict:
    """Load settings.json over defaults, returning a merged dict.

    Returns:
        Merged settings dict with defaults overridden by settings.json.
    """
    # Start with defaults, then override with settings.json.
    settings = {}
    settings.update(_safe_read_json(DEFAULTS_PATH))
    settings.update(_safe_read_json(SETTINGS_PATH))
    return settings


def get_settings() -> dict:
    """Return merged settings.json/defaultSettings.json for callers.

    Returns:
        Combined settings dict (settings.json overrides defaults).
    """
    return _load_settings()
