"""Tests for otherManagementFunctions.boxNumberLogic (pure logic, no Tk/network)."""

import pytest

from otherManagementFunctions import boxNumberLogic as bl

STREAMS = ["SG", "SM", "SD", "WG", "WM", "WD"]


def _a(id_, box, tag=None):
    return {"id": id_, "tag": tag or str(id_), "name": f"n{id_}", "model": "m", "box": box}


@pytest.mark.parametrize("raw,expected", [
    ("SG-05", ("SG", 5)),
    ("sg-5", ("SG", 5)),
    (" WD-112 ", ("WD", 112)),
    ("12", None),
    ("SG05", None),
    ("SG-", None),
    ("SG-5b", None),
    ("S1G-05", None),
    ("", None),
    (None, None),
])
def test_parse_box_value(raw, expected):
    assert bl.parse_box_value(raw) == expected


def test_group_assets_hierarchy_counts_and_order():
    assets = [
        _a(1, "WG-10"), _a(2, "SG-02"), _a(3, "SG-2"), _a(4, "SG-10"),
        _a(5, "12"), _a(6, "3"), _a(7, "shelf A"), _a(8, "abc-01"),
    ]
    cats = bl.group_assets(assets)
    assert [c["label"] for c in cats] == ["ABC-XX", "SG-XX", "WG-XX", "N/A-XX"]
    sg = next(c for c in cats if c["key"] == "SG")
    assert sg["count"] == 3
    # SG-02 and SG-2 are the same box; numeric (not text) order puts 10 after 02.
    assert [(b["label"], len(b["assets"])) for b in sg["boxes"]] == [("SG-02", 2), ("SG-10", 1)]
    na = cats[-1]
    assert [b["label"] for b in na["boxes"]] == ["3", "12", "shelf A"]


def test_assets_within_a_box_sort_by_tag_numerically():
    cats = bl.group_assets([_a(1, "SG-01", "100"), _a(2, "SG-01", "20"), _a(3, "SG-01", "3")])
    assert [a["tag"] for a in cats[0]["boxes"][0]["assets"]] == ["3", "20", "100"]


def test_tracker_removals_partial_in_last_box():
    assets = [_a(1, "SG-04"), _a(2, "SG-05"), _a(3, "SG-05"), _a(4, "SG-05")]
    out = bl.tracker_removals(assets, {2, 3}, STREAMS)
    assert out == {"SG": {"killed": False, "removed_by_box": {5: 2}}}


def test_tracker_removals_kills_stream_only_when_nothing_left():
    assets = [_a(1, "SG-04"), _a(2, "SG-05"), _a(3, "WG-01")]
    out = bl.tracker_removals(assets, {1, 2}, STREAMS)
    assert out["SG"]["killed"] is True
    assert "WG" not in out


def test_tracker_removals_ignores_untracked_prefixes_and_malformed():
    assets = [_a(1, "ABC-01"), _a(2, "12"), _a(3, "SG-01")]
    assert bl.tracker_removals(assets, {1, 2}, STREAMS) == {}


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


def test_backoff_returns_success_and_definitive_4xx_without_retrying():
    calls = []
    assert bl.request_with_backoff(lambda: calls.append(1) or _Resp(200), sleep=lambda s: None).status_code == 200
    assert bl.request_with_backoff(lambda: calls.append(1) or _Resp(422), sleep=lambda s: None).status_code == 422
    assert len(calls) == 2


def test_backoff_retries_429_honouring_retry_after_then_succeeds():
    seq = [_Resp(429, {"Retry-After": "7"}), _Resp(200)]
    sleeps = []
    resp = bl.request_with_backoff(lambda: seq.pop(0), sleep=sleeps.append)
    assert resp.status_code == 200 and sleeps == [7.0]


def test_backoff_retries_exceptions_then_raises_last():
    def boom():
        raise OSError("down")
    sleeps = []
    with pytest.raises(OSError):
        bl.request_with_backoff(boom, attempts=3, sleep=sleeps.append)
    assert len(sleeps) == 2


def test_backoff_returns_last_5xx_after_exhausting_attempts():
    assert bl.request_with_backoff(lambda: _Resp(503), attempts=2, sleep=lambda s: None).status_code == 503
