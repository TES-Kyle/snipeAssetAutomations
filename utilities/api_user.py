"""API user selection helpers for Snipe-IT requests.

This module centralizes API key selection so Snipe-IT changes can be
attributed to individual users while still supporting a single fallback key.
It supports:
  - a static user selection (always use a named key)
  - a prompt-based selection (cache the chosen user for N minutes)
  - a legacy single API_Key fallback for compatibility
"""

from __future__ import annotations

import logging
import time
from tkinter import messagebox, simpledialog

from utilities import Key
from utilities.logging_utils import configure_logging
from utilities.settings import get_settings, update_settings

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
    logger.debug("_clean_name: value=%s", value)
    result = str(value or "").strip()
    logger.debug("_clean_name: result=%s", result)
    return result


def _load_key_map() -> dict:
    """Load API_KEYS from utilities.Key and normalize entries.

    Returns:
        Dict of {display_name: api_key} with empty values removed.
    """
    logger.debug("_load_key_map: loading API_KEYS from Key module")
    raw = getattr(Key, "API_KEYS", None)
    if not isinstance(raw, dict):
        logger.debug("_load_key_map: API_KEYS not a dict (got %s); returning empty map", type(raw).__name__)
        return {}
    key_map = {}
    for name, token in raw.items():
        # Normalize both names and tokens to avoid whitespace mismatches.
        name_clean = _clean_name(name)
        token_clean = _clean_name(token)
        if name_clean and token_clean:
            key_map[name_clean] = token_clean
    logger.debug("_load_key_map: loaded %s entries", len(key_map))
    return key_map


def _lookup_key_case_insensitive(name: str, key_map: dict) -> tuple[str | None, str | None]:
    """Return a canonical key name and token using case-insensitive matching.

    Args:
        name: User-provided name to match.
        key_map: Mapping of display names to API keys.

    Returns:
        (canonical_name, token) tuple, or (None, None) when no match exists.
    """
    logger.debug("_lookup_key_case_insensitive: name=%s, key_map size=%s", name, len(key_map))
    if not name:
        logger.debug("_lookup_key_case_insensitive: empty name, returning (None, None)")
        return None, None
    if name in key_map:
        logger.debug("_lookup_key_case_insensitive: exact match found for %s", name)
        return name, key_map.get(name)
    name_lower = name.lower()
    logger.debug("_lookup_key_case_insensitive: no exact match, trying case-insensitive for %s", name_lower)
    for key, token in key_map.items():
        if key.lower() == name_lower:
            logger.debug("_lookup_key_case_insensitive: case-insensitive match: %s -> %s", name, key)
            return key, token
    logger.debug("_lookup_key_case_insensitive: no match found for %s", name)
    return None, None


def _get_default_key() -> str:
    """Return the legacy API_Key value as a normalized string.

    Returns:
        API_Key string or empty string if not configured.
    """
    logger.debug("_get_default_key: reading API_Key from Key module")
    result = _clean_name(getattr(Key, "API_Key", ""))
    logger.debug("_get_default_key: API_Key present=%s", bool(result))
    return result


def _get_timeout_seconds(settings: dict) -> float:
    """Convert apiUserTimeoutMinutes to seconds, clamped to non-negative.

    Args:
        settings: Settings dictionary from logging_utils.get_settings().

    Returns:
        Timeout in seconds (float), never negative.
    """
    logger.debug("_get_timeout_seconds: reading apiUserTimeoutMinutes from settings")
    raw = settings.get("apiUserTimeoutMinutes", "5")
    logger.debug("_get_timeout_seconds: raw value=%s", raw)
    try:
        minutes = float(raw)
    except Exception:
        logger.debug("_get_timeout_seconds: could not parse %s, defaulting to 5.0", raw)
        minutes = 5.0
    if minutes < 0:
        logger.debug("_get_timeout_seconds: negative value clamped to 0")
        minutes = 0.0
    result = minutes * 60.0
    logger.debug("_get_timeout_seconds: timeout=%s seconds", result)
    return result


def _is_static_name(name: str) -> bool:
    """Return True if the name is a valid static user selection.

    Args:
        name: Candidate static user name.

    Returns:
        True when the name is non-empty and not a fallback sentinel.
    """
    logger.debug("_is_static_name: checking name=%s", name)
    result = bool(name) and name.lower() not in _FALLBACK_NAMES
    logger.debug("_is_static_name: result=%s", result)
    return result


