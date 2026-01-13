"""Tests for battery sync preview formatting."""

from otherManagementFunctions import batteryDataSync as bds


def test_preview_dict_and_list():
    assert "<dict" in bds._preview({"a": 1, "b": 2})
    assert "<list" in bds._preview([1, 2, 3])
