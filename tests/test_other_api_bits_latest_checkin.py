"""Tests for latest check-in name helpers."""

from utilities import otherApiBits


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
    def json(self):
        return self._payload
    def raise_for_status(self):
        return None


def test_get_latest_checkin_name_basic(monkeypatch):
    activity_payload = {"rows": [{"target": {"id": 1, "name": "User One"}}]}
    monkeypatch.setattr(otherApiBits.requests, "get", lambda *a, **k: _Resp(activity_payload))
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    name = otherApiBits.getLatestCheckinName(1)
    assert name == "User One"


def test_get_latest_checkin_name_none(monkeypatch):
    activity_payload = {"rows": []}
    monkeypatch.setattr(otherApiBits.requests, "get", lambda *a, **k: _Resp(activity_payload))
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    name = otherApiBits.getLatestCheckinName(1)
    assert name is None


def test_get_latest_checkin_name_email(monkeypatch):
    activity_payload = {"rows": [{"target": {"id": 1, "name": "User One"}}]}
    user_payload = {"email": "user@example.com", "username": "user1"}
    calls = {"i": 0}

    def fake_get(*_args, **_kwargs):
        calls["i"] += 1
        if calls["i"] == 1:
            return _Resp(activity_payload)
        return _Resp(user_payload)

    monkeypatch.setattr(otherApiBits.requests, "get", fake_get)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    email = otherApiBits.getLatestCheckinName(1, email=True)
    assert email == "user@example.com"


def test_get_latest_checkin_name_username(monkeypatch):
    activity_payload = {"rows": [{"target": {"id": 1, "name": "User One"}}]}
    user_payload = {"email": "user@example.com", "username": "user1"}
    calls = {"i": 0}

    def fake_get(*_args, **_kwargs):
        calls["i"] += 1
        if calls["i"] == 1:
            return _Resp(activity_payload)
        return _Resp(user_payload)

    monkeypatch.setattr(otherApiBits.requests, "get", fake_get)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    monkeypatch.setattr(otherApiBits, "messagebox", type("X", (), {"showerror": lambda *a, **k: None}))
    username = otherApiBits.getLatestCheckinName(1, username=True)
    assert username == "user1"
