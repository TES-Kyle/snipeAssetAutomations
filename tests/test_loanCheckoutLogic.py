"""Tests for assetManagementFunctions.loanCheckout's pure logic helpers.

These are private (underscore-prefixed) module-level functions -- they're
only meaningful in the context of loan checkouts, so the logic lives
directly in loanCheckout.py rather than a shared utilities/ module (see
that file's docstring). Importing them directly by name from a test still
works fine in Python; only `import *` skips underscore names.
"""

from datetime import date

from assetManagementFunctions.loanCheckout import (
    _parse_int_list,
    _parse_reason_list,
    _parse_month_day,
    _get_last_cutoff,
    _format_loan_note_line,
    _parse_loan_note_lines,
    _count_qualifying_since_cutoff,
    _determine_checkout_outcome,
    _valid_date_string,
)

RAW_REASONS = (
    "repair:Repair:1:off;"
    "left_home:Left at home:0:0;"
    "lost:Lost (maybe permanent):0:7;"
    "other:Other:0:"
)


def _by_key(reasons, key):
    return next(r for r in reasons if r["key"] == key)


def test_parse_int_list_basic():
    assert _parse_int_list("24;35") == [24, 35]


def test_parse_int_list_skips_bad_entries_and_blanks():
    assert _parse_int_list("24; ;abc;35") == [24, 35]


def test_parse_int_list_empty_returns_empty():
    assert _parse_int_list("") == []
    assert _parse_int_list(None) == []


def test_parse_reason_list_basic_fields():
    reasons = _parse_reason_list(RAW_REASONS)
    assert len(reasons) == 4
    left_home = _by_key(reasons, "left_home")
    assert left_home == {
        "key": "left_home", "label": "Left at home",
        "repair": False, "due_days": 0, "checkin_enabled": True,
    }


def test_parse_reason_list_repair_disables_checkin_date():
    reasons = _parse_reason_list(RAW_REASONS)
    repair = _by_key(reasons, "repair")
    assert repair["repair"] is True
    assert repair["checkin_enabled"] is False
    assert repair["due_days"] is None


def test_parse_reason_list_lost_defaults_to_a_week_out():
    reasons = _parse_reason_list(RAW_REASONS)
    lost = _by_key(reasons, "lost")
    assert lost["due_days"] == 7
    assert lost["checkin_enabled"] is True


def test_parse_reason_list_other_has_no_default_but_is_editable():
    reasons = _parse_reason_list(RAW_REASONS)
    other = _by_key(reasons, "other")
    assert other["due_days"] is None
    assert other["checkin_enabled"] is True


def test_parse_reason_list_skips_malformed_entries():
    reasons = _parse_reason_list("bad:entry:only;left_home:Left at home:0:0")
    assert len(reasons) == 1
    assert reasons[0]["key"] == "left_home"


def test_parse_reason_list_empty_raw_returns_empty():
    assert _parse_reason_list("") == []
    assert _parse_reason_list(None) == []


def test_parse_month_day_accepts_dash_and_slash():
    assert _parse_month_day("07-15") == (7, 15)
    assert _parse_month_day("12/27") == (12, 27)


def test_parse_month_day_rejects_invalid():
    assert _parse_month_day("13-01") is None
    assert _parse_month_day("00-15") is None
    assert _parse_month_day("not-a-date") is None


def test_get_last_cutoff_picks_most_recent_recurring_checkpoint():
    # Cutoffs recur every year with no stored year; "today" is in August, so
    # the most recent past occurrence of 07-15 (this year) beats 12-27 (last year).
    cutoff = _get_last_cutoff("07-15;12-27", today=date(2026, 8, 25))
    assert cutoff == date(2026, 7, 15)


def test_get_last_cutoff_wraps_to_previous_year_when_this_years_is_future():
    # "today" is in January, so this year's 07-15 hasn't happened yet --
    # the most recent 12-27 was last December.
    cutoff = _get_last_cutoff("07-15;12-27", today=date(2027, 1, 15))
    assert cutoff == date(2026, 12, 27)


def test_get_last_cutoff_returns_none_for_blank():
    assert _get_last_cutoff("", today=date(2026, 8, 25)) is None


def test_get_last_cutoff_never_needs_updating_across_years():
    # Same setting string works identically many years apart -- the whole
    # point of storing MM-DD instead of a dated cutoff list.
    c1 = _get_last_cutoff("07-15", today=date(2026, 8, 1))
    c2 = _get_last_cutoff("07-15", today=date(2031, 8, 1))
    assert c1 == date(2026, 7, 15)
    assert c2 == date(2031, 7, 15)


def test_note_line_round_trip_counts():
    line = _format_loan_note_line(date(2026, 8, 25), "12345", "Left at home", counts=True)
    entries = _parse_loan_note_lines(line)
    assert len(entries) == 1
    assert entries[0] == {
        "date": date(2026, 8, 25),
        "asset_tag": "12345",
        "reason_label": "Left at home",
        "counts": True,
        "notes": "",
    }


def test_note_line_round_trip_excused():
    # e.g. the checkbox was unchecked, regardless of which reason was picked.
    line = _format_loan_note_line(date(2026, 8, 25), "12345", "Repair", counts=False)
    entries = _parse_loan_note_lines(line)
    assert entries[0]["counts"] is False


