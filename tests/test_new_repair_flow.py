"""Tests for new repair window flow without real UI/network calls."""

from assetManagementFunctions import newRepair as nr

from tests.helpers.ui_stubs import (
    DummyBoolVar,
    DummyButton,
    DummyEntry,
    DummyIntVar,
    DummyMessagebox,
    DummyStringVar,
    DummyText,
    DummyWindow,
    DummyWidget,
    reset_ui_state,
)


def _patch_ui(monkeypatch):
    reset_ui_state()
    monkeypatch.setattr(nr.tk, "Toplevel", DummyWindow)
    monkeypatch.setattr(nr.tk, "Frame", DummyWidget)
    monkeypatch.setattr(nr.tk, "Label", DummyWidget)
    monkeypatch.setattr(nr.tk, "Entry", DummyEntry)
    monkeypatch.setattr(nr.tk, "Text", DummyText)
    monkeypatch.setattr(nr.tk, "Button", DummyButton)
    monkeypatch.setattr(nr.tk, "Checkbutton", DummyWidget)
    monkeypatch.setattr(nr.tk, "Radiobutton", DummyWidget)
    monkeypatch.setattr(nr.tk, "IntVar", DummyIntVar)
    monkeypatch.setattr(nr.tk, "BooleanVar", DummyBoolVar)
    monkeypatch.setattr(nr.tk, "StringVar", DummyStringVar)


def test_new_repair_window_builds(monkeypatch):
    _patch_ui(monkeypatch)
    monkeypatch.setattr(
        nr,
        "getAssetInfo",
        lambda _tag: ([("Asset Tag", "1234")], {"asset_tag": "1234", "status_label": {"name": "Ready"}}),
    )
    monkeypatch.setattr(nr, "messagebox", DummyMessagebox())

    result = nr.newRepair("1234")

    assert result == "New repair window opened for 1234. Submit to complete."
