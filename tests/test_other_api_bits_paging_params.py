"""Tests for paging URL construction with extra params."""

from utilities import otherApiBits


def test_get_paged_includes_extra_params(monkeypatch):
    seen = {"url": None}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        return type("R", (), {"json": lambda *_: {"rows": []}, "raise_for_status": lambda *_: None})()

    monkeypatch.setattr(otherApiBits.requests, "get", fake_get)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    otherApiBits._get_paged("/statuslabels", limit=50, extra_params="type=asset")
    assert "limit=50" in seen["url"]
    assert "type=asset" in seen["url"]
