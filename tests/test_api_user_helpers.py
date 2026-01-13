"""Tests for api_user helper functions."""

from utilities import api_user


def test_clean_name_handles_none():
    assert api_user._clean_name(None) == ""


def test_is_static_name_filters_fallbacks():
    assert api_user._is_static_name("none") is False
    assert api_user._is_static_name("auto") is False
    assert api_user._is_static_name("John") is True


def test_get_timeout_seconds_clamps_negative(monkeypatch):
    settings = {"apiUserTimeoutMinutes": "-5"}
    assert api_user._get_timeout_seconds(settings) == 0.0


def test_lookup_key_case_insensitive_missing():
    name, token = api_user._lookup_key_case_insensitive("missing", {"John": "x"})
    assert name is None
    assert token is None
