"""Safe cross-thread hand-off to the Tk main thread.

widget.after(0, callback) called directly from a background thread was
confirmed -- via before/after diagnostic logging on a real deployed session,
not guesswork -- to silently never fire on this app's bundled Tcl/Tk 9.0.4
runtime: the .after() registration call itself returns normally (no
exception raised, nothing logged as failed), but Tcl's event loop simply
never invokes the callback. In the same session, a window's own
self-rescheduling .after() loop, issued FROM the Tk thread, kept firing
reliably every time. Every background-thread-to-Tk-widget hand-off in this
app (shared options loading, charger history, USB build progress, loan
checkout's per-person lookups) used the "call .after() straight from the
worker thread" pattern and was silently broken by it -- explaining reports
of "loading" placeholders and status text that looked stuck forever even
though the underlying fetch had long since finished.

Fix: never call .after() from a background thread again. A small poller,
bootstrapped via .after() from the Tk thread itself, drains a thread-safe
queue that background threads only ever queue.put() into.
"""

import logging
import queue

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 50

_queues = {}  # id(window) -> queue.Queue, one pump per window


def ensure_tk_thread_pump(window):
    """Start (if not already running) this window's Tk-thread poller.

    Must be called from the Tk thread -- typically right where a window is
    built, before starting any background thread that will later call
    run_on_tk_thread() for that same window. Safe to call more than once
    for the same window; only the first call actually starts anything.

    Args:
        window: The Tk widget (usually a Toplevel) whose lifetime bounds
            the pump. The pump stops itself once the window is destroyed.
    """
    key = id(window)
    if key in _queues:
        return
    q = _queues[key] = queue.Queue()

    def _drain():
        if not window.winfo_exists():
            _queues.pop(key, None)
            return
        while True:
            try:
                callback = q.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                logger.exception("tk_thread: queued callback raised")
        window.after(_POLL_INTERVAL_MS, _drain)

    window.after(_POLL_INTERVAL_MS, _drain)


def run_on_tk_thread(window, callback):
    """Queue callback to run on the Tk thread -- safe to call from any thread.

    Args:
        window: Same window previously passed to ensure_tk_thread_pump.
        callback: Zero-arg callable to run on the Tk thread.

    Raises:
        KeyError: ensure_tk_thread_pump was never called for this window.
    """
    _queues[id(window)].put(callback)
