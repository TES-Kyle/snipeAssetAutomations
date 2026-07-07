"""Shared Tk window-centering helper.

Every window-opening function in this project re-implemented the same
"center on screen" math by hand. This module gives them one place to call.

Usage::

    from utilities.tk_geometry import center_window

    # Size-to-content (window sizes itself from its widgets, then centers):
    center_window(win)

    # Fixed size (window is forced to WxH, then centered):
    center_window(win, width=600, height=400)
"""

import logging

logger = logging.getLogger(__name__)


def center_window(win, width=None, height=None):
    """Center a Tk window (Toplevel or root) on the screen.

    If width and height are given, the window is resized to that exact
    size before centering. Otherwise the window is centered at its
    current natural size (after letting pending geometry changes settle).

    Args:
        win: A Tk or Toplevel window to position.
        width: Optional fixed width in pixels.
        height: Optional fixed height in pixels.
    """
    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()

    if width is not None and height is not None:
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        logger.debug("center_window: fixed size %sx%s at x=%s y=%s", width, height, x, y)
        win.geometry(f"{width}x{height}+{x}+{y}")
    else:
        w = win.winfo_width()
        h = win.winfo_height()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        logger.debug("center_window: size-to-content %sx%s at x=%s y=%s", w, h, x, y)
        win.geometry(f"+{x}+{y}")
