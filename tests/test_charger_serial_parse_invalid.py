"""Tests for charger history parsing invalid lines."""

import pytest

from assetManagementFunctions.chargerSerial import parse_charger_info


def test_parse_charger_info_ignores_invalid_lines():
    raw = "bad line\nWed Oct 2 13:14:15 2025 ABC123"
    with pytest.raises(IndexError):
        parse_charger_info(raw)
