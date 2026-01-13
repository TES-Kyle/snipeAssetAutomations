"""Tests for otherApiBits header passthrough."""

from utilities import otherApiBits


def test_get_headers_passthrough(monkeypatch):
    monkeypatch.setattr(otherApiBits, "get_api_headers", lambda: {"Authorization": "Bearer X"})
    headers = otherApiBits.get_headers()
    assert headers["Authorization"] == "Bearer X"
