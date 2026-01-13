"""Tests for otherApiBits paging and option builders."""

from utilities import otherApiBits


class _Resp:
    def __init__(self, rows):
        self.status_code = 200
        self._rows = rows
    def json(self):
        return {"rows": self._rows}
    def raise_for_status(self):
        return None


def test_get_paged_combines_pages(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        if "offset=0" in url:
            return _Resp([{"id": 1}, {"id": 2}])
        if "offset=2" in url:
            return _Resp([{"id": 3}])
        return _Resp([])

    monkeypatch.setattr(otherApiBits.requests, "get", fake_get)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    rows = otherApiBits._get_paged("/statuslabels", limit=2)
    assert [r["id"] for r in rows] == [1, 2, 3]


def test_get_all_status_options_unique_sorted(monkeypatch):
    rows = [
        {"id": 2, "name": "b"},
        {"id": 1, "name": "A"},
        {"id": 2, "name": "b"},
    ]
    monkeypatch.setattr(otherApiBits, "_get_paged", lambda *a, **k: rows)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    out = otherApiBits.getAllStatusOptions()
    assert [o["id"] for o in out] == [1, 2]
    assert [o["label"] for o in out] == ["A", "b"]


def test_get_all_assignee_options(monkeypatch):
    def fake_paged(url, headers=None, limit=500, extra_params=""):
        if url == "/users":
            return [{"id": 1, "name": "User One", "username": "u1", "email": "u1@example.com"}]
        if url == "/locations":
            return [{"id": 10, "name": "Lab"}]
        return []

    monkeypatch.setattr(otherApiBits, "_get_paged", fake_paged)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    out = otherApiBits.getAllAssigneeOptions()
    assert any(o["type"] == "user" and o["id"] == 1 for o in out)
    assert any(o["type"] == "location" and o["id"] == 10 for o in out)


def test_get_all_model_options(monkeypatch):
    monkeypatch.setattr(otherApiBits, "_get_paged", lambda *a, **k: [{"id": 2, "name": "Model B"}])
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    out = otherApiBits.getAllModelOptions()
    assert out[0]["label"] == "Model B"


def test_get_paged_accepts_data_key(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return type("R", (), {"json": lambda *_: {"data": [{"id": 1}]},"raise_for_status": lambda *_: None})()

    monkeypatch.setattr(otherApiBits.requests, "get", fake_get)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    rows = otherApiBits._get_paged("/models", limit=10)
    assert rows == [{"id": 1}]
