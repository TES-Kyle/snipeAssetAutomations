"""Tests for otherApiBits logging behavior."""

import logging

from utilities import otherApiBits


def test_log_asset_data_info(monkeypatch, caplog):
    monkeypatch.setattr(otherApiBits, "get_settings", lambda: {"logAssetData": "1"})
    caplog.set_level(logging.INFO, logger=otherApiBits.logger.name)
    otherApiBits._log_asset_data("1234", {"id": 1})
    assert any(
        rec.levelno == logging.INFO and "Asset data for 1234" in rec.message
        for rec in caplog.records
        if rec.name == otherApiBits.logger.name
    )


def test_log_asset_data_debug(monkeypatch, caplog):
    monkeypatch.setattr(otherApiBits, "get_settings", lambda: {"logAssetData": "0"})
    caplog.set_level(logging.DEBUG, logger=otherApiBits.logger.name)
    otherApiBits._log_asset_data("5678", {"id": 2})
    assert any(
        rec.levelno == logging.DEBUG and "Asset data for 5678" in rec.message
        for rec in caplog.records
        if rec.name == otherApiBits.logger.name
    )