def _prompt_for_user_name(key_map: dict, settings: dict) -> str | None:
    """Prompt for a user name, optionally showing available entries.

    Args:
        key_map: Normalized mapping of user names to API keys.
        settings: Settings dictionary with prompt text overrides.

    Returns:
        User-entered string or None if the dialog is canceled.
    """
    logger.debug("_prompt_for_user_name: key_map size=%s", len(key_map))
    title = _clean_name(settings.get("apiUserPromptTitle")) or "API User"
    message = _clean_name(settings.get("apiUserPromptMessage")) or "Enter API user name."
    logger.debug("_prompt_for_user_name: title=%s", title)

    if key_map:
        names = sorted(key_map.keys(), key=str.lower)
        preview_limit = 12
        preview = ", ".join(names[:preview_limit])
        logger.debug("_prompt_for_user_name: showing %s available names", len(names))
        if len(names) > preview_limit:
            preview += "..."
        if preview:
            message = f"{message}\n\nAvailable: {preview}"

    logger.info("_prompt_for_user_name: prompting user for API user selection")
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
    logger.debug("get_api_headers: content_type=%s, accept=%s, extra_keys=%s", content_type, accept, list(extra.keys()) if extra else None)
    # Pull the active API key and build base headers.
    token = get_api_key()
    logger.debug("get_api_headers: token obtained (present=%s)", bool(token))
    headers = {
        "accept": accept,
        "Authorization": f"Bearer {token}",
    }
    if content_type:
        # Only include Content-Type when the caller requests it.
        headers["content-type"] = content_type
        logger.debug("get_api_headers: content-type set to %s", content_type)
    if extra:
        # Allow callers to override or add headers.
        headers.update(extra)
        logger.debug("get_api_headers: merged %s extra header(s)", len(extra))
    logger.debug("get_api_headers: returning %s header keys", len(headers))
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
    value = str(name or "none")
    ok = update_settings({"apiUserStaticName": value})
    if ok:
        logger.info("Updated apiUserStaticName to %s", value)
    else:
        logger.error("Failed to update apiUserStaticName in settings.json")
    return ok


def get_api_user_status() -> dict:
    """Return a non-interactive snapshot of API user selection state.

    Returns:
        Dict with keys:
          - mode: static | cached | prompt | fallback | none
          - name: user display name when available, else None
          - expires_in: seconds remaining for cached mode, else None
          - detail: optional extra note (e.g., static_missing)
    """
    logger.debug("get_api_user_status: checking current API user state")
    settings = get_settings()
    key_map = _load_key_map()
    default_key = _get_default_key()
    logger.debug("get_api_user_status: key_map size=%s, default_key present=%s", len(key_map), bool(default_key))

    static_name = _clean_name(settings.get("apiUserStaticName"))
    logger.debug("get_api_user_status: static_name=%s", static_name)
    if _is_static_name(static_name):
        canon_name, token = _lookup_key_case_insensitive(static_name, key_map)
        if token:
            logger.debug("get_api_user_status: mode=static, name=%s", canon_name)
            return {"mode": "static", "name": canon_name, "expires_in": None}
        if default_key:
            logger.debug("get_api_user_status: mode=fallback (static missing)")
            return {"mode": "fallback", "name": "API_Key (fallback)", "expires_in": None, "detail": "static_missing"}
        logger.debug("get_api_user_status: mode=none (static missing, no fallback)")
        return {"mode": "none", "name": None, "expires_in": None, "detail": "static_missing"}

    if not key_map:
        if default_key:
            logger.debug("get_api_user_status: mode=fallback (no key_map)")
            return {"mode": "fallback", "name": "API_Key (fallback)", "expires_in": None}
        logger.debug("get_api_user_status: mode=none (no key_map, no fallback)")
        return {"mode": "none", "name": None, "expires_in": None}

    now = time.monotonic()
    global _cached_name, _cached_until
    logger.debug("get_api_user_status: cached_name=%s, cache_valid=%s", _cached_name, _cached_name and now < _cached_until)
    if _cached_name and now < _cached_until:
        canon_name, token = _lookup_key_case_insensitive(_cached_name, key_map)
        if token:
            expires = max(0.0, _cached_until - now)
            logger.debug("get_api_user_status: mode=cached, name=%s, expires_in=%s", canon_name, expires)
            return {
                "mode": "cached",
                "name": canon_name,
                "expires_in": expires,
            }
        logger.debug("get_api_user_status: cached name %s no longer in key_map; clearing cache", _cached_name)
        _cached_name = None
        _cached_until = 0.0

    if _cached_name and now >= _cached_until:
        logger.debug("get_api_user_status: cache expired for %s; clearing", _cached_name)
        _cached_name = None
        _cached_until = 0.0

    logger.debug("get_api_user_status: mode=prompt")
    return {"mode": "prompt", "name": None, "expires_in": None}
