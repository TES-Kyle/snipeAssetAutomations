"""Tests for api_user static name persistence."""

import json
import os

from utilities import api_user


def test_set_api_user_static_name_writes(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"apiUserStaticName": "John"}))

    monkeypatch.setattr(api_user, "configure_logging", lambda: None)
    monkeypatch.setattr(api_user.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(api_user.os.path, "realpath", lambda _p: str(settings_path))
    monkeypatch.setattr(api_user.os.path, "dirname", lambda _p: str(tmp_path))

    ok = api_user.set_api_user_static_name("none")
    assert ok is True
    data = json.loads(settings_path.read_text())
    assert data["apiUserStaticName"] == "none"
