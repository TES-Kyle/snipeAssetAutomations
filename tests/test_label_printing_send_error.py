"""Tests for label printing error handling."""

import json

from utilities import labelPrinting


class _Printer:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def test_send_to_printer_handles_error(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({
        "printerType": "QL-720NW",
        "labelName": "62",
        "labelsPerPrint": "1",
        "printerIP": "tcp://1.2.3.4:9100",
    }))

    monkeypatch.setattr(labelPrinting, "BrotherQLRaster", _Printer)
    monkeypatch.setattr(labelPrinting.brother_ql, "brother_ql_create", type("X", (), {"convert": lambda *a, **k: ["DATA"]})())
    def _raise(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(labelPrinting, "send", _raise)

    def fake_open(*_args, **_kwargs):
        class _F:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *_):
                return False
            def read(self_inner):
                return settings_path.read_text()
        return _F()

    called = {"count": 0}
    monkeypatch.setattr(
        labelPrinting,
        "messagebox",
        type("X", (), {"showerror": lambda *a, **k: called.__setitem__("count", called["count"] + 1)}),
    )
    monkeypatch.setattr("builtins.open", fake_open)

    labelPrinting.sendToPrinter(str(tmp_path / "file.jpg"))
    assert called["count"] == 1
