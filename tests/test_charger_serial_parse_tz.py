"""Tests for charger history parsing with timezone token."""

from datetime import datetime

from assetManagementFunctions.chargerSerial import parse_charger_info


def test_parse_charger_info_with_timezone():
    raw = "Wed Oct 2 13:14:15 PDT 2025 ABC123"
    results = parse_charger_info(raw)
    assert results == [(datetime(2025, 10, 2, 13, 14, 15), "ABC123")]
