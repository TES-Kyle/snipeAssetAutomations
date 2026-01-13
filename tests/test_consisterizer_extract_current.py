"""Tests for Consisterizer current-value extraction."""

from consisterizer import consisterizer as c


def test_extract_current_values_username_from_email():
    asset = {
        "asset_tag": "1234",
        "name": "Device",
        "serial": "ABC",
        "assigned_to": {"name": "User Name", "email": "user@example.com"},
        "status_label": {"name": "Deployed"},
        "model": {"name": "Model X"},
        "purchase_date": {"date": "2025-01-01"},
        "expected_checkin": {"date": "2025-02-02"},
    }
    current = c.extract_current_values(asset)
    assert current["asset_tag"] == "1234"
    assert current["assigned_to"] == "User Name"
    assert current["_assigned_username"] == "user"
