"""Tests for email warning pattern parsing."""

import json
import re

from utilities import messaging


def test_remove_fine_warning_invalid_pattern(monkeypatch):
    monkeypatch.setattr(
        "builtins.open",
        _fake_settings_open(json.dumps({"emailWarnPattern": "^[^@]+@example\\.com$"})),
    )
    monkeypatch.setattr(messaging.json, "load", lambda fh: json.loads(fh.read()))
    monkeypatch.setattr(messaging, "get_parents", lambda _e: [])
    monkeypatch.setattr(
        messaging,
        "messagebox",
        type("X", (), {"showerror": lambda *a, **k: None, "askyesno": lambda *a, **k: True}),
    )
    monkeypatch.setattr(messaging, "re", re)
    assert messaging.remove_fine_warning("user@example.com") is True


def _fake_settings_open(settings_json):
    """Return an open() stub that yields a file-like object."""
    class FakeFile:
        def __init__(self, text):
            self._text = text
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return self._text
    def fake_open(*_args, **_kwargs):
        return FakeFile(settings_json)
    return fake_open

def test_remove_fine_warning_no_patterns(monkeypatch):
    monkeypatch.setattr("builtins.open", _fake_settings_open(json.dumps({"emailWarnPattern": ""})))
    monkeypatch.setattr(messaging.json, "load", lambda fh: json.loads(fh.read()))
    monkeypatch.setattr(messaging, "get_parents", lambda _e: [])
    monkeypatch.setattr(
        messaging,
        "messagebox",
        type("X", (), {"showerror": lambda *a, **k: None, "askyesno": lambda *a, **k: False}),
    )
    monkeypatch.setattr(messaging, "re", re)
    assert messaging.remove_fine_warning("user@example.com") is False
