"""Autocomplete Tk widget used across GUI forms."""

# utilities/auto_complete.py
import tkinter as tk
from tkinter import ttk

_IGNORE_KEYS = {
    "Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R",
    "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Caps_Lock", "Escape", "Return",
    "Up", "Down", "Left", "Right", "Home", "End", "Prior", "Next", "Insert",
}

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

    def __init__(self, parent, *, width=40):
        """Initialize the entry and popup listbox widgets.

        Args:
            parent: Tk parent widget.
            width: Entry width in characters.
        """
        super().__init__(parent)
        self.entry = ttk.Entry(self, width=width)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.grid_columnconfigure(0, weight=1)
        self.advance_focus_on_select = True

        self._all_options = []   # [{"label": str, ...}, ...]
        self._matches = []       # current top matches
        self._selected = None
        self._change_cbs = []
        self._hover_open = False

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

    # ---------- Public API ----------
    def set_options(self, options):
        """Replace the autocomplete option list.

        Args:
            options: Iterable of dicts with a "label" key.
        """
        self._all_options = list(options or [])

    def get(self) -> str:
        """Return the current entry text."""
        return self.entry.get()

    def set(self, text: str):
        """Set the entry text and fire change callbacks.

        Args:
            text: New text to insert.
        """
        self.entry.delete(0, tk.END)
        if text:
            self.entry.insert(0, text)
        self._fire_change()

    def get_selected(self):
        """Return the last committed option dict or None."""
        return self._selected

    def bind_change(self, callback):
        """Register a callback to run when the entry changes.

        Args:
            callback: Callable invoked on text or selection changes.
        """
        if callable(callback):
            self._change_cbs.append(callback)

    def set_selected_by_label(self, label: str):
        """Programmatically set entry + selected option by exact label match."""
        if not label:
            self._selected = None
            self.set("")  # fires change
            return
        for opt in self._all_options:
            if opt.get("label") == label:
                self._selected = opt
                self.set(label)  # fires change
                return
        # no exact match -> treat as plain text
        self._selected = None
        self.set(label)

    def commit_selection(self):
        """Commit selection based on current listbox cursor (if visible)."""
        if not self._popup_visible() or not self._matches:
            # try to map current entry text to an option
            txt = self.get().strip()
            for opt in self._all_options:
                if opt.get("label") == txt:
                    self._selected = opt
                    break
            return
        try:
            idx = self.listbox.curselection()[0]
        except Exception:
            idx = 0
        self._selected = self._matches[idx]
        self.set(self._selected["label"])  # fires change
        self.hide_popup()


    def hide_popup(self):
        """Hide the popup listbox and restore focus."""
        try:
            # release any implicit grabs some Tk variants might take for a transient Toplevel
            try:
                self.popup.grab_release()
            except Exception:
                pass
            self.popup.withdraw()
        except Exception:
            pass
        # ensure the main window is interactive again
        try:
            self.winfo_toplevel().focus_force()
        except Exception:
            pass


    # ---------- Internals ----------
    def _fire_change(self):
        """Invoke change callbacks with best-effort isolation."""
        # Isolate callback failures to keep the widget responsive.
        for cb in self._change_cbs:
            try: cb()
            except Exception: pass

    def _on_key(self, e):
        """Handle key release events and refresh matches."""
        # ignore non-text keys so Tab/Enter etc. don’t reset selection
        if e.keysym in _IGNORE_KEYS:
            return
        self._selected = None
        self._requery_and_show()
        self._fire_change()

    def _on_hover_entry(self, _e):
        """Open the popup when hovering over the entry."""
        self._hover_open = True
        self._requery_and_show()

    def _on_leave_entry(self, _e):
        """Schedule popup hide when leaving the entry."""
        self._hover_open = False
        self._maybe_hide_later()

    def _on_enter_popup(self, _e):
        """Track hover state when entering the popup."""
        self._hover_open = True

    def _on_leave_popup(self, _e):
        """Schedule popup hide when leaving the popup."""
        self._hover_open = False
        self._maybe_hide_later()

    def _maybe_hide_later(self, _e=None):
        """Delay popup hide to allow focus changes."""
        self.after(120, self._maybe_hide_now)

    def _maybe_hide_now(self):
        """Hide the popup if neither entry nor popup has focus."""
        has_focus = (self.focus_get() in (self.entry, self.listbox))
        if not has_focus and not self._hover_open:
            self.hide_popup()

    def _on_tab(self, e):
        """Cycle the highlighted suggestion when the popup is visible."""
        if not self._popup_visible():
            return  # let normal focus traversal happen
        if not self._matches:
            return "break"
        cur = self.listbox.curselection()
        idx = (cur[0] + 1) % len(self._matches) if cur else 0
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.activate(idx)
        self.listbox.see(idx)
        return "break"

    def _on_return(self, _e):
        """Commit the current selection on Enter."""
        if not self._popup_visible():
            return
        self._commit_selection()
        return "break"

    def _on_return_listbox(self, _e):
        """Commit the current selection from the listbox."""
        self._commit_selection()
        return "break"

    def _on_click_select(self, e):
        """Select the clicked item and commit it."""
        # ensure we select the clicked row
        i = self.listbox.nearest(e.y)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(i)
        self.listbox.activate(i)
        self.commit_selection()
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
        # Persist the selected option and reflect it in the entry.
        self._selected = opt
        self.set(opt["label"])
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

        self._fire_change()

    def _requery_and_show(self):
        """Recompute matches and render the popup listbox."""
        q = self.entry.get().strip().lower()
        self._matches = self._top_matches(q, limit=5)

        if not self._matches:
            self.hide_popup()
            return

        self.listbox.delete(0, tk.END)
        for opt in self._matches:
            self.listbox.insert(tk.END, opt["label"])

        # resize listbox to #matches (<=5)
        h = max(1, min(len(self._matches), 5))
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
        if not self._all_options:
            return []

        if not q:
            return sorted(self._all_options, key=lambda o: o["label"].lower())[:limit]

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

        ranked = sorted(self._all_options, key=score)
        return [o for o in ranked if score(o)[0] < 10_000][:limit]

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
