"""Tests for utilities.tk_thread -- the fix for a real, confirmed bug:
widget.after(0, callback) called directly from a background thread was
silently never invoked by this app's bundled Tcl/Tk 9.0.4 runtime (the
.after() call itself never raised; the callback just never ran). These
tests exercise the queue+poller workaround without needing a real Tk
display, matching this codebase's convention of not unit-testing actual
Tk window-building code.
"""

import threading
import time

from utilities import tk_thread


class _FakeWindow:
    """Runs .after() callbacks after a real (short) delay on their own
    daemon timer, like actual Tk does -- not synchronously inline, since
    the pump reschedules itself forever and a synchronous fake would
    recurse infinitely."""

    def __init__(self):
        self.exists = True

    def after(self, delay_ms, fn):
        timer = threading.Timer(max(delay_ms, 1) / 1000, fn)
        timer.daemon = True
        timer.start()

    def winfo_exists(self):
        return self.exists


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_run_on_tk_thread_executes_queued_callback():
    window = _FakeWindow()
    tk_thread.ensure_tk_thread_pump(window)

    calls = []
    tk_thread.run_on_tk_thread(window, lambda: calls.append("ran"))

    assert _wait_until(lambda: calls == ["ran"]), "queued callback never ran"


def test_run_on_tk_thread_executes_multiple_callbacks_in_order():
    window = _FakeWindow()
    tk_thread.ensure_tk_thread_pump(window)

    calls = []
    tk_thread.run_on_tk_thread(window, lambda: calls.append(1))
    tk_thread.run_on_tk_thread(window, lambda: calls.append(2))
    tk_thread.run_on_tk_thread(window, lambda: calls.append(3))

    assert _wait_until(lambda: calls == [1, 2, 3])


def test_ensure_tk_thread_pump_is_idempotent():
    window = _FakeWindow()
    tk_thread.ensure_tk_thread_pump(window)
    tk_thread.ensure_tk_thread_pump(window)  # must not start a second pump

    calls = []
    tk_thread.run_on_tk_thread(window, lambda: calls.append("ran"))

    assert _wait_until(lambda: calls == ["ran"])
    # Give any (incorrect) second pump a chance to double-fire before asserting.
    time.sleep(0.15)
    assert calls == ["ran"]


def test_callback_queued_after_window_destroyed_never_runs():
    window = _FakeWindow()
    tk_thread.ensure_tk_thread_pump(window)
    window.exists = False

    calls = []
    tk_thread.run_on_tk_thread(window, lambda: calls.append("ran"))

    # Nothing should ever drain this queue again once the window is gone --
    # give it a generous window to prove a negative.
    time.sleep(0.3)
    assert calls == []


def test_queued_callback_exception_does_not_stop_later_callbacks():
    window = _FakeWindow()
    tk_thread.ensure_tk_thread_pump(window)

    calls = []

    def _raises():
        raise ValueError("boom")

    tk_thread.run_on_tk_thread(window, _raises)
    tk_thread.run_on_tk_thread(window, lambda: calls.append("survived"))

    assert _wait_until(lambda: calls == ["survived"])
