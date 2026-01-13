"""Tests for drop-off state parsing and formatting."""

from assetManagementFunctions import dropOff


def test_format_state_line_basic():
    state = dropOff._init_default_state(12)
    state["streams"]["SG"] = {"box": 2, "count": 3}
    line = dropOff._format_state_line(state)
    assert "box capacity 12" in line
    assert "SG box 2 computer 3" in line


def test_format_state_notes_includes_header():
    state = dropOff._init_default_state(5)
    notes = dropOff._format_state_notes(state)
    assert notes.startswith("# BOX STATE")
    assert "box capacity 5" in notes


def test_detect_malformed_notes():
    assert dropOff._detect_malformed_notes("just text") is True
    assert dropOff._detect_malformed_notes("box capacity 10") is True
    assert dropOff._detect_malformed_notes("box capacity 10; SG box 1 computer 0") is False


def test_parse_state_from_notes_defaults():
    state = dropOff._parse_state_from_notes("", 12)
    assert state["capacity"] == 12
    assert state["streams"]["SG"]["box"] == 1
    assert state["streams"]["SG"]["count"] == 0


def test_parse_state_from_notes_custom_values():
    notes = "box capacity 10; SG box 3 computer 4; WM box 2 computer 1"
    state = dropOff._parse_state_from_notes(notes, 12)
    assert state["capacity"] == 10
    assert state["streams"]["SG"]["box"] == 3
    assert state["streams"]["SG"]["count"] == 4
    assert state["streams"]["WM"]["box"] == 2
    assert state["streams"]["WM"]["count"] == 1


def test_format_seq_padding():
    assert dropOff._format_seq(1) == "01"
    assert dropOff._format_seq(99) == "99"
    assert dropOff._format_seq(100) == "100"
