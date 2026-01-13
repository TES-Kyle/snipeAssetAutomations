"""Tests for api_user header helpers."""

from utilities import api_user


def test_get_api_headers_omits_content_type(monkeypatch):
    monkeypatch.setattr(api_user, "get_api_key", lambda: "token-123")
    headers = api_user.get_api_headers(content_type=None, accept="application/json")
    assert headers["Authorization"] == "Bearer token-123"
    assert headers["accept"] == "application/json"
    assert "content-type" not in headers


def test_get_api_headers_extra(monkeypatch):
    monkeypatch.setattr(api_user, "get_api_key", lambda: "token-123")
    headers = api_user.get_api_headers(extra={"X-Test": "1"})
    assert headers["Authorization"] == "Bearer token-123"
    assert headers["X-Test"] == "1"


def test_get_api_headers_content_type_default(monkeypatch):
    monkeypatch.setattr(api_user, "get_api_key", lambda: "token-123")
    headers = api_user.get_api_headers()
    assert headers["content-type"] == "application/json"
