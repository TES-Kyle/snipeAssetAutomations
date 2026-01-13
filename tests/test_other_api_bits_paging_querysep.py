"""Tests for paging URL query separator handling."""

from utilities import otherApiBits


def test_get_paged_query_sep_when_url_has_query(monkeypatch):
    seen = {"url": None}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        return type("R", (), {"json": lambda *_: {"rows": []}, "raise_for_status": lambda *_: None})()

    monkeypatch.setattr(otherApiBits.requests, "get", fake_get)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    otherApiBits._get_paged("/statuslabels?type=asset", limit=25)
    assert "?type=asset&limit=25" in seen["url"]
