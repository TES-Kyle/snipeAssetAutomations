"""API user selection helpers for Snipe-IT requests.

This module centralizes API key selection so Snipe-IT changes can be
attributed to individual users while still supporting a single fallback key.
It supports:
  - a static user selection (always use a named key)
  - a prompt-based selection (cache the chosen user for N minutes)
  - a legacy single API_Key fallback for compatibility
"""

from __future__ import annotations

import json
import logging
import os
import time
from tkinter import messagebox, simpledialog

from utilities import Key
from utilities.logging_utils import configure_logging, get_settings

logger = logging.getLogger(__name__)

_cached_name = None
_cached_until = 0.0

_FALLBACK_NAMES = {"", "none", "null", "auto", "prompt", "dynamic"}


def _clean_name(value) -> str:
    """Normalize a name or token to a stripped string.

    Args:
        value: Incoming value that may be None or non-string.

    Returns:
        Cleaned string representation (always safe to compare).
    """
    return str(value or "").strip()


def _load_key_map() -> dict:
    """Load API_KEYS from utilities.Key and normalize entries.

    Returns:
        Dict of {display_name: api_key} with empty values removed.
    """
    raw = getattr(Key, "API_KEYS", None)
    if not isinstance(raw, dict):
        return {}
    key_map = {}
    for name, token in raw.items():
        # Normalize both names and tokens to avoid whitespace mismatches.
        name_clean = _clean_name(name)
        token_clean = _clean_name(token)
        if name_clean and token_clean:
            key_map[name_clean] = token_clean
    return key_map


def _lookup_key_case_insensitive(name: str, key_map: dict) -> tuple[str | None, str | None]:
    """Return a canonical key name and token using case-insensitive matching.

    Args:
        name: User-provided name to match.
        key_map: Mapping of display names to API keys.

    Returns:
        (canonical_name, token) tuple, or (None, None) when no match exists.
    """
    if not name:
        return None, None
    if name in key_map:
        return name, key_map.get(name)
    name_lower = name.lower()
    for key, token in key_map.items():
        if key.lower() == name_lower:
            return key, token
    return None, None


def _get_default_key() -> str:
    """Return the legacy API_Key value as a normalized string.

    Returns:
        API_Key string or empty string if not configured.
    """
    return _clean_name(getattr(Key, "API_Key", ""))


def _get_timeout_seconds(settings: dict) -> float:
    """Convert apiUserTimeoutMinutes to seconds, clamped to non-negative.

    Args:
        settings: Settings dictionary from logging_utils.get_settings().

    Returns:
        Timeout in seconds (float), never negative.
    """
    raw = settings.get("apiUserTimeoutMinutes", "5")
    try:
        minutes = float(raw)
    except Exception:
        minutes = 5.0
    if minutes < 0:
        minutes = 0.0
    return minutes * 60.0


def _is_static_name(name: str) -> bool:
    """Return True if the name is a valid static user selection.

    Args:
        name: Candidate static user name.

    Returns:
        True when the name is non-empty and not a fallback sentinel.
    """
    return bool(name) and name.lower() not in _FALLBACK_NAMES


def _prompt_for_user_name(key_map: dict, settings: dict) -> str | None:
    """Prompt for a user name, optionally showing available entries.

    Args:
        key_map: Normalized mapping of user names to API keys.
        settings: Settings dictionary with prompt text overrides.

    Returns:
        User-entered string or None if the dialog is canceled.
    """
    title = _clean_name(settings.get("apiUserPromptTitle")) or "API User"
    message = _clean_name(settings.get("apiUserPromptMessage")) or "Enter API user name."

    if key_map:
        names = sorted(key_map.keys(), key=str.lower)
        preview_limit = 12
        preview = ", ".join(names[:preview_limit])
        if len(names) > preview_limit:
            preview += "..."
        if preview:
            message = f"{message}\n\nAvailable: {preview}"

    return simpledialog.askstring(title, message)


