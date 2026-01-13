"""Tests for printSelected behavior."""

from assetManagementFunctions import printSelected as ps


def test_print_selected_with_args(monkeypatch):
    called = {"values": None}
    monkeypatch.setattr(ps, "createImage", lambda values: called.update({"values": values}))
    result = ps.printSelected("1234", ["A", "B"])
    assert called["values"] == ["A", "B"]
    assert "custom fields" in result.lower()


def test_print_selected_fallback(monkeypatch):
    called = {"values": None}

    def fake_get_asset_info(tag):
        return [], {"asset_tag": tag}

    monkeypatch.setattr(ps, "createImage", lambda values: called.update({"values": values}))
    monkeypatch.setattr(ps, "getAssetInfo", fake_get_asset_info)
    result = ps.printSelected("5555")
    assert called["values"] == ["5555"]
    assert "asset tag only" in result.lower()
