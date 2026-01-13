"""Tests for Jamf sync Snipe-IT search helper."""

from otherManagementFunctions import jamfSync


class DummyResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("bad status")

    def json(self):
        return self._payload


class DummySession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, headers=None, verify=None):
        self.calls.append((url, headers, verify))
        return DummyResponse(self.payload)


def test_search_snipe_asset_by_serial_returns_row(monkeypatch):
    payload = {"total": 1, "rows": [{"asset_tag": "1234"}]}
    sess = DummySession(payload)

    monkeypatch.setattr(jamfSync, "snipe_session", sess)
    monkeypatch.setattr(jamfSync, "_snipe_headers", lambda: {"Authorization": "token"})
    monkeypatch.setattr(jamfSync, "RATE_LIMIT_DELAY", 0)

    assert jamfSync.search_snipe_asset_by_serial("ABC") == payload["rows"][0]


def test_search_snipe_asset_by_serial_returns_none_on_zero(monkeypatch):
    payload = {"total": 0, "rows": []}
    sess = DummySession(payload)

    monkeypatch.setattr(jamfSync, "snipe_session", sess)
    monkeypatch.setattr(jamfSync, "_snipe_headers", lambda: {"Authorization": "token"})
    monkeypatch.setattr(jamfSync, "RATE_LIMIT_DELAY", 0)

    assert jamfSync.search_snipe_asset_by_serial("ABC") is None
