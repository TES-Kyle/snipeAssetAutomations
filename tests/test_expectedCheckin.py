"""Tests for utilities.expectedCheckin (pure logic, no Tk/network)."""

from utilities.expectedCheckin import with_checkin_time


def test_with_checkin_time_appends_3pm():
    assert with_checkin_time("2026-09-15") == "2026-09-15 15:00:00"


def test_with_checkin_time_passes_through_blank_as_none():
    assert with_checkin_time("") is None
    assert with_checkin_time(None) is None


def test_with_checkin_time_leaves_explicit_time_unchanged():
    assert with_checkin_time("2026-09-15 09:30:00") == "2026-09-15 09:30:00"
