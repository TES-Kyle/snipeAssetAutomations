"""Date parsing tests for back-from-Apple helpers."""

from datetime import date

from assetManagementFunctions.backFromApple import _parse_date_value, _extract_checkout_date


def test_parse_date_value_from_dict():
    val = {"date": "2025-12-02", "formatted": "2025-12-02"}
    assert _parse_date_value(val) == date(2025, 12, 2)


def test_parse_date_value_from_datetime_string():
    val = "2025-10-22 11:33:26"
    assert _parse_date_value(val) == date(2025, 10, 22)


def test_extract_checkout_date_from_last_checkout():
    row = {"last_checkout": {"datetime": "2025-10-22 11:33:26", "formatted": "2025-10-22 11:33 AM"}}
    assert _extract_checkout_date(row) == date(2025, 10, 22)
