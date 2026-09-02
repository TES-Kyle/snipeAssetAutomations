"""Autocomplete Tk widget used across GUI forms."""

import logging
import tkinter as tk
from tkinter import ttk

from utilities.theme import get_ui_colors

logger = logging.getLogger(__name__)

_IGNORE_KEYS = {
    "Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R",
    "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Caps_Lock", "Escape", "Return",
    "Up", "Down", "Left", "Right", "Home", "End", "Prior", "Next", "Insert",
}

# Grace period between the cursor leaving the entry/popup and the popup
# actually hiding -- long enough for real mouse transit between the entry
# and the separate popup Toplevel below it (see _maybe_hide_later).
_HIDE_DELAY_MS = 400


def _label_matches_any_option(text, options):
    """Return True if text exactly matches some option's label.

    Pure/testable core of AutoCompleteEntry's require_match styling: a
    field is only ever flagged invalid because of this check, kept
    separate from the widget so it doesn't need a live Tk display to test.

    Args:
        text: Candidate text (should already be stripped by the caller).
        options: Iterable of option dicts with "label" keys.

    Returns:
        True if any option's label equals text exactly, or if text is empty
        (an empty field isn't a mismatched value, just an absent one).
    """
    if not text:
        return True
    return any(opt.get("label") == text for opt in options)


