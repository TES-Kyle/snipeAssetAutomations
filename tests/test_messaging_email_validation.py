"""Tests for messaging email validation."""

from utilities.messaging import is_email


def test_is_email_valid():
    assert is_email("user@example.com") is True
    assert is_email("USER+tag@EXAMPLE.ORG") is True


def test_is_email_invalid():
    assert is_email("not-an-email") is False
    assert is_email(None) is False
    assert is_email("user@localhost") is False
