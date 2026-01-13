"""Tests for serial assignment lookup."""

from utilities import otherApiBits


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
    def json(self):
        return self._payload
    def raise_for_status(self):
        return None


def test_get_asset_info_serial_assigned_to(monkeypatch):
    payload = {"rows": [{"assigned_to": {"name": "User Name"}}]}
    monkeypatch.setattr(otherApiBits.requests, "get", lambda *a, **k: _Resp(payload))
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    name = otherApiBits.getAssetInfoSerialAssignedTo("ABC")
    assert name == "User Name"


def test_get_asset_info_serial_assigned_to_none(monkeypatch):
    payload = {"rows": []}
    monkeypatch.setattr(otherApiBits.requests, "get", lambda *a, **k: _Resp(payload))
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    name = otherApiBits.getAssetInfoSerialAssignedTo("ABC")
    assert name is None
