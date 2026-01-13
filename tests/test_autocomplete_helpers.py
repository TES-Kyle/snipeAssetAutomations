"""Tests for AutoCompleteEntry helper logic."""

from utilities.autocomplete import AutoCompleteEntry


def test_subseq_pos_found():
    assert AutoCompleteEntry._subseq_pos("abcdef", "ace") == 0
    assert AutoCompleteEntry._subseq_pos("abcdef", "bd") == 1


def test_subseq_pos_not_found():
    assert AutoCompleteEntry._subseq_pos("abcdef", "gh") == -1
