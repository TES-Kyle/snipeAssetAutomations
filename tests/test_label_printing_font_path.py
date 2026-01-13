"""Tests for label font path selection."""

import os

from utilities.labelPrinting import get_font_path


def test_get_font_path_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert get_font_path().endswith("ARIBLK.TTF")


def test_get_font_path_macos(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "uname", lambda: type("U", (), {"sysname": "Darwin"})())
    assert get_font_path().endswith("Arial Black.ttf")


def test_get_font_path_posix_unsupported(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "uname", lambda: type("U", (), {"sysname": "Linux"})())
    try:
        get_font_path()
    except OSError as exc:
        assert "Unsupported POSIX" in str(exc)
    else:
        raise AssertionError("Expected OSError for unsupported POSIX OS")
