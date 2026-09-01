"""Shared TTL cache for the paginated Snipe-IT option-list getters.

getAllStatusOptions/getAllModelOptions/getAllAssigneeOptions (otherApiBits.py)
each do a full paginated fetch (all statuses, all models, all users +
locations). Every AutoCompleteEntry-backed picker across the app was
independently re-fetching all of that on every window open. This module
gives them one shared cache instead, so the common case (a second window
opened soon after the first) is instant instead of another full round trip.

Also provides start_live_refresh(), for the "reflected without closing
windows" requirement: while a window using cached options is open, it
polls in the background and pushes fresh data back into the window via a
callback -- but only while the window is focused, so a window merely left
open in the background doesn't spend API calls refreshing something
nobody's looking at. The loop stops itself once the window is destroyed.
"""

from __future__ import annotations

import logging
import threading
import time

from utilities.otherApiBits import getAllStatusOptions, getAllModelOptions, getAllAssigneeOptions
from utilities.settings import get_settings
from utilities.tk_thread import ensure_tk_thread_pump, run_on_tk_thread

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache = {}  # kind -> {"data": [...], "fetched_at": float (time.monotonic())}

# Kept as a module-level dict (rather than an if/elif chain) so tests can
# substitute fake getters without touching the real Snipe-IT API.
_GETTERS = {
    "status": getAllStatusOptions,
    "model": getAllModelOptions,
    "assignee": getAllAssigneeOptions,
}

_MIN_LIVE_REFRESH_INTERVAL_SECONDS = 5.0  # floor, regardless of settings


def _get_ttl_seconds() -> float:
    """Return the configured cache TTL in seconds.

    Also used as the default interval for start_live_refresh(), so there's
    one tunable knob rather than two separate settings to reason about.

    Returns:
        TTL in seconds (never negative).
    """
    settings = get_settings()
    try:
        return max(0.0, float(settings.get("optionsCacheTtlSeconds", 300)))
    except Exception:
        logger.warning("optionsCache: invalid optionsCacheTtlSeconds; defaulting to 300")
        return 300.0


def get_options(kind: str, force_refresh: bool = False):
    """Return cached options for kind, fetching fresh if missing/stale/forced.

    Args:
        kind: One of "status", "model", "assignee".
        force_refresh: If True, bypass the cache and fetch fresh regardless
            of TTL (used by start_live_refresh()'s periodic ticks).

    Returns:
        List of option dicts, in the same shape the underlying
        otherApiBits getter returns.
    """
    getter = _GETTERS.get(kind)
    if getter is None:
        raise ValueError(f"Unknown options kind: {kind!r}")

    now = time.monotonic()
    ttl = _get_ttl_seconds()

    with _lock:
        entry = _cache.get(kind)
        if not force_refresh and entry is not None and (now - entry["fetched_at"]) < ttl:
            logger.debug("get_options: cache hit for kind=%s (age=%.1fs)", kind, now - entry["fetched_at"])
            return entry["data"]

    # Fetch outside the lock -- this is a slow network call, and other
    # threads' cache reads/writes (for other kinds) shouldn't wait on it.
    logger.debug("get_options: cache miss/stale/forced for kind=%s; fetching", kind)
    data = getter() or []

    with _lock:
        _cache[kind] = {"data": data, "fetched_at": time.monotonic()}
    logger.info("get_options: refreshed kind=%s (%s options)", kind, len(data))
    return data


def peek(kind: str):
    """Return whatever's currently cached for kind, even if stale, without fetching.

    Used by load_widget() for stale-while-revalidate: showing a possibly-out-
    of-date value immediately is better than showing nothing while a fetch
    that might take a moment is in flight.

    Args:
        kind: One of "status", "model", "assignee".

    Returns:
        Cached list of option dicts (regardless of TTL), or None if nothing
        has been cached yet for this kind (e.g. first use since the app
        started).
    """
    with _lock:
        entry = _cache.get(kind)
    return entry["data"] if entry is not None else None


def invalidate(kind: str | None = None):
    """Clear the cache for one kind, or every kind if kind is None.

    Args:
        kind: One of "status", "model", "assignee", or None for all.
    """
    with _lock:
        if kind is None:
            _cache.clear()
        else:
            _cache.pop(kind, None)
    logger.debug("invalidate: kind=%s", kind or "all")


