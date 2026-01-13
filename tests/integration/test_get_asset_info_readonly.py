"""Read-only integration tests for Snipe-IT GETs."""

import os

import pytest

from utilities.otherApiBits import getAssetInfo


@pytest.mark.readonly_network
def test_get_asset_info_readonly():
    asset_tag = os.environ.get("READONLY_ASSET_TAG", "").strip()
    if os.environ.get("READONLY_NETWORK", "").lower() not in ("1", "true", "yes", "on"):
        pytest.skip("Set READONLY_NETWORK=1 to allow read-only GETs.")
    if not asset_tag:
        pytest.skip("Set READONLY_ASSET_TAG to run read-only integration tests.")
    var_list, asset_data = getAssetInfo(asset_tag, allow_missing=True)
    assert isinstance(var_list, list)
    assert isinstance(asset_data, dict)
