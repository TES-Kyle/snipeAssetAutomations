"""Tests for check-in window flow without real UI/network calls."""

from assetManagementFunctions import checkIn as checkin

from tests.helpers.ui_stubs import (
    DummyButton,
    DummyCombobox,
    DummyEntry,
    DummyMessagebox,
    DummyStringVar,
    DummyWindow,
    DummyWidget,
    reset_ui_state,
)


class DummyResponse:
    def __init__(self, payload=None, status_code=200, text="ok"):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def _patch_ui(monkeypatch):
    reset_ui_state()
    monkeypatch.setattr(checkin.tk, "Toplevel", DummyWindow)
    monkeypatch.setattr(checkin.tk, "Frame", DummyWidget)
    monkeypatch.setattr(checkin.tk, "Label", DummyWidget)
    monkeypatch.setattr(checkin.tk, "Entry", DummyEntry)
    monkeypatch.setattr(checkin.tk, "Button", DummyButton)
    monkeypatch.setattr(checkin.tk, "StringVar", DummyStringVar)
    monkeypatch.setattr(checkin.ttk, "Combobox", DummyCombobox)


def test_checkin_window_builds(monkeypatch):
    _patch_ui(monkeypatch)
    monkeypatch.setattr(checkin, "getAssetInfo", lambda _tag: ([], {"status_label": {"name": "Ready", "id": 5}}))

    result = checkin.checkIn("1234")

    assert result == "Check-in window opened for 1234. Submit to complete."


def test_checkin_submit_success(monkeypatch):
    _patch_ui(monkeypatch)

    monkeypatch.setattr(
        checkin,
        "getAssetInfo",
        lambda _tag: ([], {"id": 44, "status_label": {"name": "Ready", "id": 5}}),
    )
    monkeypatch.setattr(checkin, "get_headers", lambda: {"Authorization": "token"})
    monkeypatch.setattr(checkin, "messagebox", DummyMessagebox())

    def fake_get(url, headers=None):
        if "/statuslabels" in url:
            return DummyResponse({"rows": [{"name": "Ready", "id": 5}]})
        return DummyResponse({"rows": []})

    def fake_post(url, json=None, headers=None):
        return DummyResponse(status_code=200)

    monkeypatch.setattr(checkin.requests, "get", fake_get)
    monkeypatch.setattr(checkin.requests, "post", fake_post)

    checkin.checkIn("1234")
    assert DummyButton.instances
    submit_cmd = DummyButton.instances[-1].command
    result = submit_cmd()

    assert result == "Check-in complete for 1234."
