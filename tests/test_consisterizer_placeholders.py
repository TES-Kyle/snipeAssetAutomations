"""Tests for placeholder helpers without Tk dependencies."""

from consisterizer import consisterizer as c


class DummyEntry:
    def __init__(self, text="", placeholder_active=False):
        self._text = text
        self.placeholder_active = placeholder_active
    def get(self):
        return self._text


def test_is_effective_empty_placeholder_active():
    entry = DummyEntry(text="anything", placeholder_active=True)
    assert c.is_effective_empty(entry) is True


def test_is_effective_empty_non_empty_text():
    entry = DummyEntry(text="Value", placeholder_active=False)
    assert c.is_effective_empty(entry) is False
