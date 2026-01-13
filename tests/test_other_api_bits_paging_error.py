"""Tests for paging error handling."""

from utilities import otherApiBits


def test_get_paged_handles_exception(monkeypatch):
    def fake_get(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(otherApiBits.requests, "get", fake_get)
    monkeypatch.setattr(otherApiBits, "get_headers", lambda: {})
    rows = otherApiBits._get_paged("/statuslabels", limit=2)
    assert rows == []
