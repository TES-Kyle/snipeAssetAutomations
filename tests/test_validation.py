"""Tests for utilities.validation.valid_asset_tag (pure logic, no Tk/network)."""

from utilities.validation import valid_asset_tag


def test_default_pattern_accepts_4_to_5_digits():
    assert valid_asset_tag("1234", settings={})
    assert valid_asset_tag("12345", settings={})


def test_default_pattern_rejects_wrong_length():
    assert not valid_asset_tag("123", settings={})
    assert not valid_asset_tag("123456", settings={})


def test_default_pattern_rejects_non_digits():
    assert not valid_asset_tag("abcd", settings={})
    assert not valid_asset_tag("12a4", settings={})


def test_empty_or_none_value_is_invalid():
    assert not valid_asset_tag("", settings={})
    assert not valid_asset_tag(None, settings={})


def test_custom_pattern_from_settings_is_honored():
    settings = {"assetTagRegex": r"^[A-Z]{2}\d{3}$"}
    assert valid_asset_tag("AB123", settings=settings)
    assert not valid_asset_tag("1234", settings=settings)


def test_malformed_custom_pattern_falls_back_to_default():
    settings = {"assetTagRegex": "(unclosed["}
    assert valid_asset_tag("1234", settings=settings)
    assert not valid_asset_tag("abcd", settings=settings)


def test_uses_get_settings_when_settings_arg_omitted(monkeypatch):
    import utilities.validation as validation

    monkeypatch.setattr(validation, "get_settings", lambda: {"assetTagRegex": r"^\d{2}$"})
    assert valid_asset_tag("42")
    assert not valid_asset_tag("4242")