def filter_to_users(options):
    """Keep only the "user" entries from a mixed assignee-options list.

    Shared transform for every AutoCompleteEntry field that offers
    "assignee" options (users + locations, per getAllAssigneeOptions) but
    should only ever resolve to a person -- e.g. loan checkout's borrower
    field, checkoutTo's "Checkout To" field.

    Args:
        options: List of option dicts from get_options("assignee").

    Returns:
        Filtered list containing only entries with type == "user".
    """
    return [o for o in (options or []) if o.get("type") == "user"]


def load_widget(window, kind: str, widget, transform=None):
    """Populate an AutoCompleteEntry-like widget, stale-while-revalidate style.

    If anything is already cached for kind -- even stale -- it's applied to
    the widget immediately with no loading indicator, since a possibly-
    outdated list is more useful than a blank/disabled field. A background
    refresh always runs regardless (via get_options(), which only actually
    hits the network if the cache is missing/stale), and its result is
    applied the same way once it arrives -- also with no loading flicker.
    The "loading…" placeholder is reserved for the one case that actually
    needs it: nothing cached yet at all for this kind since the app started.

    Args:
        window: Tk widget whose .after() schedules the Tk-thread callback
            (usually the Toplevel the widget lives in).
        kind: One of "status", "model", "assignee".
        widget: An AutoCompleteEntry (or anything exposing set_options() and
            set_loading()).
        transform: Optional callable(list[dict]) -> list[dict] applied to
            the options before they're set on the widget (e.g. filtering
            assignees down to just users, or models down to just chargers).
    """
    ensure_tk_thread_pump(window)

    def _apply(options):
        widget.set_options(transform(options) if transform else options)

    cached = peek(kind)
    if cached is not None:
        # Something usable exists -- make sure the widget looks ready
        # (not stuck showing a stale "loading…" placeholder) right away.
        widget.set_loading(False)
        _apply(cached)
    else:
        widget.set_loading(True)

    def worker():
        """Fetch (cache-hit-or-real-fetch) off the Tk thread, then apply on it."""
        try:
            fresh = get_options(kind)
        except Exception:
            logger.exception("load_widget: failed to load kind=%s", kind)
            fresh = None

        def on_tk_thread():
            """Clear any loading state and apply fresh data, on the Tk thread."""
            logger.debug("load_widget: on_tk_thread INVOKED for kind=%s (window_exists=%s)", kind, window.winfo_exists())
            if not window.winfo_exists():
                # window.after() below only guards against the window
                # already being gone at scheduling time -- it can still be
                # destroyed in the gap between that and Tk actually running
                # this callback. Touching a destroyed widget unconditionally
                # here is confirmed (via a real macOS crash report, same
                # AfterProc/Tkapp_Call/SetCmdNameFromAny signature) to be
                # able to segfault the whole process, not just raise a
                # catchable Python exception.
                logger.debug("load_widget: window gone before applying kind=%s", kind)
                return
            widget.set_loading(False)
            if fresh is not None:
                _apply(fresh)
            logger.debug("load_widget: on_tk_thread COMPLETED for kind=%s", kind)

        logger.debug("load_widget: queuing on_tk_thread for kind=%s", kind)
        try:
            run_on_tk_thread(window, on_tk_thread)
            logger.debug("load_widget: on_tk_thread QUEUED for kind=%s", kind)
        except Exception:
            logger.debug("load_widget: window gone before applying kind=%s", kind)

    threading.Thread(target=worker, daemon=True).start()


def revalidate_for_submit(kind: str, widget, transform=None) -> bool:
    """Force a fresh fetch for kind and re-check widget's value against it.

    Always does a real (force_refresh=True) fetch -- at submit time,
    correctness matters more than avoiding one extra API call, and this is
    the one place mildly-stale-but-not-yet-expired cached data isn't good
    enough on its own: a form filled out in the moment right after a window
    opens could otherwise submit using data that's been sitting in the
    cache since long before this window existed (hours/days, if nothing
    happened to refresh that kind in the meantime). This call is
    synchronous/blocking -- same tradeoff the rest of this app already
    makes for submit-time API calls (e.g. call_with_retry).

    The widget's options are updated either way, so it reflects the
    freshest state and (via its own require_match styling) visibly flags
    if the previously chosen value no longer exists.

    Args:
        kind: One of "status", "model", "assignee".
        widget: An AutoCompleteEntry (or anything exposing get(),
            get_selected(), and set_options()) to revalidate.
        transform: Optional callable(list[dict]) -> list[dict], same as
            load_widget() -- must match whatever transform was used to load
            the widget originally, or "valid" options will look wrong.

    Returns:
        True if the field is blank (nothing to validate -- required-ness is
        the caller's job, and a blank optional field shouldn't block a
        submit over an unrelated network hiccup) or the fetch succeeded and
        the widget's current value still matches an option in the fresh
        list. False if there's non-blank text and the fetch failed, or the
        fresh data no longer contains a match.
    """
    text = widget.get().strip()
    if not text:
        return True

    try:
        fresh = get_options(kind, force_refresh=True)
    except Exception:
        logger.exception("revalidate_for_submit: fetch failed for kind=%s", kind)
        return False

    widget.set_options(transform(fresh) if transform else fresh)
    return widget.get_selected() is not None


