"""Tests for asset info helpers in otherApiBits."""

from utilities import otherApiBits


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


def test_get_asset_info_allow_missing(monkeypatch):
    payload = {"status": "error", "messages": "Asset does not exist."}
    monkeypatch.setattr(otherApiBits.requests, "get", lambda *a, **k: _Resp(200, payload))
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "_log_asset_data", lambda *_: None)
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    var_list, asset_data = otherApiBits.getAssetInfo("9999", allow_missing=True)
    assert var_list == []
    assert asset_data == payload


def test_get_asset_info_builds_var_list(monkeypatch):
    payload = {
        "status": "success",
        "asset_tag": "1234",
        "serial": "ABC",
        "name": "Device",
        "status_label": {"name": "Deployed"},
        "assigned_to": {"name": "User", "email": "user@example.com"},
        "custom_fields": {},
    }
    monkeypatch.setattr(otherApiBits.requests, "get", lambda *a, **k: _Resp(200, payload))
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "_log_asset_data", lambda *_: None)
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    var_list, _ = otherApiBits.getAssetInfo("1234")
    assert ("Asset Tag", "1234") in var_list
    assert ("Serial Number", "ABC") in var_list
    assert ("Asset Name", "Device") in var_list
