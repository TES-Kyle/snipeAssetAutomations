"""Tests for battery sync helper functions."""

from otherManagementFunctions import batteryDataSync as bds


def test_extract_number_parses_commas():
    assert bds._extract_number("4,562 mAh") == 4562.0


def test_extract_number_handles_none():
    assert bds._extract_number(None) is None


def test_extract_number_parses_negative():
    assert bds._extract_number("-12.5") == -12.5


def test_normalize_condition_mapping():
    assert bds.normalize_condition("normal") == "Normal"
    assert bds.normalize_condition("REPLACE SOON") == "Replace Soon"
    assert bds.normalize_condition("Weird") == "Weird"


def test_build_battery_string_valid():
    final, is_valid = bds.build_battery_string("5000", "4500", "normal")
    assert final == "90.0% - Normal"
    assert is_valid is True


def test_build_battery_string_partial():
    final, is_valid = bds.build_battery_string(None, None, "normal")
    assert final == "N/A - Normal"
    assert is_valid is True


def test_build_battery_string_invalid():
    final, is_valid = bds.build_battery_string(None, None, None)
    assert final == "N/A - N/A"
    assert is_valid is False


def test_format_three_sig_pct_examples():
    assert bds._format_three_sig_pct(105) == "105"
    assert bds._format_three_sig_pct(99.1) == "99.1"
    assert bds._format_three_sig_pct(9.76) == "9.76"
    assert bds._format_three_sig_pct(0.987) == "0.987"


def test_format_three_sig_pct_zero():
    assert bds._format_three_sig_pct(0) == "0"