class AutoCompleteEntry(ttk.Frame):
    """Reusable autocomplete Entry with popup Listbox (auto-height up to 5 items).

    Public API:
      - set_options(list[dict]): each dict must include {"label": str, ...}
      - get() -> str (visible text)
      - set(text: str)
      - get_selected() -> dict | None (last committed selection)
      - bind_change(callback) -> called on text change or selection

    Keyboard:
      - typing filters results (printable keys only)
      - Tab cycles suggestions while popup is visible
      - Enter selects highlighted
      - Esc hides popup

    The popup appears on typing or hover and hides on selection or when
    focus leaves both the entry and popup.
    """

    def __init__(self, parent, *, width=40, require_match=True):
        """Initialize the entry and popup listbox widgets.

        Args:
            parent: Tk parent widget.
            width: Entry width in characters.
            require_match: If True (the default -- currently true for every
                field in the app), the entry shows a red/invalid style
                whenever it holds non-blank text that doesn't exactly match
                a current option's label -- including a previously valid
                selection that set_options() later drops (e.g. because it
                was deleted in Snipe-IT and a refresh no longer includes
                it). Set False for fields that intentionally accept
                free-text values outside the option list (e.g.
                consisterizer's "{empty}" sentinel for clearing an
                assignment).
        """
        logger.debug("AutoCompleteEntry.__init__: parent=%s, width=%s, require_match=%s", parent, width, require_match)
        super().__init__(parent)

        # Read once per widget (not per call) -- get_ui_colors() shells out
        # to `defaults read` on macOS, and this widget is created many
        # times per window.
        self._theme = get_ui_colors()

        # Classic tk.Frame (not ttk) wrapping just the Entry, so the
        # invalid-value indicator is a colored highlight border rather than
        # a ttk style tweak: ttk's Aqua theme (macOS) silently ignores
        # fieldbackground/bordercolor customization on ttk.Entry in
        # practice, but a classic widget's highlightbackground/
        # highlightthickness are drawn by Tk itself and always render.
        # (Also avoids fighting over self.entry's own `style` option, which
        # at least one caller -- consisterizer.py -- already uses for an
        # unrelated highlight of its own.)
        # Thickness is fixed from the start (not toggled) so the widget's
        # footprint never changes size -- only the border *color* toggles,
        # matching the background (invisible) when valid.
        self._entry_wrap = tk.Frame(self, highlightthickness=2)
        self._entry_wrap.grid(row=0, column=0, sticky="ew")
        self._valid_border_color = self._entry_wrap.cget("highlightbackground")

        self.entry = ttk.Entry(self._entry_wrap, width=width)
        self.entry.pack(fill="both", expand=True)
        self.grid_columnconfigure(0, weight=1)
        self.advance_focus_on_select = True
        self.require_match = require_match

        self._all_options = []   # [{"label": str, ...}, ...]
        self._matches = []       # current top matches
        self._selected = None
        self._change_cbs = []
        self._hover_open = False
        self._loading = False

        # Popup with listbox (no scrollbar)
        self.popup = tk.Toplevel(self)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.attributes("-topmost", True)
        self.popup.transient(self.winfo_toplevel())

        self.listbox = tk.Listbox(self.popup, height=0, activestyle="dotbox")
        self.listbox.pack(side="left", fill="both", expand=True)

        # Entry bindings
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<FocusOut>", self._maybe_hide_later)
        self.entry.bind("<Enter>", self._on_hover_entry)
        self.entry.bind("<Leave>", self._on_leave_entry)

        self.entry.bind("<Tab>", self._on_tab, add="+")
        self.entry.bind("<ISO_Left_Tab>", self._on_tab, add="+")  # Shift+Tab on some X11
        self.entry.bind("<Return>", self._on_return, add="+")
        self.entry.bind("<Escape>", lambda e: (self.hide_popup(), "break"))

        # Popup bindings
        self.listbox.bind("<Button-1>", self._on_click_select)
        self.listbox.bind("<Return>", self._on_return_listbox)
        self.listbox.bind("<Escape>", lambda e: (self.hide_popup(), "break"))
        self.listbox.bind("<FocusOut>", self._maybe_hide_later)
        self.listbox.bind("<Leave>", self._on_leave_popup)
        self.listbox.bind("<Enter>", self._on_enter_popup)

        # Keep popup width aligned with entry
        self.entry.bind("<Configure>", lambda e: self._place_popup())

        self._update_validity_style()

    # ---------- Public API ----------
    def set_options(self, options):
        """Replace the autocomplete option list.

        If the currently selected option is no longer present in the new
        list (e.g. a live-refresh dropped it), the selection is cleared --
        get_selected() should never keep returning something that's not
        actually in the current option list.

        Args:
            options: Iterable of dicts with a "label" key.
        """
        self._all_options = list(options or [])
        logger.debug("AutoCompleteEntry.set_options: %s options loaded", len(self._all_options))
        if self._selected is not None and self._selected not in self._all_options:
            logger.debug("AutoCompleteEntry.set_options: previously selected option no longer present; clearing")
            self._selected = None
        self._update_validity_style()

    def get(self) -> str:
        """Return the current entry text."""
        result = self.entry.get()
        logger.debug("AutoCompleteEntry.get: returning %s", result)
        return result

    def set(self, text: str):
        """Set the entry text and fire change callbacks.

        Args:
            text: New text to insert.
        """
        logger.debug("AutoCompleteEntry.set: text=%s", text)
        self.entry.delete(0, tk.END)
        if text:
            self.entry.insert(0, text)
        self._fire_change()

    def get_selected(self):
        """Return the last committed option dict or None."""
        logger.debug("AutoCompleteEntry.get_selected: selected=%s", (self._selected or {}).get("label"))
        return self._selected

    def bind_change(self, callback):
        """Register a callback to run when the entry changes.

        Args:
            callback: Callable invoked on text or selection changes.
        """
        logger.debug("AutoCompleteEntry.bind_change: registering callback %s", callback)
        if callable(callback):
            self._change_cbs.append(callback)

    def set_loading(self, is_loading: bool, text: str = "loading…"):
        """Show or clear a disabled grey loading placeholder in the entry.

        Common pattern for options populated from a background thread:
        show this while the fetch is in flight, then clear it once
        set_options() has real data. Callers can check is_loading() to
        block submission while it's still showing.

        Args:
            is_loading: True to show the placeholder and disable typing;
                False to clear it, restore normal styling, and re-enable.
            text: Placeholder text to show while is_loading is True.
        """
        logger.debug("AutoCompleteEntry.set_loading: is_loading=%s text=%s", is_loading, text)
        self._loading = is_loading
        try:
            if is_loading:
                self.entry.configure(foreground=self._theme["muted_fg"])
                self.entry.delete(0, tk.END)
                self.entry.insert(0, text)
                self.entry.state(["disabled"])
            else:
                self.entry.state(["!disabled"])
                self.entry.delete(0, tk.END)
                self.entry.configure(foreground=self._theme["entry_fg"])
        except Exception:
            pass

    def is_loading(self) -> bool:
        """Return True while the loading placeholder is showing."""
        return self._loading

    def set_selected_by_label(self, label: str):
        """Programmatically set entry + selected option by exact label match.

        Args:
            label: Exact label string to match and select.
        """
        logger.debug("AutoCompleteEntry.set_selected_by_label: label=%s", label)
        if not label:
            logger.debug("AutoCompleteEntry.set_selected_by_label: empty label, clearing selection")
            self._selected = None
            self.set("")  # fires change
            return
        for opt in self._all_options:
            if opt.get("label") == label:
                logger.debug("AutoCompleteEntry.set_selected_by_label: exact match found for %s", label)
                self._selected = opt
                self.set(label)  # fires change
                return
        # no exact match -> treat as plain text
        logger.debug("AutoCompleteEntry.set_selected_by_label: no exact match; treating as plain text label=%s", label)
        self._selected = None
        self.set(label)

    def commit_selection(self):
        """Commit selection based on current listbox cursor (if visible)."""
        logger.debug("AutoCompleteEntry.commit_selection: popup_visible=%s, matches=%s", self._popup_visible(), len(self._matches))
        if not self._popup_visible() or not self._matches:
            # try to map current entry text to an option
            txt = self.get().strip()
            logger.debug("AutoCompleteEntry.commit_selection: popup not visible; mapping text=%s to option", txt)
            for opt in self._all_options:
                if opt.get("label") == txt:
                    self._selected = opt
                    logger.debug("AutoCompleteEntry.commit_selection: matched text to option label=%s", txt)
                    break
            return
        self._commit_selection()


    def hide_popup(self, restore_focus: bool = True):
        """Hide the popup listbox and optionally restore focus."""
        try:
            # release any implicit grabs some Tk variants might take for a transient Toplevel
            try:
                self.popup.grab_release()
            except Exception:
                pass
            self.popup.withdraw()
        except Exception:
            pass
        if restore_focus:
            try:
                self.winfo_toplevel().focus_force()
            except Exception:
                pass


    # ---------- Internals ----------
    def _fire_change(self):
        """Invoke change callbacks with best-effort isolation."""
        self._update_validity_style()
        # Isolate callback failures to keep the widget responsive.
        for cb in self._change_cbs:
            try: cb()
            except Exception: pass

    def _update_validity_style(self):
        """Apply/clear the invalid-value indicator based on require_match.

        Runs on every text/selection change (via _fire_change) and every
        set_options() call, so a value that was fine when picked but later
        stops matching (a live-refresh removed it) gets flagged the moment
        that happens -- not just at some later submit-time check.

        Only touches _entry_wrap's highlight border, deliberately never
        self.entry's own ttk `style` option: at least one caller
        (consisterizer.py) already uses that same attribute on the same
        widget for an unrelated highlight (its own default-mismatch
        indicator), and fighting over one shared attribute would make
        whichever call happened last silently win.
        """
        if not self.require_match:
            return
        text = self.entry.get().strip()
        is_invalid = not _label_matches_any_option(text, self._all_options)
        # Thickness is never touched here (fixed at construction) so the
        # widget never changes size when this toggles -- only the color
        # does, blending into the background when valid.
        border_color = self._theme["error_fg"] if is_invalid else self._valid_border_color
        try:
            self._entry_wrap.configure(highlightbackground=border_color, highlightcolor=border_color)
        except Exception:
            logger.debug("AutoCompleteEntry._update_validity_style: failed to set border color")

    def _on_key(self, e):
        """Handle key release events and refresh matches."""
        logger.debug("AutoCompleteEntry._on_key: keysym=%s", e.keysym)
        # ignore non-text keys so Tab/Enter etc. don’t reset selection
        if e.keysym in _IGNORE_KEYS:
            logger.debug("AutoCompleteEntry._on_key: ignored keysym=%s", e.keysym)
            return
        self._selected = None
        logger.debug("AutoCompleteEntry._on_key: selection cleared, requerying")
        self._requery_and_show()
        self._fire_change()

    def _on_hover_entry(self, _e):
        """Open the popup when hovering over the entry."""
        logger.debug("AutoCompleteEntry._on_hover_entry: hover opened")
        self._hover_open = True
        self._requery_and_show()

    def _on_leave_entry(self, _e):
        """Schedule popup hide when leaving the entry."""
        logger.debug("AutoCompleteEntry._on_leave_entry: hover closed, scheduling hide")
        self._hover_open = False
        self._maybe_hide_later()

    def _on_enter_popup(self, _e):
        """Track hover state when entering the popup."""
        logger.debug("AutoCompleteEntry._on_enter_popup: cursor entered popup")
        self._hover_open = True

    def _on_leave_popup(self, _e):
        """Schedule popup hide when leaving the popup."""
        logger.debug("AutoCompleteEntry._on_leave_popup: cursor left popup, scheduling hide")
        self._hover_open = False
        self._maybe_hide_later()

    def _maybe_hide_later(self, _e=None):
        """Delay popup hide to allow focus changes.

        The popup is a separate Toplevel positioned below the entry (see
        _place_popup), so moving the mouse from the entry down into it
        always crosses a moment where the cursor is over neither widget --
        <Leave> fires on the entry before <Enter> fires on the popup. 120ms
        was too tight a window for that real mouse transit on at least one
        deployed machine: the popup hid itself before the click landed,
        repeatedly, which is exactly what made picking a person look like
        it was stuck for tens of seconds (confirmed via debug-log
        timestamps -- _on_click_select simply never fired across several
        hover/hide cycles).
        """
        logger.debug("AutoCompleteEntry._maybe_hide_later: scheduling hide in %sms", _HIDE_DELAY_MS)
        self.after(_HIDE_DELAY_MS, self._maybe_hide_now)

    def _maybe_hide_now(self):
        """Hide the popup if neither entry nor popup has focus."""
        if not self.winfo_exists():
            # The whole widget (and its window) can be destroyed in the gap
            # between _maybe_hide_later scheduling this and it actually
            # running -- touching self.entry/self.listbox unconditionally
            # in that case is a real, confirmed SIGSEGV (Tcl segfaulting
            # resolving a destroyed widget's command from a stale .after()
            # callback), not just a catchable Python exception.
            return
        has_focus = (self.focus_get() in (self.entry, self.listbox))
        logger.debug("AutoCompleteEntry._maybe_hide_now: has_focus=%s, hover_open=%s", has_focus, self._hover_open)
        if not has_focus and not self._hover_open:
            logger.debug("AutoCompleteEntry._maybe_hide_now: hiding popup")
            self.hide_popup()

    def _on_tab(self, e):
        """Cycle the highlighted suggestion when the popup is visible."""
        logger.debug("AutoCompleteEntry._on_tab: popup_visible=%s, matches=%s", self._popup_visible(), len(self._matches))
        if not self._popup_visible():
            return  # let normal focus traversal happen
        if not self._matches:
            return "break"
        cur = self.listbox.curselection()
        idx = (cur[0] + 1) % len(self._matches) if cur else 0
        logger.debug("AutoCompleteEntry._on_tab: advancing to index=%s", idx)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.activate(idx)
        self.listbox.see(idx)
        return "break"

    def _on_return(self, _e):
        """Commit the current selection on Enter."""
        logger.debug("AutoCompleteEntry._on_return: popup_visible=%s", self._popup_visible())
        if not self._popup_visible():
            return
        self._commit_selection()
        return "break"

    def _on_return_listbox(self, _e):
        """Commit the current selection from the listbox."""
        logger.debug("AutoCompleteEntry._on_return_listbox: committing selection from listbox")
        self._commit_selection()
        return "break"

    def _on_click_select(self, e):
        """Select the clicked item and commit it."""
        logger.debug("AutoCompleteEntry._on_click_select: y=%s", e.y)
        # ensure we select the clicked row
        i = self.listbox.nearest(e.y)
        logger.debug("AutoCompleteEntry._on_click_select: nearest row index=%s", i)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(i)
        self.listbox.activate(i)
        self._commit_selection()
        return "break"

    def _commit_selection(self):
        """Finalize the current selection and optionally advance focus."""
        sel = self.listbox.curselection()
        if not sel and self._matches:
            idx = 0
        elif not sel:
            self.hide_popup()
            return
        else:
            idx = sel[0]
        opt = self._matches[idx]
        logger.debug("AutoCompleteEntry._commit_selection: selecting index %s (%s)", idx, opt.get("label"))
        # Persist the selected option and reflect it in the entry.
        self._selected = opt
        self.set(opt["label"])  # already fires change callbacks -- see below
        self.hide_popup()

        try:
            # Move focus to the next widget if configured.
            if self.advance_focus_on_select:
                nxt = self.tk_focusNext()
                if nxt:
                    nxt.focus_set()
            else:
                self.winfo_toplevel().focus_force()
        except Exception:
            pass

        # No second self._fire_change() here: set() above already fired
        # change callbacks with the final state (self._selected is set
        # before set() runs). A second call here doubled every bound
        # callback's work on every single commit -- e.g. loanCheckout's
        # on_person_change spawning two redundant background API fetches
        # per person picked, worsening contention right when the shared
        # assignee list is also still loading.

    def _requery_and_show(self):
        """Recompute matches and render the popup listbox."""
        q = self.entry.get().strip().lower()
        logger.debug("AutoCompleteEntry._requery_and_show: query=%s", q)
        self._matches = self._top_matches(q, limit=5)
        logger.debug("AutoCompleteEntry._requery_and_show: %s matches found", len(self._matches))

        if not self._matches:
            logger.debug("AutoCompleteEntry._requery_and_show: no matches; hiding popup")
            self.hide_popup(restore_focus=False)
            return

        self.listbox.delete(0, tk.END)
        for opt in self._matches:
            self.listbox.insert(tk.END, opt["label"])
        logger.debug("AutoCompleteEntry._requery_and_show: listbox populated with %s entries", len(self._matches))

        # resize listbox to #matches (<=5)
        h = max(1, min(len(self._matches), 5))
        logger.debug("AutoCompleteEntry._requery_and_show: setting listbox height=%s", h)
        try:
            self.listbox.configure(height=h)
        except Exception:
            pass

        self.listbox.selection_clear(0, "end")
        self.listbox.activate(0)
        self.listbox.selection_set(0)
        self._place_popup()
        self.show_popup()

    def _place_popup(self):
        """Position the popup just below the entry widget."""
        if not self._popup_visible() and not self._matches:
            return
        try:
            x = self.entry.winfo_rootx()
            y = self.entry.winfo_rooty() + self.entry.winfo_height()
            w = self.entry.winfo_width()
            # let tk compute natural height
            self.popup.update_idletasks()
            h = self.popup.winfo_reqheight()
            logger.debug("AutoCompleteEntry._place_popup: geometry width=%s height=%s x=%s y=%s", max(200, w), h, x, y)
            self.popup.geometry(f"{max(200, w)}x{h}+{x}+{y}")
        except Exception:
            pass

    def show_popup(self):
        """Show and raise the popup listbox."""
        try:
            self.popup.deiconify()
            self.popup.lift()
        except Exception:
            pass


    def _popup_visible(self):
        """Return True if the popup is currently visible."""
        return self.popup.state() != "withdrawn"

    # ------ matching ------
    def _top_matches(self, q, limit=5):
        """Return top matching options for the given query.

        Args:
            q: Lowercased query string.
            limit: Maximum number of options to return.

        Returns:
            Ordered list of option dicts.
        """
        logger.debug("AutoCompleteEntry._top_matches: q=%s, options=%s, limit=%s", q, len(self._all_options), limit)
        if not self._all_options:
            logger.debug("AutoCompleteEntry._top_matches: no options loaded; returning []")
            return []

        if not q:
            result = sorted(self._all_options, key=lambda o: o["label"].lower())[:limit]
            logger.debug("AutoCompleteEntry._top_matches: empty query; returning first %s alphabetically", len(result))
            return result

        def score(opt):
            """Return a tuple used to rank match quality."""
            label = opt["label"].lower()
            if label.startswith(q):
                return (0, len(label))
            pos = label.find(q)
            if pos != -1:
                return (1 + pos, len(label))
            subseq_pos = self._subseq_pos(label, q)
            if subseq_pos != -1:
                return (100 + subseq_pos, len(label))
            return (10_000, len(label))

        # Score each option once, then sort/filter on the cached scores
        # instead of recomputing score() a second time per option.
        scored = [(score(o), o) for o in self._all_options]
        scored.sort(key=lambda pair: pair[0])
        result = [o for s, o in scored if s[0] < 10_000][:limit]
        logger.debug("AutoCompleteEntry._top_matches: q=%s returned %s matches", q, len(result))
        return result

    @staticmethod
    def _subseq_pos(text, pat):
        """Return the start index of a subsequence match or -1."""
        ti, first = 0, -1
        for pc in pat:
            found = text.find(pc, ti)
            if found == -1:
                return -1
            if first == -1:
                first = found
            ti = found + 1
        return first
