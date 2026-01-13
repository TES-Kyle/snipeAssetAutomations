"""Tests for drop-off settings path and default parsing."""

import os

from assetManagementFunctions import dropOff


def test_settings_path_ends_with_settings_json():
    path = dropOff._settings_path()
    assert path.endswith(os.path.join("utilities", "settings.json"))


def test_get_dropoff_status_ids_invalid_values(monkeypatch):
    monkeypatch.setattr(dropOff, "get_settings", lambda: {"dropOffStatusId": "x", "dropOffPendingStatusId": "y"})
    drop_status, pending_status = dropOff._get_dropoff_status_ids()
    assert drop_status == 5
    assert pending_status == 20
