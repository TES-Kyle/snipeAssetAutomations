"""Tests for Jamf sync device processing."""

from otherManagementFunctions import jamfSync


class DummyGeneral:
    def __init__(self, asset_tag=None, name=None, display_name=None):
        self.assetTag = asset_tag
        self.name = name
        self.displayName = display_name


class DummyHardware:
    def __init__(self, serial=None):
        self.serialNumber = serial


class DummyComputer:
    def __init__(self, device_id, serial, asset_tag, name="Device"):
        self.id = device_id
        self.hardware = DummyHardware(serial)
        self.general = DummyGeneral(asset_tag=asset_tag, name=name)


class DummyMobile:
    def __init__(self, device_id, serial, asset_tag, name="Mobile"):
        self.mobileDeviceId = device_id
        self.hardware = DummyHardware(serial)
        self.general = DummyGeneral(asset_tag=asset_tag, display_name=name)


class DummyProApi:
    def __init__(self, computers=None, mobiles=None):
        self._computers = computers or []
        self._mobiles = mobiles or []

    def get_computer_inventory_v1(self, sections=None, page_size=None):
        return self._computers

    def get_mobile_device_inventory_v2(self, sections=None, page_size=None):
        return self._mobiles


class DummyJamfClient:
    def __init__(self, pro_api):
        self.pro_api = pro_api


def test_process_devices_updates_when_live(monkeypatch):
    device = DummyComputer(device_id=1, serial="ABC123", asset_tag="OLD")
    jamf_client = DummyJamfClient(DummyProApi(computers=[device]))

    calls = []
    monkeypatch.setattr(jamfSync, "search_snipe_asset_by_serial", lambda _s: {"asset_tag": "NEW"})
    monkeypatch.setattr(
        jamfSync,
        "update_jamf_asset_tag",
        lambda _client, device_id, new_tag, endpoint: calls.append((device_id, new_tag, endpoint)),
    )
    monkeypatch.setattr(jamfSync, "DRY_RUN", False)
    monkeypatch.setattr(jamfSync, "TEST_MODE_SERIAL", "")

    jamfSync.process_devices(jamf_client, "computers")

    assert calls == [(1, "NEW", "computers")]


def test_process_devices_skips_when_tags_match(monkeypatch):
    device = DummyComputer(device_id=2, serial="ABC124", asset_tag="MATCH")
    jamf_client = DummyJamfClient(DummyProApi(computers=[device]))

    calls = []
    monkeypatch.setattr(jamfSync, "search_snipe_asset_by_serial", lambda _s: {"asset_tag": "MATCH"})
    monkeypatch.setattr(
        jamfSync,
        "update_jamf_asset_tag",
        lambda _client, device_id, new_tag, endpoint: calls.append((device_id, new_tag, endpoint)),
    )
    monkeypatch.setattr(jamfSync, "DRY_RUN", False)
    monkeypatch.setattr(jamfSync, "TEST_MODE_SERIAL", "")

    jamfSync.process_devices(jamf_client, "computers")

    assert calls == []


def test_process_devices_dry_run_skips_update(monkeypatch):
    device = DummyMobile(device_id=3, serial="MOB123", asset_tag="OLD")
    jamf_client = DummyJamfClient(DummyProApi(mobiles=[device]))

    calls = []
    monkeypatch.setattr(jamfSync, "search_snipe_asset_by_serial", lambda _s: {"asset_tag": "NEW"})
    monkeypatch.setattr(
        jamfSync,
        "update_jamf_asset_tag",
        lambda _client, device_id, new_tag, endpoint: calls.append((device_id, new_tag, endpoint)),
    )
    monkeypatch.setattr(jamfSync, "DRY_RUN", True)
    monkeypatch.setattr(jamfSync, "TEST_MODE_SERIAL", "")

    jamfSync.process_devices(jamf_client, "mobiledevices")

    assert calls == []


def test_process_devices_test_mode_allows_only_matching_serial(monkeypatch):
    device = DummyComputer(device_id=4, serial="SERIAL1", asset_tag="OLD")
    jamf_client = DummyJamfClient(DummyProApi(computers=[device]))

    calls = []
    monkeypatch.setattr(jamfSync, "search_snipe_asset_by_serial", lambda _s: {"asset_tag": "NEW"})
    monkeypatch.setattr(
        jamfSync,
        "update_jamf_asset_tag",
        lambda _client, device_id, new_tag, endpoint: calls.append((device_id, new_tag, endpoint)),
    )
    monkeypatch.setattr(jamfSync, "DRY_RUN", False)
    monkeypatch.setattr(jamfSync, "TEST_MODE_SERIAL", "OTHER")

    jamfSync.process_devices(jamf_client, "computers")

    assert calls == []


def test_process_devices_skips_when_serial_missing(monkeypatch):
    device = DummyComputer(device_id=5, serial=None, asset_tag="OLD")
    jamf_client = DummyJamfClient(DummyProApi(computers=[device]))

    monkeypatch.setattr(
        jamfSync,
        "search_snipe_asset_by_serial",
        lambda _s: (_ for _ in ()).throw(AssertionError("search should not be called")),
    )

    jamfSync.process_devices(jamf_client, "computers")


def test_process_devices_skips_when_snipe_asset_missing(monkeypatch):
    device = DummyComputer(device_id=6, serial="ABC999", asset_tag="OLD")
    jamf_client = DummyJamfClient(DummyProApi(computers=[device]))

    calls = []
    monkeypatch.setattr(jamfSync, "search_snipe_asset_by_serial", lambda _s: None)
    monkeypatch.setattr(
        jamfSync,
        "update_jamf_asset_tag",
        lambda _client, device_id, new_tag, endpoint: calls.append((device_id, new_tag, endpoint)),
    )

    jamfSync.process_devices(jamf_client, "computers")

    assert calls == []


def test_process_devices_skips_when_snipe_asset_tag_missing(monkeypatch):
    device = DummyComputer(device_id=7, serial="ABC888", asset_tag="OLD")
    jamf_client = DummyJamfClient(DummyProApi(computers=[device]))

    calls = []
    monkeypatch.setattr(jamfSync, "search_snipe_asset_by_serial", lambda _s: {"asset_tag": ""})
    monkeypatch.setattr(
        jamfSync,
        "update_jamf_asset_tag",
        lambda _client, device_id, new_tag, endpoint: calls.append((device_id, new_tag, endpoint)),
    )

    jamfSync.process_devices(jamf_client, "computers")

    assert calls == []


def test_process_devices_mobile_update_live(monkeypatch):
    device = DummyMobile(device_id=8, serial="MOB555", asset_tag="OLD")
    jamf_client = DummyJamfClient(DummyProApi(mobiles=[device]))

    calls = []
    monkeypatch.setattr(jamfSync, "search_snipe_asset_by_serial", lambda _s: {"asset_tag": "NEW"})
    monkeypatch.setattr(
        jamfSync,
        "update_jamf_asset_tag",
        lambda _client, device_id, new_tag, endpoint: calls.append((device_id, new_tag, endpoint)),
    )
    monkeypatch.setattr(jamfSync, "DRY_RUN", False)
    monkeypatch.setattr(jamfSync, "TEST_MODE_SERIAL", "")

    jamfSync.process_devices(jamf_client, "mobiledevices")

    assert calls == [(8, "NEW", "mobiledevices")]
