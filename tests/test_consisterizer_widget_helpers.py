"""Tests for Consisterizer widget helpers without Tk."""

from consisterizer import consisterizer as c


class DummyEntry:
    def __init__(self, text=""):
        self.text = text
    def __bool__(self):
        return True
    def get(self):
        return self.text
    def delete(self, *_args):
        self.text = ""
    def insert(self, *_args):
        self.text = _args[-1]


def test_widget_get_text_entry():
    entry = DummyEntry("value")
    assert c._widget_get_text(entry) == "value"


def test_widget_set_text_entry():
    entry = DummyEntry("old")
    c._widget_set_text(entry, "new")
    assert entry.get() == "new"
