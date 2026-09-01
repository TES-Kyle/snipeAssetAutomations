"""Tests for utilities.api_user's pure logic.

_clean_name is called with both safe display names and raw API
tokens/keys (it can't tell which) -- these are regression tests for a real
incident where its own debug logging dumped live JWTs into
logs/automations.log on every ~1s status-poll tick on deployed machines.
"""

import logging

from utilities.api_user import _clean_name


def test_clean_name_strips_and_stringifies():
    assert _clean_name("  Joe  ") == "Joe"
    assert _clean_name(None) == ""
    assert _clean_name(123) == "123"


def test_clean_name_never_logs_the_raw_value(caplog):
    secret = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.super-secret-token-value"
    with caplog.at_level(logging.DEBUG):
        _clean_name(secret)
    assert secret not in caplog.text
