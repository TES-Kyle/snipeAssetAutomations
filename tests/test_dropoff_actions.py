"""Tests for drop-off action helpers that hit the API."""

from assetManagementFunctions import dropOff


class DummyMessagebox:
    def __init__(self):
        self.calls = []

    def askretrycancel(self, title, message):
        self.calls.append((title, message))
        return False

    def askyesno(self, title, message):
        self.calls.append((title, message))
        return True


class DummyResponse:
    def __init__(self, status_code=200, payload=None, text="ok"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_assign_from_remote_state_empty_notes(monkeypatch):
    notes_written = []

    monkeypatch.setattr(dropOff, "_get_box_state_asset_tag_and_capacity", lambda: ("BOX", 2))
    monkeypatch.setattr(dropOff, "_get_asset_by_tag_with_retry", lambda _tag: (True, {"id": "1", "notes": ""}))
    monkeypatch.setattr(dropOff, "_put_asset_notes_with_retry", lambda _id, notes: notes_written.append(notes) or True)

    ok, label = dropOff._assign_from_remote_state("SG", 2)

    assert ok is True
    assert label == "SG-01"
    assert any("SG box 1 computer 1" in note for note in notes_written)


def test_assign_from_remote_state_rolls_box(monkeypatch):
    state = dropOff._init_default_state(2)
    state["streams"]["SG"] = {"box": 1, "count": 2}
    notes = dropOff._format_state_notes(state)
    notes_written = []

    monkeypatch.setattr(dropOff, "_get_box_state_asset_tag_and_capacity", lambda: ("BOX", 2))
    monkeypatch.setattr(dropOff, "_get_asset_by_tag_with_retry", lambda _tag: (True, {"id": "1", "notes": notes}))
    monkeypatch.setattr(dropOff, "_put_asset_notes_with_retry", lambda _id, new_notes: notes_written.append(new_notes) or True)

    ok, label = dropOff._assign_from_remote_state("SG", 2)

    assert ok is True
    assert label == "SG-02"
    assert any("SG box 2 computer 1" in note for note in notes_written)


def test_checkin_asset_with_retry_accepts_already_checked_in(monkeypatch):
    monkeypatch.setattr(dropOff, "get_headers", lambda: {"Authorization": "token"})

    def fake_post(_url, json=None, headers=None, timeout=None):
        return DummyResponse(status_code=400, payload={"messages": "Already checked in"})

    monkeypatch.setattr(dropOff.requests, "post", fake_post)
    monkeypatch.setattr(dropOff, "messagebox", DummyMessagebox())

    ok = dropOff._checkin_asset_with_retry(123)

    assert ok is True


def test_update_asset_with_retry_payload(monkeypatch):
    captured = {}

    def fake_put(_url, json=None, headers=None, timeout=None):
        captured.update(json or {})
        return DummyResponse(status_code=200)

    monkeypatch.setattr(dropOff, "_get_dropoff_field_keys", lambda: ("chargerKey", "cordKey", "boxKey"))
    monkeypatch.setattr(dropOff, "get_headers", lambda: {"Authorization": "token"})
    monkeypatch.setattr(dropOff.requests, "put", fake_put)
    monkeypatch.setattr(dropOff, "messagebox", DummyMessagebox())

    ok = dropOff._update_asset_with_retry(
        1,
        "1234",
        5,
        10,
        "y",
        "n",
        "SG-01",
        "notes",
    )

    assert ok is True
    assert captured["chargerKey"] == "y"
    assert captured["cordKey"] == "n"
    assert captured["boxKey"] == "SG-01"
