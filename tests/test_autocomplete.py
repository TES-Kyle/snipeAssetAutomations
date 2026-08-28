"""Tests for utilities.autocomplete's pure logic (the AutoCompleteEntry
widget itself needs a live Tk display and isn't unit-tested here, matching
this codebase's convention of leaving Tk window-building code untested)."""

from utilities.autocomplete import _label_matches_any_option


def test_empty_text_is_never_invalid():
    # An empty field is "absent", not "mismatched" -- required-ness is a
    # separate concern callers enforce themselves.
    assert _label_matches_any_option("", [{"label": "A"}]) is True
    assert _label_matches_any_option("", []) is True


def test_exact_label_match():
    options = [{"label": "Loan Fleet"}, {"label": "In Repair"}]
    assert _label_matches_any_option("Loan Fleet", options) is True


def test_no_match_is_invalid():
    options = [{"label": "Loan Fleet"}, {"label": "In Repair"}]
    assert _label_matches_any_option("Deleted Status", options) is False


def test_match_is_case_sensitive():
    # Matches the widget's own selection semantics (exact label equality,
    # same as _commit_selection/set_selected_by_label) -- not the fuzzy
    # case-insensitive scoring used while typing suggestions.
    options = [{"label": "Loan Fleet"}]
    assert _label_matches_any_option("loan fleet", options) is False
