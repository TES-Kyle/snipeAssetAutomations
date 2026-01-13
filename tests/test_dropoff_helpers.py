"""Tests for drop-off helper functions."""

from assetManagementFunctions import dropOff


def test_get_dropoff_status_ids(monkeypatch):
    monkeypatch.setattr(dropOff, "get_settings", lambda: {"dropOffStatusId": "7", "dropOffPendingStatusId": "21"})
    drop_status, pending_status = dropOff._get_dropoff_status_ids()
    assert drop_status == 7
    assert pending_status == 21


def test_get_dropoff_field_keys_defaults(monkeypatch):
    monkeypatch.setattr(dropOff, "get_settings", lambda: {})
    charger_key, cord_key, box_key = dropOff._get_dropoff_field_keys()
    assert charger_key == "_snipeit_chargeringoodcondition_6"
    assert cord_key == "_snipeit_cordingoodcondition_11"
    assert box_key == "_snipeit_box_number_5"


def test_get_dropoff_field_keys_blank(monkeypatch):
    monkeypatch.setattr(
        dropOff,
        "get_settings",
        lambda: {
            "dropOffChargerFieldKey": " ",
            "dropOffCordFieldKey": "",
            "dropOffBoxFieldKey": "  ",
        },
    )
    charger_key, cord_key, box_key = dropOff._get_dropoff_field_keys()
    assert charger_key == "_snipeit_chargeringoodcondition_6"
    assert cord_key == "_snipeit_cordingoodcondition_11"
    assert box_key == "_snipeit_box_number_5"


def test_get_box_state_asset_tag_and_capacity(monkeypatch):
    monkeypatch.setattr(dropOff, "_load_settings", lambda: {"boxStateAssetTag": "BOX-1", "defaultBoxCapacity": "10"})
    tag, cap = dropOff._get_box_state_asset_tag_and_capacity()
    assert tag == "BOX-1"
    assert cap == 10


def test_get_box_state_asset_tag_capacity_clamps(monkeypatch):
    monkeypatch.setattr(dropOff, "_load_settings", lambda: {"boxStateAssetTag": "BOX-2", "defaultBoxCapacity": "-3"})
    tag, cap = dropOff._get_box_state_asset_tag_and_capacity()
    assert tag == "BOX-2"
    assert cap == 1
