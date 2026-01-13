"""Tests for cached API user expiry handling."""

import time

from utilities import api_user


def test_get_api_user_status_expired_cache(monkeypatch):
    monkeypatch.setattr(api_user, "get_settings", lambda: {"apiUserStaticName": "none"})
    monkeypatch.setattr(api_user, "_load_key_map", lambda: {"John": "token-1"})
    monkeypatch.setattr(api_user, "_get_default_key", lambda: "")
    api_user._cached_name = "John"
    api_user._cached_until = time.monotonic() - 1
    status = api_user.get_api_user_status()
    assert status["mode"] == "prompt"
