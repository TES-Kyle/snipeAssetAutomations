"""Tests for Consisterizer helper functions."""

from consisterizer import consisterizer as c


def test_norm_field_key():
    assert c._norm_field_key(" Asset Tag ") == "asset_tag"
    assert c._norm_field_key(None) == ""


def test_valid_date():
    assert c.valid_date("2025-12-02") is True
    assert c.valid_date("2025-13-40") is False


def test_valid_asset_tag_custom_regex(monkeypatch):
    monkeypatch.setattr(c, "get_settings", lambda: {"assetTagRegex": r"^ABC\d+$"})
    assert c.valid_asset_tag("ABC123") is True
    assert c.valid_asset_tag("12345") is False


def test_valid_asset_tag_invalid_regex_falls_back(monkeypatch):
    monkeypatch.setattr(c, "get_settings", lambda: {"assetTagRegex": r"["})
    assert c.valid_asset_tag("1234") is True
