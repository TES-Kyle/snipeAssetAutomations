"""Tests for autocomplete ranking."""

from utilities.autocomplete import AutoCompleteEntry


def test_top_matches_empty_query_sorted():
    ac = AutoCompleteEntry.__new__(AutoCompleteEntry)
    ac._all_options = [{"label": "b"}, {"label": "A"}]
    matches = ac._top_matches("", limit=5)
    assert [m["label"] for m in matches] == ["A", "b"]


def test_top_matches_prefix_priority():
    ac = AutoCompleteEntry.__new__(AutoCompleteEntry)
    ac._all_options = [{"label": "alpha"}, {"label": "beta"}, {"label": "alphabet"}]
    matches = ac._top_matches("alp", limit=5)
    assert [m["label"] for m in matches][:2] == ["alpha", "alphabet"]


def test_top_matches_subsequence_priority():
    ac = AutoCompleteEntry.__new__(AutoCompleteEntry)
    ac._all_options = [{"label": "alphabet"}, {"label": "albeta"}, {"label": "beta"}]
    matches = ac._top_matches("ab", limit=5)
    assert matches[0]["label"] == "alphabet"
