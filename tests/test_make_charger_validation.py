"""Tests for makeCharger date input validation logic."""

import re


def _validate_date(P: str) -> bool:
    """Mirror makeCharger date validation logic (partial YYYY-MM-DD)."""
    date_partial_re = re.compile(r"^\d{0,4}(-\d{0,2}(-\d{0,2})?)?$")
    if P == "":
        return True
    if len(P) > 10:
        return False
    return bool(date_partial_re.fullmatch(P))


def test_validate_date_partial():
    assert _validate_date("") is True
    assert _validate_date("2025") is True
    assert _validate_date("2025-") is True
    assert _validate_date("2025-12-") is True
    assert _validate_date("2025-12-02") is True
    assert _validate_date("2025-12-021") is False
