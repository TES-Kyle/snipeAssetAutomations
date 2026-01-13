"""Tests for logging utility helpers."""

import logging

from utilities import logging_utils


def test_resolve_log_level_defaults_to_debug():
    assert logging_utils._resolve_log_level("nope") == logging.DEBUG


def test_resolve_log_level_info():
    assert logging_utils._resolve_log_level("info") == logging.INFO


def test_resolve_log_level_warning():
    assert logging_utils._resolve_log_level("warning") == logging.WARNING


def test_resolve_log_level_error():
    assert logging_utils._resolve_log_level("error") == logging.ERROR
