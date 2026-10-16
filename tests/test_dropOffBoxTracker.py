"""Tests for dropOff.apply_removals_to_state (tracker adjustments after box clean-up)."""

from assetManagementFunctions.dropOff import apply_removals_to_state, _init_default_state


def _state(**streams):
    st = _init_default_state(12)
    for code, (box, count) in streams.items():
        st["streams"][code] = {"box": box, "count": count}
    return st


def test_killed_stream_resets_to_fresh_state():
    st = _state(SG=(7, 5))
    changes = apply_removals_to_state(st, {"SG": {"killed": True, "removed_by_box": {7: 5}}})
    assert st["streams"]["SG"] == {"box": 1, "count": 0}
    assert len(changes) == 1


def test_removals_from_current_box_decrement_count():
    st = _state(SG=(5, 9))
    changes = apply_removals_to_state(st, {"SG": {"killed": False, "removed_by_box": {5: 4}}})
    assert st["streams"]["SG"] == {"box": 5, "count": 5}
    assert len(changes) == 1


def test_count_never_goes_below_zero():
    st = _state(SG=(5, 2))
    apply_removals_to_state(st, {"SG": {"killed": False, "removed_by_box": {5: 10}}})
    assert st["streams"]["SG"]["count"] == 0


def test_removals_from_older_boxes_change_nothing():
    st = _state(SG=(5, 9))
    changes = apply_removals_to_state(st, {"SG": {"killed": False, "removed_by_box": {3: 12, 4: 12}}})
    assert st["streams"]["SG"] == {"box": 5, "count": 9}
    assert changes == []


def test_only_touched_streams_change():
    st = _state(SG=(5, 9), WG=(2, 3))
    apply_removals_to_state(st, {"SG": {"killed": False, "removed_by_box": {5: 1}}})
    assert st["streams"]["WG"] == {"box": 2, "count": 3}


def test_killing_an_already_fresh_stream_reports_no_change():
    st = _state()
    assert apply_removals_to_state(st, {"SG": {"killed": True, "removed_by_box": {1: 1}}}) == []
