"""Tests for consisterizer.saveStates (pure file-backed logic, no Tk)."""

import os

import pytest

from consisterizer import saveStates as ss


def _without_stamp(state):
    return {k: v for k, v in state.items() if k != "saved_at"}


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "saves.json")


def test_missing_file_means_no_saves(path):
    assert ss.list_names(path) == []
    assert ss.get_state("x", path) is None


def test_save_and_get_roundtrip(path):
    state = {"batch_mode": True, "set": {"status": "In Storage"}}
    assert ss.save_state("  Storage run ", state, path) == "Storage run"
    assert _without_stamp(ss.get_state("Storage run", path)) == state


def test_names_are_case_insensitive_and_overwrite_replaces(path):
    ss.save_state("Loaner", {"a": 1}, path)
    assert ss.name_exists("loaner", path)
    ss.save_state("loaner", {"a": 2}, path)
    assert ss.list_names(path) == ["loaner"]
    assert _without_stamp(ss.get_state("LOANER", path)) == {"a": 2}


def test_list_names_sorted_case_insensitively(path):
    for n in ("banana", "Apple", "cherry"):
        ss.save_state(n, {}, path)
    assert ss.list_names(path) == ["Apple", "banana", "cherry"]


def test_delete(path):
    ss.save_state("one", {}, path)
    assert ss.delete_state("ONE", path) is True
    assert ss.delete_state("one", path) is False
    assert ss.list_names(path) == []


def test_blank_name_rejected(path):
    with pytest.raises(ValueError):
        ss.save_state("   ", {}, path)


def test_corrupt_file_is_treated_as_empty_and_recoverable(path):
    with open(path, "w") as fh:
        fh.write("{not json")
    assert ss.list_names(path) == []
    ss.save_state("fresh", {}, path)
    assert ss.list_names(path) == ["fresh"]
    assert not [f for f in os.listdir(os.path.dirname(path)) if f.endswith(".tmp")]


def _stamp(path, name, saved_at):
    """Write a save with an explicit saved_at, bypassing the clock."""
    saves = ss._read_all(path)
    saves[name] = {"saved_at": saved_at}
    ss._write_all(path, saves)


def test_save_stamps_saved_at_without_mutating_the_input(path):
    state = {"batch_mode": True}
    ss.save_state("a", state, path)
    assert "saved_at" not in state
    assert ss.get_state("a", path)["saved_at"]


def test_sort_modes(path):
    _stamp(path, "banana", "2026-10-03T09:00:00")
    _stamp(path, "Apple", "2026-10-02T09:00:00")
    _stamp(path, "cherry", "2026-10-01T09:00:00")
    names = lambda mode: [n for n, _ in ss.list_entries(mode, path)]
    assert names(ss.SORT_ALPHA) == ["Apple", "banana", "cherry"]
    assert names(ss.SORT_NEWEST) == ["banana", "Apple", "cherry"]
    assert names(ss.SORT_OLDEST) == ["cherry", "Apple", "banana"]


def test_saves_without_timestamp_count_as_oldest_and_tie_alphabetically(path):
    _stamp(path, "zeta", "")
    _stamp(path, "alpha", "")
    _stamp(path, "new", "2026-10-05T09:00:00")
    names = lambda mode: [n for n, _ in ss.list_entries(mode, path)]
    assert names(ss.SORT_NEWEST) == ["new", "alpha", "zeta"]
    assert names(ss.SORT_OLDEST) == ["alpha", "zeta", "new"]
