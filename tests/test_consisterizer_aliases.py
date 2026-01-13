"""Tests for Consisterizer aliases."""

from consisterizer import aliases


def test_bulk_checkin_alias_shape():
    alias = aliases.bulkCheckIn
    assert alias["batch_mode"] is True
    assert alias["maintain_defaults"] is True
    assert "set" in alias
    assert alias["set"].get("assigned_to") == "{empty}"
    assert "reset" in alias
