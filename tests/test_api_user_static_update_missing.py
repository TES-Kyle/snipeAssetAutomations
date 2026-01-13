"""Tests for api_user static name persistence error handling."""

from utilities import api_user


def test_set_api_user_static_name_write_error(monkeypatch):
    monkeypatch.setattr(api_user, "configure_logging", lambda: None)
    monkeypatch.setattr(api_user.os.path, "isfile", lambda _p: True)
    def _raise(*_a, **_k):
        raise OSError("boom")
    monkeypatch.setattr("builtins.open", _raise)
    ok = api_user.set_api_user_static_name("none")
    assert ok is False