def start_live_refresh(window, kind: str, on_update, interval_seconds: float | None = None):
    """Periodically refresh a cached options list while a window stays open.

    Schedules refreshes via the window's own Tk event loop (window.after()),
    so on_update always runs on the Tk thread -- callers don't need to
    marshal it themselves. The loop stops itself once the window is
    destroyed (window.after() raises once the underlying widget is gone).
    While the window isn't focused, ticks are skipped (no fetch, just
    rescheduled) so a window left open in the background doesn't spend API
    calls refreshing something nobody's currently looking at.

    Args:
        window: The Tk widget (usually a Toplevel) whose lifetime bounds
            the refresh loop, and whose focus state gates actual fetches.
        kind: One of "status", "model", "assignee".
        on_update: Callable(list[dict]) invoked with fresh options each
            time a refresh completes, on the Tk thread.
        interval_seconds: Poll interval; defaults to the configured cache
            TTL so refreshes line up with when the cache would go stale
            anyway. Floored at _MIN_LIVE_REFRESH_INTERVAL_SECONDS.
    """
    ensure_tk_thread_pump(window)

    interval_seconds = interval_seconds if interval_seconds is not None else _get_ttl_seconds()
    interval_ms = int(max(interval_seconds, _MIN_LIVE_REFRESH_INTERVAL_SECONDS) * 1000)

    focus_state = {"focused": True}

    def _on_focus_in(_e):
        focus_state["focused"] = True

    def _on_focus_out(_e):
        focus_state["focused"] = False

    try:
        window.bind("<FocusIn>", _on_focus_in, add="+")
        window.bind("<FocusOut>", _on_focus_out, add="+")
    except Exception:
        logger.debug("start_live_refresh: could not bind focus events for kind=%s", kind)

    def _refresh_in_background():
        """Fetch fresh data off the Tk thread, then apply it back on the Tk thread."""
        try:
            data = get_options(kind, force_refresh=True)
        except Exception:
            logger.exception("start_live_refresh: background fetch failed for kind=%s", kind)
            data = None

        def _apply_and_reschedule():
            """Push fresh data into the caller's callback and queue the next tick."""
            logger.debug(
                "start_live_refresh: _apply_and_reschedule INVOKED for kind=%s (window_exists=%s)",
                kind, window.winfo_exists(),
            )
            if not window.winfo_exists():
                # See load_widget's on_tk_thread for why this check exists:
                # window.after() below only catches the window already
                # being gone at scheduling time, not destroyed in the gap
                # before Tk runs this callback -- and on_update() touches
                # widgets (e.g. person_ac.set_options(...)), which can
                # segfault the process on a destroyed widget rather than
                # just raising.
                logger.debug("start_live_refresh: window gone before applying update for kind=%s", kind)
                return
            if data is not None:
                try:
                    on_update(data)
                except Exception:
                    logger.exception("start_live_refresh: on_update callback failed for kind=%s", kind)
            _schedule_next()
            logger.debug("start_live_refresh: _apply_and_reschedule COMPLETED for kind=%s", kind)

        logger.debug("start_live_refresh: queuing _apply_and_reschedule for kind=%s", kind)
        try:
            run_on_tk_thread(window, _apply_and_reschedule)
            logger.debug("start_live_refresh: _apply_and_reschedule QUEUED for kind=%s", kind)
        except Exception:
            logger.debug("start_live_refresh: window gone before applying update for kind=%s", kind)

    def _tick():
        """Fetch on a background thread if focused; otherwise just reschedule."""
        if focus_state["focused"]:
            threading.Thread(target=_refresh_in_background, daemon=True).start()
        else:
            logger.debug("start_live_refresh: window unfocused; skipping fetch for kind=%s", kind)
            _schedule_next()

    def _schedule_next():
        """Queue the next tick, or stop silently once the window is gone."""
        try:
            window.after(interval_ms, _tick)
        except Exception:
            logger.debug("start_live_refresh: window destroyed; stopping refresh loop for kind=%s", kind)

    _schedule_next()
