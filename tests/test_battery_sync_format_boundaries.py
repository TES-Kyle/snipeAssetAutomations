"""Tests for battery percentage formatting boundaries."""

from otherManagementFunctions import batteryDataSync as bds


def test_format_three_sig_pct_boundaries():
    assert bds._format_three_sig_pct(10) == "10.0"
    assert bds._format_three_sig_pct(1) == "1.00"
    assert bds._format_three_sig_pct(100) == "100"
