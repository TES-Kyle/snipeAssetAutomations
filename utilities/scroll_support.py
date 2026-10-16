"""Shared mousewheel/trackpad scroll wiring for scrollable tk.Canvas widgets.

Two real bugs found and fixed here (both confirmed via debug logging on a
real deployed session, same class of issue as the tk_thread.py background-
thread bug -- surprising Tk runtime behavior, not application logic):

1. A widget's default bindtags chain is (widget, class, toplevel, "all") --
   a canvas is not in that chain just because a widget happens to live
   inside it. bind_all()/<Enter>/<Leave>-based scroll bindings rely on that
   chain and don't reliably deliver the event to a canvas's descendants in
   this app's Tk runtime. Binding directly on every widget in the subtree
   sidesteps propagation entirely.

2. macOS trackpad two-finger scroll does not fire <MouseWheel> at all in
   this app's bundled Tk 9.0.4 -- only a native Scrollbar responded (through
   its own platform-level handling, not a Tcl virtual event). Tk 9 (TIP 684)
   added a separate <TouchpadScroll> event specifically for high-resolution
   trackpad panning on macOS/Windows; that's the one that actually needs
   binding for trackpad users.
"""

from __future__ import annotations

import logging
import tkinter as tk

logger = logging.getLogger(__name__)

# Discrete mouse wheel (real wheel, or Linux Button-4/5): pixels per notch.
PIXELS_PER_WHEEL_NOTCH = 30


def bind_canvas_scroll(canvas: tk.Canvas, subtree_root: tk.Misc | None = None):
    """Wire mousewheel + trackpad scrolling onto canvas and all its descendants.

    Call this once, after the canvas's full widget subtree has been built --
    it walks winfo_children() at call time and won't pick up anything added
    to the tree afterward.

    Sets canvas's yscrollincrement to 1px so scroll amounts (both the fixed
    per-notch amount for a real wheel, and the raw per-event delta from a
    trackpad) can be expressed directly in pixels instead of Tk's much
    coarser, unset-by-default "unit" size -- that mismatch is what made
    trackpad scrolling feel jerky/chunky before this was set explicitly.

    Scrolling is a no-op while the canvas content already fits entirely in
    view, so a short list never wobbles or reveals empty canvas.

    Args:
        canvas: The scrollable canvas to wire up.
        subtree_root: Bind only this widget and its descendants instead of the
            whole canvas. For a canvas whose contents are rebuilt after the
            first call: bind the canvas once, then call again with each newly
            created widget so earlier widgets don't get duplicate handlers.
    """
    canvas.configure(yscrollincrement=1)

    def _on_mousewheel(event):
        """Scroll from a discrete mouse wheel (<MouseWheel>/Button-4/5)."""
        logger.debug("_on_mousewheel: num=%s, delta=%s", event.num, event.delta)
        if canvas.yview() == (0.0, 1.0):
            return
        if event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-PIXELS_PER_WHEEL_NOTCH, "units")
        elif event.num == 5 or event.delta < 0:
            canvas.yview_scroll(PIXELS_PER_WHEEL_NOTCH, "units")

    def _on_touchpad_scroll(event):
        """Scroll from a Tk 9 <TouchpadScroll> event (macOS/Windows trackpad).

        Fires roughly 60x/second with small packed X/Y deltas (TIP 684),
        unpacked via Tk's own tk::PreciseScrollDeltas helper. Scrolled
        directly per-event (no extra accumulation) now that yscrollincrement
        is 1px, so motion tracks the trackpad 1:1 instead of in chunks.
        """
        if canvas.yview() == (0.0, 1.0):
            return
        try:
            _dx, dy = canvas.tk.call("tk::PreciseScrollDeltas", event.delta)
            dy = int(dy)
        except Exception:
            logger.debug("_on_touchpad_scroll: could not unpack delta=%s", event.delta)
            return
        if dy:
            logger.debug("_on_touchpad_scroll: dy=%s", dy)
            canvas.yview_scroll(-dy, "units")

    def _bind_recursive(widget):
        widget.bind("<MouseWheel>", _on_mousewheel, add="+")
        widget.bind("<Button-4>", _on_mousewheel, add="+")
        widget.bind("<Button-5>", _on_mousewheel, add="+")
        widget.bind("<TouchpadScroll>", _on_touchpad_scroll, add="+")
        for child in widget.winfo_children():
            _bind_recursive(child)

    _bind_recursive(subtree_root if subtree_root is not None else canvas)
    logger.debug("bind_canvas_scroll: wired scroll handling for canvas=%s", canvas)


def bind_text_scroll(text: tk.Text):
    """Wire mousewheel + trackpad scrolling onto a tk.Text widget.

    Same two Tk 9 quirks as bind_canvas_scroll (module docstring): a trackpad
    only fires <TouchpadScroll>, and the discrete wheel needs binding
    directly on the widget. A Text already has its own class-level wheel
    binding, so these handlers return "break" to stop it scrolling a second
    time. Scrolls in pixels, and does nothing while all the content fits.

    Args:
        text: The Text widget to wire up (bind once; no subtree to walk).
    """
    def _on_mousewheel(event):
        if text.yview() != (0.0, 1.0):
            if event.num == 4 or event.delta > 0:
                text.yview_scroll(-PIXELS_PER_WHEEL_NOTCH, "pixels")
            elif event.num == 5 or event.delta < 0:
                text.yview_scroll(PIXELS_PER_WHEEL_NOTCH, "pixels")
        return "break"

    def _on_touchpad_scroll(event):
        if text.yview() != (0.0, 1.0):
            try:
                _dx, dy = text.tk.call("tk::PreciseScrollDeltas", event.delta)
                dy = int(dy)
            except Exception:
                logger.debug("bind_text_scroll: could not unpack delta=%s", event.delta)
                return "break"
            if dy:
                text.yview_scroll(-dy, "pixels")
        return "break"

    text.bind("<MouseWheel>", _on_mousewheel)
    text.bind("<Button-4>", _on_mousewheel)
    text.bind("<Button-5>", _on_mousewheel)
    text.bind("<TouchpadScroll>", _on_touchpad_scroll)
    logger.debug("bind_text_scroll: wired scroll handling for text=%s", text)
