"""Additional date parsing tests for back-from-Apple helpers."""

from datetime import date

from assetManagementFunctions.backFromApple import _parse_date_value


def test_parse_date_value_formatted_with_time():
    val = "2025-10-22 11:33 AM"
    assert _parse_date_value(val) == date(2025, 10, 22)
