"""Tests for utilities.api_retry (pure control-flow logic, no real Tk/network).

Dialog functions are monkeypatched to canned answers rather than exercising
real Tk, since these tests run headless.
"""

import utilities.api_retry as api_retry


class FakeResponse:
    def __init__(self, status_code, json_data=None, text="raw text"):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def test_default_is_success_on_2xx_with_no_body():
    assert api_retry.default_is_success(FakeResponse(200, json_data=None))


def test_default_is_success_false_on_non_2xx():
    assert not api_retry.default_is_success(FakeResponse(500, json_data={"ok": True}))


def test_default_is_success_false_on_json_error_status_case_insensitive():
    assert not api_retry.default_is_success(FakeResponse(200, json_data={"status": "Error"}))
    assert not api_retry.default_is_success(FakeResponse(200, json_data={"status": "ERROR"}))


def test_call_with_retry_succeeds_first_try(monkeypatch):
    monkeypatch.setattr(api_retry, "ask_retry_cancel", lambda *a: (_ for _ in ()).throw(AssertionError("should not prompt")))
    result = api_retry.call_with_retry("Do thing", lambda: FakeResponse(200, json_data={"ok": True}))
    assert result == {"ok": True}


def test_call_with_retry_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(500, json_data={"status": "error"}, text="boom")
        return FakeResponse(200, json_data={"ok": True})

    monkeypatch.setattr(api_retry, "ask_retry_cancel", lambda title, msg: True)
    result = api_retry.call_with_retry("Do thing", fn)
    assert result == {"ok": True}
    assert calls["n"] == 2


def test_call_with_retry_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(api_retry, "ask_retry_cancel", lambda title, msg: False)
    result = api_retry.call_with_retry("Do thing", lambda: FakeResponse(500, text="boom"))
    assert result is None


def test_call_with_retry_exception_then_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(api_retry, "ask_retry_cancel", lambda title, msg: False)

    def fn():
        raise ConnectionError("network down")

    result = api_retry.call_with_retry("Do thing", fn)
    assert result is None


def test_call_with_retry_skip_returns_sentinel(monkeypatch):
    monkeypatch.setattr(api_retry, "ask_retry_skip_cancel", lambda title, msg: False)
    result = api_retry.call_with_retry("Do thing", lambda: FakeResponse(500, text="boom"), allow_skip=True)
    assert result is api_retry.SKIPPED


def test_call_with_retry_skip_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(api_retry, "ask_retry_skip_cancel", lambda title, msg: None)
    result = api_retry.call_with_retry("Do thing", lambda: FakeResponse(500, text="boom"), allow_skip=True)
    assert result is None


def test_call_with_retry_nonfatal_bypasses_dialog(monkeypatch):
    monkeypatch.setattr(api_retry, "ask_retry_cancel", lambda *a: (_ for _ in ()).throw(AssertionError("should not prompt")))
    resp = FakeResponse(400, json_data={"already": "checked in"})
    result = api_retry.call_with_retry(
        "Check in", lambda: resp,
        is_success=lambda r: 200 <= r.status_code < 300,
        is_nonfatal=lambda r: True,
    )
    assert result == {"already": "checked in"}


def test_call_with_retry_custom_is_success_skips_json_error_check(monkeypatch):
    # A response with a JSON status=="error" body should count as success
    # when is_success only checks the HTTP status code (matches dropOff.py's
    # functions, which never inspected the JSON body).
    monkeypatch.setattr(api_retry, "ask_retry_cancel", lambda *a: (_ for _ in ()).throw(AssertionError("should not prompt")))
    resp = FakeResponse(200, json_data={"status": "error"})
    result = api_retry.call_with_retry(
        "Do thing", lambda: resp,
        is_success=lambda r: 200 <= r.status_code < 300,
    )
    assert result == {"status": "error"}


def test_call_with_retry_busy_cursor_cleared_before_exception_dialog(monkeypatch):
    # The busy/watch cursor must be cleared BEFORE the retry dialog is shown
    # on an exception, not after -- otherwise the dialog would appear while
    # the cursor is still "busy", which is what consisterizer.py's original
    # hand-rolled implementations were careful to avoid.
    events = []

    class FakeWidget:
        def config(self, cursor):
            events.append(("cursor", cursor))

        def update_idletasks(self):
            pass

    def ask(title, msg):
        events.append(("dialog",))
        return False

    monkeypatch.setattr(api_retry, "ask_retry_cancel", ask)

    def fn():
        raise ConnectionError("network down")

    result = api_retry.call_with_retry("Do thing", fn, busy_widget=FakeWidget())
    assert result is None
    # Cursor is cleared once explicitly before the dialog (what we're
    # verifying here), then again via the finally block after -- a
    # redundant-but-harmless double-clear that matches the original
    # hand-rolled implementations' behavior.
    assert events == [("cursor", "watch"), ("cursor", ""), ("dialog",), ("cursor", "")]


def test_call_with_retry_busy_widget_toggled_around_each_attempt():
    calls = []

    class FakeWidget:
        def config(self, cursor):
            calls.append(cursor)

        def update_idletasks(self):
            pass

    result = api_retry.call_with_retry(
        "Do thing", lambda: FakeResponse(200, json_data={"ok": True}),
        busy_widget=FakeWidget(),
    )
    assert result == {"ok": True}
    assert calls == ["watch", ""]
