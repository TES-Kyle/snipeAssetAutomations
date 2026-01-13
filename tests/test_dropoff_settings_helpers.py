"""Tests for drop-off settings helpers."""

from assetManagementFunctions import dropOff


class DummyMessagebox:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def showerror(self, title, message):
        self.errors.append((title, message))

    def showwarning(self, title, message):
        self.warnings.append((title, message))


def test_get_dropoff_status_ids_defaults(monkeypatch):
    monkeypatch.setattr(dropOff, "get_settings", lambda: {})
    assert dropOff._get_dropoff_status_ids() == (5, 20)


def test_get_dropoff_status_ids_custom(monkeypatch):
    monkeypatch.setattr(
        dropOff,
        "get_settings",
        lambda: {"dropOffStatusId": "7", "dropOffPendingStatusId": "9"},
    )
    assert dropOff._get_dropoff_status_ids() == (7, 9)


def test_get_dropoff_field_keys_defaults(monkeypatch):
    monkeypatch.setattr(
        dropOff,
        "get_settings",
        lambda: {"dropOffChargerFieldKey": "", "dropOffCordFieldKey": " cord ", "dropOffBoxFieldKey": ""},
    )
    charger_key, cord_key, box_key = dropOff._get_dropoff_field_keys()
    assert charger_key == "_snipeit_chargeringoodcondition_6"
    assert cord_key == "cord"
    assert box_key == "_snipeit_box_number_5"


def test_get_box_state_asset_tag_and_capacity(monkeypatch):
    dummy_msg = DummyMessagebox()
    monkeypatch.setattr(dropOff, "messagebox", dummy_msg)
    monkeypatch.setattr(
        dropOff,
        "_load_settings",
        lambda: {"boxStateAssetTag": "BOX-STATE", "defaultBoxCapacity": "-2"},
    )

    tag, cap = dropOff._get_box_state_asset_tag_and_capacity()
    assert tag == "BOX-STATE"
    assert cap == 1
