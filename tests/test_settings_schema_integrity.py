"""Tests to validate settings schema consistency."""

import json
import os


def _load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_settings_schema_keys_exist_in_defaults():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    defaults_path = os.path.join(root, "utilities", "defaultSettings.json")
    schema_path = os.path.join(root, "utilities", "settingsSchema.json")

    defaults = _load_json(defaults_path)
    schema = _load_json(schema_path)

    keys = []
    for group in schema.get("groups", []):
        for item in group.get("items", []):
            key = item.get("key")
            assert key
            keys.append(key)
            assert key in defaults
            assert item.get("label")
            assert "description" in item

    assert len(keys) == len(set(keys))
