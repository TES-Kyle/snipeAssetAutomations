# utilities/auto_complete.py
import tkinter as tk
from tkinter import ttk

_IGNORE_KEYS = {
    "Tab", "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R",
    "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Caps_Lock", "Escape", "Return",
    "Up", "Down", "Left", "Right", "Home", "End", "Prior", "Next", "Insert",
}

class AutoCompleteEntry(ttk.Frame):
    """
    Reusable autocomplete Entry with popup Listbox (auto-height up to 5 items).
    Public API:
      - set_options(list[dict]): each dict has at least {"label": str, "id": any, ...}
      - get() -> str (visible text)
      - set(text: str)
      - get_selected() -> dict | None (the last committed selection)
      - bind_change(callback) -> called on text change or selection
    Keyboard:
      - typing filters results (printable keys only)
      - Tab cycles suggestions while popup is visible
      - Enter selects highlighted
      - Esc hides popup
    Popup appears on typing or hover; hides on selection or leaving both entry & popup.
    """

    def __init__(self, parent, *, width=40):
        super().__init__(parent)
        self.entry = ttk.Entry(self, width=width)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.grid_columnconfigure(0, weight=1)

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
        self._all_options = list(options or [])

    def get(self) -> str:
        return self.entry.get()

    def set(self, text: str):
        self.entry.delete(0, tk.END)
        if text:
            self.entry.insert(0, text)
        self._fire_change()

    def get_selected(self):
        return self._selected

    def bind_change(self, callback):
        if callable(callback):
            self._change_cbs.append(callback)

    # ---------- Internals ----------
    def _fire_change(self):
        for cb in self._change_cbs:
            try: cb()
            except Exception: pass

    def _on_key(self, e):
        # ignore non-text keys so Tab/Enter etc. don’t reset selection
        if e.keysym in _IGNORE_KEYS:
            return
        self._selected = None
        self._requery_and_show()
        self._fire_change()

    def _on_hover_entry(self, _e):
        self._hover_open = True
        self._requery_and_show()

    def _on_leave_entry(self, _e):
        self._hover_open = False
        self._maybe_hide_later()

    def _on_enter_popup(self, _e):
        self._hover_open = True

    def _on_leave_popup(self, _e):
        self._hover_open = False
        self._maybe_hide_later()

    def _maybe_hide_later(self, _e=None):
        self.after(120, self._maybe_hide_now)

    def _maybe_hide_now(self):
        has_focus = (self.focus_get() in (self.entry, self.listbox))
        if not has_focus and not self._hover_open:
            self.hide_popup()

    def _on_tab(self, e):
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
        if not self._popup_visible():
            return
        self._commit_selection()
        return "break"

    def _on_return_listbox(self, _e):
        self._commit_selection()
        return "break"

    def _on_click_select(self, _e):
        self._commit_selection()
        return "break"

    def _commit_selection(self):
        sel = self.listbox.curselection()
        if not sel and self._matches:
            idx = 0
        elif not sel:
            self.hide_popup()
            return
        else:
            idx = sel[0]
        opt = self._matches[idx]
        self._selected = opt
        self.set(opt["label"])
        self.hide_popup()
        try:
            # ensure the main window is interactive again
            self.winfo_toplevel().focus_force()
            self.entry.focus_set()
        except Exception:
            pass
        self._fire_change()

    def _requery_and_show(self):
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
        try:
            self.popup.deiconify()
            self.popup.lift()
        except Exception:
            pass

    def hide_popup(self):
        try:
            self.popup.withdraw()
        except Exception:
            pass

    def _popup_visible(self):
        return self.popup.state() != "withdrawn"

    # ------ matching ------
    def _top_matches(self, q, limit=5):
        if not self._all_options:
            return []

        if not q:
            return sorted(self._all_options, key=lambda o: o["label"].lower())[:limit]

        def score(opt):
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
        ti, first = 0, -1
        for pc in pat:
            found = text.find(pc, ti)
            if found == -1:
                return -1
            if first == -1:
                first = found
            ti = found + 1
        return first
