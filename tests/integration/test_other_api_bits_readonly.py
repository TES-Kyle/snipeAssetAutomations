"""Read-only integration tests for options endpoints."""

import os

import pytest

from utilities import otherApiBits


def _readonly_enabled():
    return os.environ.get("READONLY_NETWORK", "").lower() in ("1", "true", "yes", "on")


@pytest.mark.readonly_network
def test_readonly_status_options():
    if not _readonly_enabled():
        pytest.skip("Set READONLY_NETWORK=1 to allow read-only GETs.")

    rows = otherApiBits.getAllStatusOptions()
    assert isinstance(rows, list)
    if not rows:
        pytest.skip("No status options returned; check API access.")

    for row in rows[:5]:
        assert isinstance(row, dict)
        assert "label" in row
        assert "id" in row


@pytest.mark.readonly_network
def test_readonly_assignee_options():
    if not _readonly_enabled():
        pytest.skip("Set READONLY_NETWORK=1 to allow read-only GETs.")

    rows = otherApiBits.getAllAssigneeOptions()
    assert isinstance(rows, list)
    if not rows:
        pytest.skip("No assignee options returned; check API access.")

    for row in rows[:5]:
        assert isinstance(row, dict)
        assert row.get("type") in ("user", "location")
        assert "label" in row
        assert "id" in row


@pytest.mark.readonly_network
def test_readonly_model_options():
    if not _readonly_enabled():
        pytest.skip("Set READONLY_NETWORK=1 to allow read-only GETs.")

    rows = otherApiBits.getAllModelOptions()
    assert isinstance(rows, list)
    if not rows:
        pytest.skip("No model options returned; check API access.")

    for row in rows[:5]:
        assert isinstance(row, dict)
        assert "label" in row
        assert "id" in row
