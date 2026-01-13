"""Tests for drop-off state parsing regex."""

from assetManagementFunctions import dropOff as d


def test_state_line_regex_box_capacity():
    m = d._STATE_LINE_RE.search("box capacity 12")
    assert m is not None
    assert m.group("key").lower() == "box capacity"
    assert m.group("num1") == "12"


def test_state_line_regex_stream_and_computer():
    m = d._STATE_LINE_RE.search("SG box 3 computer 7")
    assert m is not None
    assert m.group("key").lower() == "sg box"
    assert m.group("num1") == "3"
    assert m.group("num2") == "7"
