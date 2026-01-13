"""Tests for logging_utils safe JSON read with invalid content."""

from utilities import logging_utils


def test_safe_read_json_invalid(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert logging_utils._safe_read_json(str(bad)) == {}
