"""Tests for utilities.settings read/write helpers (pure logic, no Tk/network)."""

import json
import os

import utilities.settings as settings_mod


def _point_at_tmp(monkeypatch, tmp_path, *, defaults=None, initial=None):
    """Redirect SETTINGS_PATH/DEFAULTS_PATH at files under tmp_path."""
    settings_path = tmp_path / "settings.json"
    defaults_path = tmp_path / "defaultSettings.json"
    if initial is not None:
        settings_path.write_text(json.dumps(initial))
    if defaults is not None:
        defaults_path.write_text(json.dumps(defaults))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", str(settings_path))
    monkeypatch.setattr(settings_mod, "DEFAULTS_PATH", str(defaults_path))
    return settings_path, defaults_path


def test_update_settings_roundtrip(monkeypatch, tmp_path):
    _point_at_tmp(monkeypatch, tmp_path, initial={})
    assert settings_mod.update_settings({"assetTagRegex": r"^\d{3}$"})
    assert settings_mod.get_settings()["assetTagRegex"] == r"^\d{3}$"


def test_set_setting_leaves_other_keys_untouched(monkeypatch, tmp_path):
    _point_at_tmp(monkeypatch, tmp_path, initial={"a": 1, "b": 2})
    assert settings_mod.set_setting("b", 99)
    on_disk = json.loads((tmp_path / "settings.json").read_text())
    assert on_disk == {"a": 1, "b": 99}


def test_atomic_write_leaves_no_tmp_file(monkeypatch, tmp_path):
    _point_at_tmp(monkeypatch, tmp_path, initial={})
    assert settings_mod.update_settings({"x": "y"})
    assert not (tmp_path / "settings.json.tmp").exists()


def test_update_settings_does_not_persist_defaults(monkeypatch, tmp_path):
    _point_at_tmp(monkeypatch, tmp_path, defaults={"onlyInDefaults": "d"}, initial={})
    assert settings_mod.update_settings({"newKey": "v"})
    on_disk = json.loads((tmp_path / "settings.json").read_text())
    assert on_disk == {"newKey": "v"}
    assert "onlyInDefaults" not in on_disk
    # But get_settings() still sees the merged view.
    assert settings_mod.get_settings()["onlyInDefaults"] == "d"


def test_update_settings_returns_false_without_corrupting_on_write_failure(monkeypatch, tmp_path):
    settings_path, _ = _point_at_tmp(monkeypatch, tmp_path, initial={"keep": "me"})

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(settings_mod.os, "replace", _boom)
    assert settings_mod.update_settings({"new": "value"}) is False
    # Original file must be untouched.
    assert json.loads(settings_path.read_text()) == {"keep": "me"}


def test_get_settings_merges_defaults_under_overrides(monkeypatch, tmp_path):
    _point_at_tmp(
        monkeypatch, tmp_path,
        defaults={"a": "default", "b": "default"},
        initial={"b": "override"},
    )
    merged = settings_mod.get_settings()
    assert merged["a"] == "default"
    assert merged["b"] == "override"
