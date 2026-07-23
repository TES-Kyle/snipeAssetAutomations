"""Shared "call an API and retry on failure" helper.

Consolidates the "call an API, and on failure show a Retry/Cancel (or
Retry/Skip/Cancel) dialog, looping until success or give-up" pattern that
was previously hand-rolled ~10 times across consisterizer.py, newRepair.py,
and dropOff.py, each with slightly different wording and success checks.

Also home to the underlying Tk-safe dialog primitives (promoted from
utilities.jamfPrestageCommon, which needs them to be safe to call from
headless/background contexts too, since that module is also invoked from
Windmill jobs).
"""

import logging

logger = logging.getLogger(__name__)

try:
    import tkinter as _tk
    from tkinter import messagebox as _mb
    _TK_OK = True
except Exception:
    _tk = None
    _mb = None
    _TK_OK = False


SKIPPED = object()  # sentinel: user chose "Skip" (only reachable with allow_skip=True)


def ensure_tk_root():
    """Return the current Tk root (or a hidden root if none exists).

    Returns:
        Tk root window, or None when Tk is unavailable.
    """
    logger.debug("ensure_tk_root: _TK_OK=%s", _TK_OK)
    if not _TK_OK:
        logger.debug("ensure_tk_root: Tk not available, returning None")
        return None
    root = getattr(ensure_tk_root, "_root", None)
    try:
        if root is None or not root.winfo_exists():
            logger.debug("ensure_tk_root: no existing root; checking for default root")
            existing = getattr(_tk, "_default_root", None)
            if existing is not None and existing.winfo_exists():
                root = existing
                logger.debug("ensure_tk_root: reusing existing _default_root")
            else:
                root = _tk.Tk()
                root.withdraw()
                logger.debug("ensure_tk_root: created new hidden Tk root")
            ensure_tk_root._root = root
        return root
    except Exception:
        logger.debug("ensure_tk_root: exception while obtaining root; returning None")
        return None


def ask_retry_cancel(title: str, message: str) -> bool:
    """Show a retry/cancel dialog and return the user's choice.

    Falls back to False (cancel) when Tk is unavailable or headless.

    Args:
        title: Dialog window title.
        message: Question or error text to display.

    Returns:
        True when the user chooses Retry; False on Cancel or in headless mode.
    """
    try:
        root = ensure_tk_root()
        if root:
            return bool(_mb.askretrycancel(title, message, parent=root))
    except Exception:
        pass
    logger.warning("Prompt (no GUI): %s: %s -> cancel", title, message)
    return False


def ask_retry_skip_cancel(title: str, message: str):
    """Show a retry/skip/cancel dialog and return the user's choice.

    Falls back to None (cancel) when Tk is unavailable or headless.

    Args:
        title: Dialog window title.
        message: Question or error text to display.

    Returns:
        True to retry, False to skip, None to cancel/abort.
    """
    try:
        root = ensure_tk_root()
        if root:
            return _mb.askyesnocancel(title, message, parent=root)
    except Exception:
        pass
    logger.warning("Prompt (no GUI): %s: %s -> cancel", title, message)
    return None


def default_is_success(resp) -> bool:
    """Return True when resp is HTTP 2xx and not a Snipe-IT-style JSON error body.

    Args:
        resp: requests.Response object.

    Returns:
        True if the response indicates success.
    """
    if not (200 <= resp.status_code < 300):
        return False
    try:
        data = resp.json()
        if isinstance(data, dict) and str(data.get("status", "")).lower() == "error":
            return False
    except Exception:
        pass
    return True


def _parse_body(resp):
    """Best-effort JSON parse of a response, falling back to raw text.

    Args:
        resp: requests.Response object.

    Returns:
        Parsed JSON (usually a dict), or {"raw": <text>} if not JSON.
    """
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _set_busy(widget, on: bool) -> None:
    """Best-effort busy-cursor toggle on a Tk widget.

    Args:
        widget: Tk widget to toggle the cursor on.
        on: True to show a busy cursor, False to restore the default.
    """
    try:
        widget.config(cursor="watch" if on else "")
        widget.update_idletasks()
    except Exception:
        pass


def _ask_failure(op_name: str, message: str, allow_skip: bool):
    """Show the appropriate retry dialog variant for a failed attempt.

    Args:
        op_name: Human-readable operation name for the dialog title.
        message: Full dialog body text.
        allow_skip: Whether to offer Retry/Skip/Cancel instead of Retry/Cancel.

    Returns:
        True to retry; False to skip (allow_skip) or cancel (not allow_skip);
        None to cancel/abort (only reachable with allow_skip).
    """
    title = f"{op_name} failed"
    if allow_skip:
        return ask_retry_skip_cancel(title, message)
    return ask_retry_cancel(title, message)


def call_with_retry(op_name, fn, *, allow_skip=False, is_success=default_is_success,
                     is_nonfatal=None, busy_widget=None, detail_limit=500):
    """Call fn(), retrying via a dialog on failure until success or give-up.

    Args:
        op_name: Human-readable operation name used in dialog titles/messages
            (e.g. "Update asset 1234").
        fn: Zero-arg callable returning a requests.Response. Called once per
            attempt, so it's re-invoked (re-issuing the request) on retry.
        allow_skip: If True, failures offer Retry/Skip/Cancel instead of
            Retry/Cancel, and choosing Skip returns SKIPPED.
        is_success: Callable(resp) -> bool. Defaults to 2xx with no JSON
            status=="error" body.
        is_nonfatal: Optional callable(resp) -> bool. When given and it
            returns True for a failed response, that response is treated as
            success without prompting the user.
        busy_widget: Optional Tk widget to show a busy cursor on while each
            attempt is in flight.
        detail_limit: Max characters of response detail shown in the dialog.

    Returns:
        Parsed JSON body (dict, or {"raw": <text>} if not JSON) on success or
        non-fatal failure; SKIPPED if the user chose Skip; None if cancelled.
    """
    while True:
        try:
            if busy_widget is not None:
                _set_busy(busy_widget, True)
            resp = fn()
        except Exception as e:
            if busy_widget is not None:
                _set_busy(busy_widget, False)
            logger.exception("%s raised an exception", op_name)
            choice = _ask_failure(
                op_name,
                f"{op_name} raised an exception:\n{type(e).__name__}: {e}\n\nRetry?",
                allow_skip,
            )
            if choice is True:
                continue
            if choice is False and allow_skip:
                return SKIPPED
            return None
        finally:
            if busy_widget is not None:
                _set_busy(busy_widget, False)

        if is_success(resp):
            logger.info("%s succeeded", op_name)
            return _parse_body(resp)

        if is_nonfatal is not None and is_nonfatal(resp):
            logger.info("%s: non-fatal failure, treating as success", op_name)
            return _parse_body(resp)

        detail = str(_parse_body(resp))[:detail_limit]
        logger.error("%s failed (HTTP %s): %s", op_name, resp.status_code, detail)
        choice = _ask_failure(
            op_name,
            f"{op_name} failed (HTTP {resp.status_code}).\n{detail}\n\nRetry?",
            allow_skip,
        )
        if choice is True:
            continue
        if choice is False and allow_skip:
            return SKIPPED
        return None