def test_note_line_round_trip_with_freeform_notes():
    line = _format_loan_note_line(
        date(2026, 8, 25), "12345", "Lost (maybe permanent)", counts=True,
        notes_text="Left it on the bus, checked lost and found already",
    )
    entries = _parse_loan_note_lines(line)
    assert entries[0]["notes"] == "Left it on the bus, checked lost and found already"


def test_note_line_round_trip_preserves_internal_newlines():
    # Multi-line notes are kept verbatim (each line prefixed for safe
    # parsing), not flattened -- so they read back the way they were typed.
    line = _format_loan_note_line(
        date(2026, 8, 25), "12345", "Other", counts=True, notes_text="line one\nline two\n\nline three",
    )
    entries = _parse_loan_note_lines(line)
    assert entries[0]["notes"] == "line one\nline two\n\nline three"


def test_parse_loan_note_lines_ignores_unrelated_text_between_entries():
    notes = (
        "Some unrelated note.\n"
        + _format_loan_note_line(date(2026, 8, 25), "12345", "Left at home", True)
        + "\nAnother note."
    )
    entries = _parse_loan_note_lines(notes)
    assert len(entries) == 1


def test_parse_loan_note_lines_unrelated_text_does_not_get_absorbed_as_notes():
    # A line that isn't prefixed as a continuation ends the entry above it
    # (and is itself ignored), so it can't get silently attributed as that
    # checkout's freeform notes.
    entry_with_notes = _format_loan_note_line(
        date(2026, 8, 25), "12345", "Lost (maybe permanent)", True, notes_text="Left on the bus",
    )
    notes = entry_with_notes + "\nUnrelated note added later by someone else."
    entries = _parse_loan_note_lines(notes)
    assert len(entries) == 1
    assert entries[0]["notes"] == "Left on the bus"


def test_parse_loan_note_lines_multiple_entries_each_keep_their_own_notes():
    notes = "\n".join([
        _format_loan_note_line(date(2026, 7, 10), "111", "Repair", False, notes_text="Screen cracked"),
        _format_loan_note_line(date(2026, 8, 25), "222", "Left at home", True),
    ])
    entries = _parse_loan_note_lines(notes)
    assert len(entries) == 2
    assert entries[0]["asset_tag"] == "111"
    assert entries[0]["notes"] == "Screen cracked"
    assert entries[1]["asset_tag"] == "222"
    assert entries[1]["notes"] == ""


def test_count_qualifying_since_cutoff_filters_excused_and_date():
    entries = [
        {"date": date(2026, 7, 1), "asset_tag": "1", "reason_label": "a", "counts": True},   # before cutoff
        {"date": date(2026, 8, 5), "asset_tag": "2", "reason_label": "b", "counts": True},   # counts
        {"date": date(2026, 8, 6), "asset_tag": "3", "reason_label": "c", "counts": False},  # excused (checkbox was off)
    ]
    assert _count_qualifying_since_cutoff(entries, cutoff=date(2026, 8, 1)) == 1


def test_count_qualifying_since_cutoff_none_cutoff_counts_all_time():
    entries = [
        {"date": date(2020, 1, 1), "asset_tag": "1", "reason_label": "a", "counts": True},
    ]
    assert _count_qualifying_since_cutoff(entries, cutoff=None) == 1


def test_determine_checkout_outcome_second_and_third_warn_fourth_overrides():
    assert _determine_checkout_outcome(1, True, max_before_override=3) == {
        "counts": True, "new_count": 2, "requires_warning": True,
        "requires_override": False, "requires_email": True,
    }
    assert _determine_checkout_outcome(2, True, max_before_override=3)["requires_warning"] is True
    outcome_fourth = _determine_checkout_outcome(3, True, max_before_override=3)
    assert outcome_fourth["requires_override"] is True
    assert outcome_fourth["requires_warning"] is False


def test_determine_checkout_outcome_email_covers_warning_and_override():
    # The 3rd checkout's warning email is really a "3rd or later" email --
    # every override past the limit should also trigger it by default.
    third = _determine_checkout_outcome(2, True, max_before_override=3)
    assert third["requires_warning"] is True
    assert third["requires_email"] is True

    fourth = _determine_checkout_outcome(3, True, max_before_override=3)
    assert fourth["requires_override"] is True
    assert fourth["requires_email"] is True

    tenth = _determine_checkout_outcome(9, True, max_before_override=3)
    assert tenth["requires_override"] is True
    assert tenth["requires_email"] is True


def test_determine_checkout_outcome_first_checkout_is_silent():
    outcome = _determine_checkout_outcome(0, True, max_before_override=3)
    assert outcome["new_count"] == 1
    assert outcome["requires_warning"] is False
    assert outcome["requires_override"] is False
    assert outcome["requires_email"] is False


def test_determine_checkout_outcome_unchecked_box_never_counts_or_warns():
    # Regardless of reason -- the checkbox is the sole source of truth.
    result = _determine_checkout_outcome(5, False, max_before_override=3)
    assert result["counts"] is False
    assert result["new_count"] == 5
    assert result["requires_warning"] is False
    assert result["requires_override"] is False
    assert result["requires_email"] is False


def test_valid_date_string_accepts_blank_and_real_dates():
    assert _valid_date_string("") is True
    assert _valid_date_string("2026-08-25") is True


def test_valid_date_string_rejects_garbage_and_impossible_dates():
    assert _valid_date_string("not-a-date") is False
    assert _valid_date_string("2026-13-40") is False
