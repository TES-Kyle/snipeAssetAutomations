"""Tests for main GUI helpers without launching the full UI."""

import importlib
import sys
import types


def test_print_label_missing_file(monkeypatch):
    dummy_settings = types.SimpleNamespace(settingsMenu=lambda: None)
    sys.modules.pop("utilities.settings", None)
    monkeypatch.setitem(sys.modules, "utilities.settings", dummy_settings)

    sys.modules.pop("assetManagementGui_Main", None)
    gui = importlib.import_module("assetManagementGui_Main")

    calls = {"sent": False, "error": False}

    monkeypatch.setattr(gui.os.path, "isfile", lambda _p: False)
    monkeypatch.setattr(gui, "sendToPrinter", lambda _p: calls.update({"sent": True}))
    monkeypatch.setattr(
        gui,
        "messagebox",
        type("MB", (), {"showerror": lambda *_a, **_k: calls.update({"error": True})}),
    )

    gui.print_label()

    assert calls["sent"] is False
    assert calls["error"] is True