def get_api_key() -> str:
    """Return the active API key using settings and optional prompt.

    Selection order:
      1) Static user name (apiUserStaticName) if configured and present in API_KEYS.
      2) Cached prompt selection if still valid.
      3) Prompt the user and cache the selection for apiUserTimeoutMinutes.
      4) Fallback to legacy API_Key if available.

    Returns:
        API key string or empty string if none is available.
    """
    configure_logging()
    # Load settings and key sources once per call.
    settings = get_settings()
    key_map = _load_key_map()
    default_key = _get_default_key()

    # Prefer a static selection if it is configured.
    static_name = _clean_name(settings.get("apiUserStaticName"))
    if _is_static_name(static_name):
        # Allow case-insensitive matching for static selections.
        canon_name, token = _lookup_key_case_insensitive(static_name, key_map)
        if token:
            logger.debug("Using static API user: %s", canon_name)
            return token
        if default_key:
            logger.warning("Static API user %s not found; using API_Key fallback", static_name)
            return default_key
        messagebox.showerror("API User", f"API key not found for user '{static_name}'.")
        return ""

    # With no API_KEYS map, fall back to the legacy single key.
    if not key_map:
        if default_key:
            logger.debug("API_KEYS not set; using API_Key")
            return default_key
        messagebox.showerror("API User", "No API keys configured in utilities.Key.")
        return ""

    # Check cached user selection before prompting.
    now = time.monotonic()
    global _cached_name, _cached_until
    # If we have a cached name still within TTL, reuse it.
    if _cached_name and now < _cached_until:
        # Refresh the cache window on every API key use (sliding TTL).
        canon_name, token = _lookup_key_case_insensitive(_cached_name, key_map)
        if token:
            _cached_name = canon_name
            _cached_until = now + _get_timeout_seconds(settings)
            return token
        _cached_name = None
        _cached_until = 0.0

    # Prompt until a valid name is selected or the user cancels.
    # Interactive prompt loop for kiosk-style usage.
    while True:
        name = _prompt_for_user_name(key_map, settings)
        if name is None:
            if default_key:
                logger.info("API user prompt canceled; using API_Key fallback")
                return default_key
            return ""
        name = _clean_name(name)
        if not name:
            messagebox.showwarning("API User", "User name is required.")
            continue
        # Match user selection case-insensitively so "john" matches "John".
        canon_name, token = _lookup_key_case_insensitive(name, key_map)
        if token:
            _cached_name = canon_name
            _cached_until = time.monotonic() + _get_timeout_seconds(settings)
            logger.info("Using prompted API user: %s", canon_name)
            return token

        retry = messagebox.askretrycancel(
            "API User",
            f"Unknown user '{name}'.\n\nRetry?",
        )
        if not retry:
            if default_key:
                logger.info("Unknown API user %s; using API_Key fallback", name)
                return default_key
            return ""


def get_api_headers(content_type: str | None = "application/json",
                    accept: str = "application/json",
                    extra: dict | None = None) -> dict:
    """Return Snipe-IT request headers using the active API key.

    Args:
        content_type: Optional Content-Type header (None to omit).
        accept: Accept header value.
        extra: Optional additional headers to merge.

    Returns:
        Header dict suitable for requests.
    """
    # Pull the active API key and build base headers.
    token = get_api_key()
    headers = {
        "accept": accept,
        "Authorization": f"Bearer {token}",
    }
    if content_type:
        # Only include Content-Type when the caller requests it.
        headers["content-type"] = content_type
    if extra:
        # Allow callers to override or add headers.
        headers.update(extra)
    return headers


def clear_cached_api_user() -> None:
    """Clear any cached prompt-based API user selection."""
    global _cached_name, _cached_until
    _cached_name = None
    _cached_until = 0.0
    logger.info("Cleared cached API user selection")


def set_api_user_static_name(name: str) -> bool:
    """Persist apiUserStaticName to settings.json.

    Args:
        name: Static API user name to store (use "none" to disable).

    Returns:
        True when the settings file is updated, False on failure.
    """
    configure_logging()
    settings_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings.json")
    try:
        if os.path.isfile(settings_path):
            with open(settings_path, "r") as fh:
                data = json.load(fh) or {}
        else:
            data = {}
        data["apiUserStaticName"] = str(name or "none")
        with open(settings_path, "w") as fh:
            json.dump(data, fh)
        logger.info("Updated apiUserStaticName to %s", data["apiUserStaticName"])
        return True
    except Exception:
        logger.exception("Failed to update apiUserStaticName in settings.json")
        return False


def get_api_user_status() -> dict:
    """Return a non-interactive snapshot of API user selection state.

    Returns:
        Dict with keys:
          - mode: static | cached | prompt | fallback | none
          - name: user display name when available, else None
          - expires_in: seconds remaining for cached mode, else None
          - detail: optional extra note (e.g., static_missing)
    """
    settings = get_settings()
    key_map = _load_key_map()
    default_key = _get_default_key()

    static_name = _clean_name(settings.get("apiUserStaticName"))
    if _is_static_name(static_name):
        canon_name, token = _lookup_key_case_insensitive(static_name, key_map)
        if token:
            return {"mode": "static", "name": canon_name, "expires_in": None}
        if default_key:
            return {"mode": "fallback", "name": "API_Key (fallback)", "expires_in": None, "detail": "static_missing"}
        return {"mode": "none", "name": None, "expires_in": None, "detail": "static_missing"}

    if not key_map:
        if default_key:
            return {"mode": "fallback", "name": "API_Key (fallback)", "expires_in": None}
        return {"mode": "none", "name": None, "expires_in": None}

    now = time.monotonic()
    global _cached_name, _cached_until
    if _cached_name and now < _cached_until:
        canon_name, token = _lookup_key_case_insensitive(_cached_name, key_map)
        if token:
            return {
                "mode": "cached",
                "name": canon_name,
                "expires_in": max(0.0, _cached_until - now),
            }
        _cached_name = None
        _cached_until = 0.0

    if _cached_name and now >= _cached_until:
        _cached_name = None
        _cached_until = 0.0

    return {"mode": "prompt", "name": None, "expires_in": None}
