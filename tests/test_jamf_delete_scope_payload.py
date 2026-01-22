"""Tests for Jamf prestage scope payload building."""

from utilities import jamfPrestageCommon as jd


def test_build_scope_payload_from_assignments_dict():
    scope = {
        "versionLock": 4,
        "assignments": {"serialNumbers": ["ABC", "DEF", "GHI"]},
    }
    payload, msg = jd._build_scope_put_payload(scope, "DEF")

    assert payload == {"serialNumbers": ["ABC", "GHI"], "versionLock": 4}
    assert "Doc-style prune" in msg


def test_build_scope_payload_from_assignments_list():
    scope = {
        "versionLock": 9,
        "assignments": [{"serialNumber": "AAA"}, {"serialNumber": "BBB"}],
    }
    payload, msg = jd._build_scope_put_payload(scope, "AAA")

    assert payload == {"serialNumbers": ["BBB"], "versionLock": 9}
    assert "Doc-style prune" in msg


def test_build_scope_payload_missing_assignments():
    payload, msg = jd._build_scope_put_payload({}, "AAA")
    assert payload is None
    assert "assignments" in msg


def test_build_scope_payload_serial_not_present():
    scope = {
        "versionLock": 4,
        "assignments": {"serialNumbers": ["ABC"]},
    }
    payload, msg = jd._build_scope_put_payload(scope, "XYZ")
    assert payload is None
    assert "Serial not present" in msg
