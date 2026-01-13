"""Tests for otherApiBits error handling with message lists."""

from utilities import otherApiBits


class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
    def json(self):
        return self._payload
    def raise_for_status(self):
        return None


def test_get_asset_info_error_messages_list(monkeypatch):
    payload = {"status": "error", "messages": ["One", "Two"]}
    monkeypatch.setattr(otherApiBits.requests, "get", lambda *a, **k: _Resp(payload))
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    called = {"count": 0}
    monkeypatch.setattr(
        otherApiBits,
        "messagebox",
        type("X", (), {"showerror": lambda *a, **k: called.__setitem__("count", called["count"] + 1)}),
    )
    var_list, asset_data = otherApiBits.getAssetInfo("1234", allow_missing=False)
    assert var_list == []
    assert asset_data == {}
    assert called["count"] == 1
