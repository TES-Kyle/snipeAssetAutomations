"""Tests for logging settings merge behavior."""

from utilities import logging_utils


def test_load_settings_overrides(monkeypatch):
    def fake_safe_read_json(path):
        if path.endswith("defaultSettings.json"):
            return {"a": "1", "b": "2"}
        if path.endswith("settings.json"):
            return {"b": "3"}
        return {}

    monkeypatch.setattr(logging_utils, "_safe_read_json", fake_safe_read_json)
    merged = logging_utils._load_settings()
    assert merged["a"] == "1"
    assert merged["b"] == "3"
