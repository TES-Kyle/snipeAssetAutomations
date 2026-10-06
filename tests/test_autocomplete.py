"""Tests for utilities.autocomplete's pure logic (the AutoCompleteEntry
widget itself needs a live Tk display and isn't unit-tested here, matching
this codebase's convention of leaving Tk window-building code untested)."""

from utilities.autocomplete import _label_matches_any_option, _option_identity


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


def test_option_identity_ignores_volatile_meta_payload():
    # Same status (id/type/label unchanged), but "meta" -- the raw
    # Snipe-IT payload -- carries a field (e.g. a live asset count) that
    # changed between fetches. This is exactly what made set_options()
    # wrongly clear a still-valid "In Storage" selection every time that
    # status's count ticked: it was comparing whole dicts, not identity.
    old = {"label": "In Storage", "id": 7, "meta": {"id": 7, "name": "In Storage", "assets_count": 40}}
    fresh = {"label": "In Storage", "id": 7, "meta": {"id": 7, "name": "In Storage", "assets_count": 41}}
    assert _option_identity(old) == _option_identity(fresh)


def test_option_identity_differs_for_a_genuinely_different_option():
    a = {"label": "In Storage", "id": 7, "meta": {}}
    b = {"label": "In Repair", "id": 8, "meta": {}}
    assert _option_identity(a) != _option_identity(b)
