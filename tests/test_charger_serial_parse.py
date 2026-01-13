"""Tests for charger history parsing."""

from datetime import datetime

from assetManagementFunctions.chargerSerial import parse_charger_info


def test_parse_charger_info():
    raw = "Wed Oct 2 13:14:15 2025 ABC123\nThu Oct 10 09:10:11 2025 XYZ999"
    results = parse_charger_info(raw)
    assert results[0][0] == datetime(2025, 10, 2, 13, 14, 15)
    assert results[0][1] == "ABC123"
    assert results[1][1] == "XYZ999"


def test_parse_charger_info_single_digit_day():
    raw = "Wed Oct 2 13:14:15 2025 ABC123"
    results = parse_charger_info(raw)
    assert results[0][0] == datetime(2025, 10, 2, 13, 14, 15)
