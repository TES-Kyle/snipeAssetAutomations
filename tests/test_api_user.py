"""Tests for API user selection helpers."""

import time

from utilities import api_user


def test_lookup_key_case_insensitive():
    key_map = {"John": "token-1", "Alice": "token-2"}
    name, token = api_user._lookup_key_case_insensitive("john", key_map)
    assert name == "John"
    assert token == "token-1"


def test_get_api_user_status_static(monkeypatch):
    monkeypatch.setattr(api_user, "get_settings", lambda: {"apiUserStaticName": "John"})
    monkeypatch.setattr(api_user, "_load_key_map", lambda: {"John": "token-1"})
    monkeypatch.setattr(api_user, "_get_default_key", lambda: "")
    status = api_user.get_api_user_status()
    assert status["mode"] == "static"
    assert status["name"] == "John"


def test_get_api_user_status_cached(monkeypatch):
    monkeypatch.setattr(api_user, "get_settings", lambda: {"apiUserStaticName": "none"})
    monkeypatch.setattr(api_user, "_load_key_map", lambda: {"John": "token-1"})
    monkeypatch.setattr(api_user, "_get_default_key", lambda: "")
    api_user._cached_name = "John"
    api_user._cached_until = time.monotonic() + 60
    status = api_user.get_api_user_status()
    assert status["mode"] == "cached"
    assert status["name"] == "John"
    assert status["expires_in"] is not None
    api_user.clear_cached_api_user()


def test_get_api_user_status_fallback_for_missing_static(monkeypatch):
    monkeypatch.setattr(api_user, "get_settings", lambda: {"apiUserStaticName": "Missing"})
    monkeypatch.setattr(api_user, "_load_key_map", lambda: {"John": "token-1"})
    monkeypatch.setattr(api_user, "_get_default_key", lambda: "fallback-token")
    status = api_user.get_api_user_status()
    assert status["mode"] == "fallback"
    assert status.get("detail") == "static_missing"
