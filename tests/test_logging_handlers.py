"""Tests for logging handler utilities."""

import logging

from utilities import logging_utils


def test_handler_exists_and_update_levels():
    logger = logging.getLogger("test_logger")
    logger.handlers = []

    file_handler = logging.FileHandler("/dev/null")
    stream_handler = logging.StreamHandler()
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    assert logging_utils._handler_exists(logger, logging.FileHandler) is True
    assert logging_utils._handler_exists(logger, logging.StreamHandler) is True

    logging_utils._update_handler_levels(logger, logging.ERROR)
    assert file_handler.level == logging.ERROR
    assert stream_handler.level == logging.ERROR
