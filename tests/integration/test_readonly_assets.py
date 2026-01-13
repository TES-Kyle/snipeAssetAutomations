"""Read-only integration tests for known safe asset tags."""

import os

import pytest

from utilities import otherApiBits as api


class DummyMessagebox:
    def showerror(self, title, message):
        return None


def _readonly_enabled():
    return os.environ.get("READONLY_NETWORK", "").lower() in ("1", "true", "yes", "on")


def _get_tags():
    raw = os.environ.get("READONLY_ASSET_TAGS", "").strip()
    if not raw:
        raw = "6057,6529,6249"
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


@pytest.mark.readonly_network
def test_readonly_asset_tags(monkeypatch):
    if not _readonly_enabled():
        pytest.skip("Set READONLY_NETWORK=1 to allow read-only GETs.")

    tags = _get_tags()
    if not tags:
        pytest.skip("No READONLY_ASSET_TAGS provided and no defaults available.")

    monkeypatch.setattr(api, "messagebox", DummyMessagebox())

    successes = 0
    for tag in tags:
        var_list, asset = api.getAssetInfo(tag, allow_missing=True)
        assert isinstance(var_list, list)
        assert isinstance(asset, dict)
        if asset.get("asset_tag") == tag:
            successes += 1
            assert asset.get("id") is not None

    if successes == 0:
        pytest.skip("No asset tags resolved; check READONLY_ASSET_TAGS.")


@pytest.mark.readonly_network
def test_readonly_asset_helpers(monkeypatch):
    if not _readonly_enabled():
        pytest.skip("Set READONLY_NETWORK=1 to allow read-only GETs.")

    tags = _get_tags()
    if not tags:
        pytest.skip("No READONLY_ASSET_TAGS provided and no defaults available.")

    monkeypatch.setattr(api, "messagebox", DummyMessagebox())

    var_list, asset = api.getAssetInfo(tags[0], allow_missing=True)
    if not asset.get("id"):
        pytest.skip("Asset id missing; cannot test helpers.")

    serial = asset.get("serial")
    if serial:
        assigned = api.getAssetInfoSerialAssignedTo(serial)
        assert assigned is None or isinstance(assigned, str)

    latest = api.getLatestCheckinName(asset["id"])
    assert latest is None or isinstance(latest, str)
