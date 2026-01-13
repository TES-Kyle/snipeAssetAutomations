"""Tests for Jamf sync update helper."""

from otherManagementFunctions import jamfSync


class DummyResponse:
    def __init__(self):
        self.calls = []

    def raise_for_status(self):
        return None


class DummyJamfClient:
    def __init__(self):
        self.calls = []

    def pro_api_request(self, method, resource_path, data=None, override_headers=None):
        self.calls.append((method, resource_path, data, override_headers))
        return DummyResponse()


def test_update_jamf_asset_tag_computers():
    client = DummyJamfClient()
    jamfSync.update_jamf_asset_tag(client, 123, "TAG1", "computers")

    assert client.calls == [
        (
            "PATCH",
            "/v2/computers-inventory-detail/123",
            {"general": {"assetTag": "TAG1"}},
            {"Accept": "application/json"},
        )
    ]


def test_update_jamf_asset_tag_mobiledevices():
    client = DummyJamfClient()
    jamfSync.update_jamf_asset_tag(client, 456, "TAG2", "mobiledevices")

    assert client.calls == [
        (
            "PATCH",
            "/v2/mobile-devices/456",
            {"assetTag": "TAG2"},
            {"Accept": "application/json"},
        )
    ]


def test_update_jamf_asset_tag_invalid_endpoint():
    client = DummyJamfClient()
    jamfSync.update_jamf_asset_tag(client, 789, "TAG3", "bad")

    assert client.calls == []
