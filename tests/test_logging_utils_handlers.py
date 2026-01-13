"""Tests for logging_utils handler helper functions."""

import logging

from utilities import logging_utils


def test_handler_exists_false_for_missing():
    logger = logging.getLogger("test_logger_missing")
    logger.handlers = []
    assert logging_utils._handler_exists(logger, logging.StreamHandler) is False
