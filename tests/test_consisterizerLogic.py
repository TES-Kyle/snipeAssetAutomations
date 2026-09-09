"""Tests for pure-logic helpers in consisterizer.consisterizer (no Tk/network)."""

from consisterizer.consisterizer import extract_current_values, valid_date_or_datetime


def test_valid_date_or_datetime_accepts_bare_date_and_datetime():
    assert valid_date_or_datetime("2026-09-15") is True
    assert valid_date_or_datetime("2026-09-15 15:00:00") is True


def test_valid_date_or_datetime_rejects_garbage():
    assert valid_date_or_datetime("not-a-date") is False
    assert valid_date_or_datetime("2026-09-15 25:00:00") is False


def test_extract_current_values_reads_expected_checkin_datetime_shape():
    # Snipe-IT dropped the "date" key for expected_checkin once it became a
    # datetime field -- only "datetime"/"formatted" remain.
    asset = {"expected_checkin": {"datetime": "2026-09-15 15:00:00", "formatted": "2026-09-15 03:00 PM"}}
    assert extract_current_values(asset)["expected_checkin"] == "2026-09-15 15:00:00"


def test_extract_current_values_falls_back_to_date_shape():
    asset = {"expected_checkin": {"date": "2026-09-15", "formatted": "2026-09-15"}}
    assert extract_current_values(asset)["expected_checkin"] == "2026-09-15"
