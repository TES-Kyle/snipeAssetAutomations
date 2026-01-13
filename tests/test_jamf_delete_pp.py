"""Tests for jamfDeleteAndPreStage pretty-printer."""

from assetManagementFunctions import jamfDeleteAndPreStage as jd


def test_pp_truncates_long_text():
    long_text = "x" * 2000
    out = jd._pp(long_text, limit=100)
    assert out.endswith("…(truncated)…")


def test_pp_handles_dict():
    out = jd._pp({"a": 1})
    assert '"a": 1' in out
