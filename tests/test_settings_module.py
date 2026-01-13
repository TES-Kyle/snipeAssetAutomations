"""Tests for settings module initialization."""

import importlib.util
import io
import os
import sys


def test_settings_module_import(monkeypatch):
    real_open = open
    real_isfile = os.path.isfile

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    defaults_path = os.path.join(root, "utilities", "defaultSettings.json")
    settings_path = os.path.join(root, "utilities", "settings.json")
    module_path = os.path.join(root, "utilities", "settings.py")

    def fake_isfile(path):
        if os.path.abspath(path) == os.path.abspath(settings_path):
            return False
        return real_isfile(path)

    def fake_open(path, mode="r", *args, **kwargs):
        abs_path = os.path.abspath(path)
        if abs_path == os.path.abspath(settings_path) and "r" in mode:
            return io.StringIO("{}")
        if abs_path == os.path.abspath(settings_path) and "w" in mode:
            return io.StringIO()
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(os.path, "isfile", fake_isfile)
    monkeypatch.setattr(sys.modules["builtins"], "open", fake_open)

    sys.modules.pop("utilities.settings", None)

    spec = importlib.util.spec_from_file_location("utilities.settings", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["utilities.settings"] = module
    spec.loader.exec_module(module)

    assert isinstance(module.settings, dict)
    assert isinstance(module.defaults, dict)
    assert module.defaults
