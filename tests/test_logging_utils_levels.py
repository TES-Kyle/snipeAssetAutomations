"""Tests for logging level mapping."""

import logging

from utilities import logging_utils


def test_resolve_log_level_critical():
    assert logging_utils._resolve_log_level("critical") == logging.CRITICAL
