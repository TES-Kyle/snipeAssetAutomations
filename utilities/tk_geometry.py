"""Shared Tk window-centering helper.

Every window-opening function in this project re-implemented the same
"center on screen" math by hand. This module gives them one place to call.

Usage::

    from utilities.tk_geometry import center_window

    # Size-to-content (window sizes itself from its widgets, then centers):
    center_window(win)

    # Fixed size (window is forced to WxH, then centered):
    center_window(win, width=600, height=400)

    # Centered within a sub-area of the screen, keeping clear of a dock/
    # taskbar/menu bar. Margins are pixels excluded from that edge:
    center_window(win, margin_bottom=120, margin_left=20, margin_right=20)
"""

import logging

logger = logging.getLogger(__name__)


def center_window(win, width=None, height=None,
                   margin_left=0, margin_right=0, margin_top=0, margin_bottom=0):
    """Center a Tk window (Toplevel or root) within the screen, or within a
    usable sub-area of the screen if margins are given.

    If width and height are given, the window is resized to that exact
    size before centering. Otherwise the window is centered at its current
    natural size (after letting pending geometry changes settle). Either
    way, the window is shrunk to fit if it's larger than the usable area
    (screen size minus margins).

    Margins carve out space to keep the window clear of docks, taskbars,
    or menu bars — e.g. margin_bottom=120 reserves 120px at the bottom of
    the screen that the window will never cover, and the window is
    centered within what's left rather than the full screen. All margins
    default to 0, which centers within the full screen exactly as before.

    Args:
        win: A Tk or Toplevel window to position.
        width: Optional fixed width in pixels.
        height: Optional fixed height in pixels.
        margin_left: Pixels to exclude from the left edge of the screen.
        margin_right: Pixels to exclude from the right edge of the screen.
        margin_top: Pixels to exclude from the top edge of the screen.
        margin_bottom: Pixels to exclude from the bottom edge of the screen.
    """
    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    usable_w = max(1, screen_w - margin_left - margin_right)
    usable_h = max(1, screen_h - margin_top - margin_bottom)

    if width is not None and height is not None:
        w = min(width, usable_w)
        h = min(height, usable_h)
        x = margin_left + (usable_w - w) // 2
        y = margin_top + (usable_h - h) // 2
        logger.debug(
            "center_window: fixed size %sx%s at x=%s y=%s (margins l=%s r=%s t=%s b=%s)",
            w, h, x, y, margin_left, margin_right, margin_top, margin_bottom,
        )
        win.geometry(f"{w}x{h}+{x}+{y}")
    else:
        w = win.winfo_width()
        h = win.winfo_height()
        if w > usable_w or h > usable_h:
            w = min(w, usable_w)
            h = min(h, usable_h)
            win.geometry(f"{w}x{h}")
            win.update_idletasks()
        x = margin_left + (usable_w - w) // 2
        y = margin_top + (usable_h - h) // 2
        logger.debug(
            "center_window: size-to-content %sx%s at x=%s y=%s (margins l=%s r=%s t=%s b=%s)",
            w, h, x, y, margin_left, margin_right, margin_top, margin_bottom,
        )
        win.geometry(f"+{x}+{y}")
