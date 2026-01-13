"""Additional API user status tests."""

from utilities import api_user


def test_get_api_user_status_prompt_mode(monkeypatch):
    monkeypatch.setattr(api_user, "get_settings", lambda: {"apiUserStaticName": "none"})
    monkeypatch.setattr(api_user, "_load_key_map", lambda: {"John": "token-1"})
    monkeypatch.setattr(api_user, "_get_default_key", lambda: "")
    api_user.clear_cached_api_user()
    status = api_user.get_api_user_status()
    assert status["mode"] == "prompt"


def test_get_api_user_status_fallback_when_no_keys(monkeypatch):
    monkeypatch.setattr(api_user, "get_settings", lambda: {"apiUserStaticName": "none"})
    monkeypatch.setattr(api_user, "_load_key_map", lambda: {})
    monkeypatch.setattr(api_user, "_get_default_key", lambda: "fallback-token")
    api_user.clear_cached_api_user()
    status = api_user.get_api_user_status()
    assert status["mode"] == "fallback"


def test_get_api_user_status_none_when_no_keys(monkeypatch):
    monkeypatch.setattr(api_user, "get_settings", lambda: {"apiUserStaticName": "none"})
    monkeypatch.setattr(api_user, "_load_key_map", lambda: {})
    monkeypatch.setattr(api_user, "_get_default_key", lambda: "")
    api_user.clear_cached_api_user()
    status = api_user.get_api_user_status()
    assert status["mode"] == "none"
