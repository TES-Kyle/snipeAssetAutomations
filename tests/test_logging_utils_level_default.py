"""Tests for logging level default handling."""

import logging

from utilities import logging_utils


def test_resolve_log_level_default_none():
    assert logging_utils._resolve_log_level(None) == logging.DEBUG
