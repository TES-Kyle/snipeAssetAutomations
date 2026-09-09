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


def _should_drop_key(key, value, defaults: dict) -> bool:
    """Return True if key should be omitted from settings.json rather than written.

    Two cases:
    - value matches key's entry in defaults (defaultSettings.json) -- no
      need to pin today's value when it's already the default.
    - key has no entry in defaults at all (a leftover/orphaned setting from
      a removed or renamed feature) and value is blank -- nothing meaningful
      to preserve, so it's dropped instead of living forever. A non-blank
      orphaned key is always kept, since there's no default to fall back to
      and dropping it would lose its value outright.
    """
    if key in defaults:
        return str(value) == str(defaults[key])
    return str(value) == ""


def _write_settings_file(data: dict) -> bool:
    """Atomically replace settings.json's contents with data.

    Writes to a temp file followed by os.replace() so a crash mid-write
    can't corrupt the settings.json the app reads on every launch.

    Args:
        data: Complete dict to persist (already prepared by the caller).

    Returns:
        True on success, False if the write failed (logged, not raised).
    """
    tmp_path = SETTINGS_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp_path, SETTINGS_PATH)
        logger.info("_write_settings_file: wrote %s keys to %s", len(data), SETTINGS_PATH)
        return True
    except Exception as exc:
        logger.exception("_write_settings_file: failed to write %s: %s", SETTINGS_PATH, exc)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def update_settings(updates: dict) -> bool:
    """Merge `updates` into settings.json and write it back atomically.

    Reads the current settings.json only (not the merged defaults+overrides
    view from get_settings()), applies `updates` on top, and writes the
    result. Any key in `updates` whose value matches its defaultSettings.json
    entry is dropped from settings.json instead of written -- so a setting
    that's set back to (or left at) default keeps tracking future changes to
    that default, rather than getting permanently pinned to today's value.
    Pre-existing keys not part of this call are left untouched either way.

    Args:
        updates: Dict of key/value pairs to merge into settings.json.

    Returns:
        True on success, False if the write failed (logged, not raised).
    """
    logger.debug("update_settings: merging %s keys into settings.json", len(updates))
    current = safe_read_json(SETTINGS_PATH)
    defaults = safe_read_json(DEFAULTS_PATH)
    for key, value in updates.items():
        if _should_drop_key(key, value, defaults):
            current.pop(key, None)
        else:
            current[key] = value
    return _write_settings_file(current)


def set_setting(key, value) -> bool:
    """Set a single settings.json key, leaving all others untouched.

    Args:
        key: Settings key to set.
        value: Value to store for that key.

    Returns:
        True on success, False if the write failed.
    """
    return update_settings({key: value})


def replace_settings(values: dict) -> bool:
    """Replace settings.json wholesale with values, dropping keys that don't need saving.

    Unlike update_settings() (an incremental merge), this replaces the whole
    file -- for a caller like the Settings window that always submits its
    complete currently-displayed state rather than a partial change. See
    _should_drop_key() for exactly which keys get omitted: default-equal
    keys, plus blank orphaned keys (no schema/default entry at all) -- so
    resetting the whole "Other" group to blank and hitting Apply is enough
    to clean out dead/leftover settings, without touching anything with a
    real value.

    Args:
        values: Complete dict of key/value pairs representing the desired
            settings state.

    Returns:
        True on success, False if the write failed.
    """
    defaults = safe_read_json(DEFAULTS_PATH)
    pruned = {k: v for k, v in values.items() if not _should_drop_key(k, v, defaults)}
    logger.info("replace_settings: %s of %s keys kept (others matched default or were blank/orphaned)", len(pruned), len(values))
    return _write_settings_file(pruned)
