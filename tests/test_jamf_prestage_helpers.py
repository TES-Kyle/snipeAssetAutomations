"""Tests for Jamf PreStage helper utilities."""

from assetManagementFunctions.jamfDeleteAndPreStage import _build_scope_put_payload


def test_build_scope_put_payload_dict_assignments():
    scope = {
        "versionLock": 3,
        "assignments": {"serialNumbers": ["ABC", "DEF"]},
    }
    payload, dbg = _build_scope_put_payload(scope, "ABC")
    assert payload == {"serialNumbers": ["DEF"], "versionLock": 3}
    assert "2->1" in dbg


def test_build_scope_put_payload_list_assignments():
    scope = {
        "versionLock": 7,
        "assignments": [{"serialNumber": "ABC"}, {"serialNumber": "XYZ"}],
    }
    payload, dbg = _build_scope_put_payload(scope, "XYZ")
    assert payload == {"serialNumbers": ["ABC"], "versionLock": 7}
    assert "2->1" in dbg


def test_build_scope_put_payload_serial_not_present():
    scope = {
        "versionLock": 5,
        "assignments": {"serialNumbers": ["ABC"]},
    }
    payload, dbg = _build_scope_put_payload(scope, "ZZZ")
    assert payload is None
    assert "Serial not present" in dbg


def test_build_scope_put_payload_invalid_scope():
    payload, dbg = _build_scope_put_payload("bad", "ABC")
    assert payload is None
    assert "Bad scope" in dbg
