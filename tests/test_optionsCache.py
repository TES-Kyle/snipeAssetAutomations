"""Tests for utilities.optionsCache (cache logic only -- start_live_refresh
is Tk-event-loop-driven and left for manual/integration testing, matching
this codebase's convention of not unit-testing Tk window-building code)."""

import threading

import pytest

import utilities.optionsCache as options_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache before and after each test."""
    options_cache.invalidate()
    yield
    options_cache.invalidate()


class _FakeClock:
    """Controllable stand-in for time.monotonic()."""

    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now


def test_get_options_fetches_and_caches(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(options_cache.time, "monotonic", clock)
    calls = []

    def fake_getter():
        calls.append(1)
        return [{"label": "A", "id": 1}]

    monkeypatch.setattr(options_cache, "_GETTERS", {"status": fake_getter})
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)

    result = options_cache.get_options("status")
    assert result == [{"label": "A", "id": 1}]
    assert len(calls) == 1

    # Second call within the TTL window should be a cache hit -- no refetch.
    result2 = options_cache.get_options("status")
    assert result2 == [{"label": "A", "id": 1}]
    assert len(calls) == 1


def test_get_options_refetches_after_ttl_expires(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(options_cache.time, "monotonic", clock)
    calls = []

    def fake_getter():
        calls.append(1)
        return [{"label": f"call-{len(calls)}"}]

    monkeypatch.setattr(options_cache, "_GETTERS", {"status": fake_getter})
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 10)

    options_cache.get_options("status")
    assert len(calls) == 1

    clock.now += 15  # advance past the 10s TTL
    options_cache.get_options("status")
    assert len(calls) == 2


def test_get_options_force_refresh_bypasses_ttl(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(options_cache.time, "monotonic", clock)
    calls = []

    def fake_getter():
        calls.append(1)
        return []

    monkeypatch.setattr(options_cache, "_GETTERS", {"status": fake_getter})
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)

    options_cache.get_options("status")
    options_cache.get_options("status", force_refresh=True)
    assert len(calls) == 2


def test_get_options_unknown_kind_raises():
    with pytest.raises(ValueError):
        options_cache.get_options("not-a-real-kind")


def test_get_options_none_from_getter_becomes_empty_list(monkeypatch):
    monkeypatch.setattr(options_cache, "_GETTERS", {"status": lambda: None})
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)
    assert options_cache.get_options("status") == []


def test_invalidate_specific_kind_only(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(options_cache.time, "monotonic", clock)
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)

    status_calls = []
    model_calls = []
    monkeypatch.setattr(options_cache, "_GETTERS", {
        "status": lambda: status_calls.append(1) or [],
        "model": lambda: model_calls.append(1) or [],
    })

    options_cache.get_options("status")
    options_cache.get_options("model")
    assert len(status_calls) == 1
    assert len(model_calls) == 1

    options_cache.invalidate("status")
    options_cache.get_options("status")  # re-fetches
    options_cache.get_options("model")   # still cached
    assert len(status_calls) == 2
    assert len(model_calls) == 1


def test_invalidate_all_kinds(monkeypatch):
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)
    calls = []
    monkeypatch.setattr(options_cache, "_GETTERS", {"status": lambda: calls.append(1) or []})

    options_cache.get_options("status")
    options_cache.invalidate()
    options_cache.get_options("status")
    assert len(calls) == 2


def test_ttl_seconds_uses_setting_value(monkeypatch):
    monkeypatch.setattr(options_cache, "get_settings", lambda: {"optionsCacheTtlSeconds": "42"})
    assert options_cache._get_ttl_seconds() == 42.0


def test_ttl_seconds_falls_back_to_default_on_invalid_setting(monkeypatch):
    monkeypatch.setattr(options_cache, "get_settings", lambda: {"optionsCacheTtlSeconds": "not-a-number"})
    assert options_cache._get_ttl_seconds() == 300.0


def test_ttl_seconds_never_negative(monkeypatch):
    monkeypatch.setattr(options_cache, "get_settings", lambda: {"optionsCacheTtlSeconds": "-50"})
    assert options_cache._get_ttl_seconds() == 0.0


def test_peek_returns_none_when_nothing_cached():
    assert options_cache.peek("status") is None


def test_peek_returns_cached_value_even_if_stale(monkeypatch):
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 10)
    options_cache._cache["status"] = {"data": [{"label": "stale"}], "fetched_at": -1_000_000.0}
    assert options_cache.peek("status") == [{"label": "stale"}]


class _FakeWidget:
    """Records set_options()/set_loading() calls in order, like a real AutoCompleteEntry would receive them."""

    def __init__(self):
        self.options_history = []
        self.loading_history = []

    def set_options(self, options):
        self.options_history.append(options)

    def set_loading(self, is_loading):
        self.loading_history.append(is_loading)


class _FakeWindow:
    """Stand-in for a Tk widget's .after() -- runs the callback after a
    real (short) delay on its own timer, like actual Tk does, rather than
    synchronously inline. load_widget's tk_thread pump reschedules itself
    via .after() forever (see utilities.tk_thread), so a synchronous fake
    would recurse infinitely; a real delay lets the background worker
    thread's queue.put() land before some later drain cycle picks it up,
    same as it would against a real Tk mainloop."""

    def __init__(self):
        self.done = threading.Event()

    def after(self, delay_ms, fn):
        def _run():
            fn()
            self.done.set()
        # daemon=True: the pump reschedules itself forever (matching real
        # Tk usage), so a non-daemon Timer would keep the process (and
        # pytest) alive indefinitely after the test itself finishes.
        timer = threading.Timer(max(delay_ms, 1) / 1000, _run)
        timer.daemon = True
        timer.start()

    def winfo_exists(self):
        return True


class _FakeDestroyedWindow(_FakeWindow):
    """Same as _FakeWindow, but simulates the window having been closed
    before the deferred callback runs -- the exact race a real macOS crash
    report traced to a segfault in Tcl's SetCmdNameFromAny (a .after()
    callback touching an already-destroyed widget)."""

    def winfo_exists(self):
        return False


def test_load_widget_shows_loading_only_when_nothing_cached_yet(monkeypatch):
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)
    monkeypatch.setattr(options_cache, "_GETTERS", {"status": lambda: [{"label": "A"}]})

    widget = _FakeWidget()
    window = _FakeWindow()
    options_cache.load_widget(window, "status", widget)
    assert window.done.wait(timeout=2), "load_widget's background thread never completed"

    assert widget.loading_history == [True, False]
    assert widget.options_history == [[{"label": "A"}]]


def test_load_widget_applies_stale_value_immediately_with_no_loading_state(monkeypatch):
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)
    options_cache._cache["status"] = {"data": [{"label": "stale"}], "fetched_at": -1_000_000.0}
    monkeypatch.setattr(options_cache, "_GETTERS", {"status": lambda: [{"label": "fresh"}]})

    widget = _FakeWidget()
    window = _FakeWindow()
    options_cache.load_widget(window, "status", widget)
    assert window.done.wait(timeout=2), "load_widget's background thread never completed"

    # Stale value applied synchronously (before the background fetch even
    # starts), then silently upgraded to the fresh value -- set_loading(True)
    # (the actual "loading…" placeholder) is never called, since something
    # usable was on screen the whole time.
    assert True not in widget.loading_history
    assert widget.options_history[0] == [{"label": "stale"}]
    assert widget.options_history[-1] == [{"label": "fresh"}]


def test_load_widget_applies_transform_to_both_stale_and_fresh_values(monkeypatch):
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)
    options_cache._cache["assignee"] = {
        "data": [{"type": "user", "label": "u1"}, {"type": "location", "label": "l1"}],
        "fetched_at": -1_000_000.0,
    }
    monkeypatch.setattr(options_cache, "_GETTERS", {
        "assignee": lambda: [{"type": "user", "label": "u2"}, {"type": "location", "label": "l2"}],
    })
    users_only = lambda opts: [o for o in opts if o["type"] == "user"]

    widget = _FakeWidget()
    window = _FakeWindow()
    options_cache.load_widget(window, "assignee", widget, transform=users_only)
    assert window.done.wait(timeout=2), "load_widget's background thread never completed"

    assert widget.options_history[0] == [{"type": "user", "label": "u1"}]
    assert widget.options_history[-1] == [{"type": "user", "label": "u2"}]


def test_load_widget_skips_applying_if_window_destroyed_before_callback_runs(monkeypatch):
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)
    monkeypatch.setattr(options_cache, "_GETTERS", {"status": lambda: [{"label": "A"}]})

    widget = _FakeWidget()
    window = _FakeDestroyedWindow()
    options_cache.load_widget(window, "status", widget)
    assert window.done.wait(timeout=2), "load_widget's background thread never completed"

    # Only the synchronous initial set_loading(True) (cache-miss path, run
    # before the background thread even starts) should have happened -- the
    # deferred on_tk_thread callback must bail out without touching the
    # widget once the window is gone, rather than touching a destroyed
    # widget.
    assert widget.loading_history == [True]
    assert widget.options_history == []


class _FakeAutoComplete:
    """Stand-in mirroring AutoCompleteEntry's set_options() invalidation
    logic: clears the current selection if it's not present in the new
    options (see utilities.autocomplete.AutoCompleteEntry.set_options)."""

    def __init__(self, text="", selected=None):
        self._text = text
        self._selected = selected
        self.options_history = []

    def get(self):
        return self._text

    def get_selected(self):
        return self._selected

    def set_options(self, options):
        self.options_history.append(options)
        if self._selected is not None and self._selected not in options:
            self._selected = None


def test_revalidate_for_submit_true_when_blank_skips_the_network_entirely(monkeypatch):
    def _boom():
        raise AssertionError("should not fetch for a blank field")

    monkeypatch.setattr(options_cache, "_GETTERS", {"status": _boom})
    widget = _FakeAutoComplete(text="", selected=None)
    assert options_cache.revalidate_for_submit("status", widget) is True
    assert widget.options_history == []  # set_options never called either


def test_revalidate_for_submit_true_when_selection_still_present(monkeypatch):
    monkeypatch.setattr(options_cache, "_GETTERS", {
        "status": lambda: [{"id": 5, "label": "Loan Fleet"}],
    })
    selected = {"id": 5, "label": "Loan Fleet"}
    widget = _FakeAutoComplete(text="Loan Fleet", selected=selected)
    assert options_cache.revalidate_for_submit("status", widget) is True


def test_revalidate_for_submit_false_when_selection_no_longer_present(monkeypatch):
    monkeypatch.setattr(options_cache, "_GETTERS", {
        "status": lambda: [{"id": 6, "label": "In Repair"}],  # "Loan Fleet" (id 5) is gone
    })
    selected = {"id": 5, "label": "Loan Fleet"}
    widget = _FakeAutoComplete(text="Loan Fleet", selected=selected)
    assert options_cache.revalidate_for_submit("status", widget) is False


def test_revalidate_for_submit_false_when_fetch_fails(monkeypatch):
    def _boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(options_cache, "_GETTERS", {"status": _boom})
    widget = _FakeAutoComplete(text="Loan Fleet", selected={"id": 5, "label": "Loan Fleet"})
    assert options_cache.revalidate_for_submit("status", widget) is False


def test_revalidate_for_submit_always_forces_a_fresh_fetch_even_within_ttl(monkeypatch):
    # The whole point: submit-time correctness beats avoiding an extra call,
    # so a still-within-TTL cached value isn't good enough on its own here.
    monkeypatch.setattr(options_cache, "_get_ttl_seconds", lambda: 300)
    options_cache._cache["status"] = {
        "data": [{"id": 5, "label": "Loan Fleet"}], "fetched_at": options_cache.time.monotonic(),
    }
    calls = []
    monkeypatch.setattr(options_cache, "_GETTERS", {
        "status": lambda: calls.append(1) or [{"id": 6, "label": "In Repair"}],
    })
    widget = _FakeAutoComplete(text="Loan Fleet", selected={"id": 5, "label": "Loan Fleet"})
    assert options_cache.revalidate_for_submit("status", widget) is False
    assert len(calls) == 1


def test_revalidate_for_submit_applies_transform(monkeypatch):
    monkeypatch.setattr(options_cache, "_GETTERS", {
        "assignee": lambda: [{"type": "user", "label": "u1"}, {"type": "location", "label": "l1"}],
    })
    users_only = lambda opts: [o for o in opts if o["type"] == "user"]
    widget = _FakeAutoComplete(text="u1", selected={"type": "user", "label": "u1"})
    assert options_cache.revalidate_for_submit("assignee", widget, transform=users_only) is True
    assert widget.options_history[-1] == [{"type": "user", "label": "u1"}]
