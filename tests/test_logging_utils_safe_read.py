"""Tests for logging_utils JSON reader."""

from utilities import logging_utils


def test_safe_read_json_missing(tmp_path):
    missing = tmp_path / "missing.json"
    assert logging_utils._safe_read_json(str(missing)) == {}
