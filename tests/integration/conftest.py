"""Integration test helpers for read-only network runs."""

import os

import pytest

from utilities import Key
from utilities import api_user


def _resolve_readonly_token():
    env_token = os.environ.get("READONLY_API_KEY", "").strip()
    if env_token:
        return env_token

    key_map = getattr(Key, "API_KEYS", None)
    if isinstance(key_map, dict) and key_map:
        preferred = os.environ.get("READONLY_API_USER", "").strip()
        if preferred:
            for name, token in key_map.items():
                if str(name).strip().lower() == preferred.lower() and str(token).strip():
                    return str(token).strip()
        for token in key_map.values():
            if str(token).strip():
                return str(token).strip()

    legacy = str(getattr(Key, "API_Key", "") or "").strip()
    if legacy:
        return legacy

    return ""


@pytest.fixture(autouse=True)
def readonly_api_key_guard(request, monkeypatch):
    """Avoid interactive API user prompts during read-only integration tests."""
    allow_readonly = bool(request.node.get_closest_marker("readonly_network"))
    readonly_enabled = os.environ.get("READONLY_NETWORK", "").lower() in ("1", "true", "yes", "on")
    if not (allow_readonly and readonly_enabled):
        yield
        return

    token = _resolve_readonly_token()
    if not token:
        pytest.skip("No API key available; set READONLY_API_KEY or configure Key.API_Key/API_KEYS.")

    monkeypatch.setattr(api_user, "get_api_key", lambda: token)
    yield
