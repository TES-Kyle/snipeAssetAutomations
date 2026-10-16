"""Box Number Cleanup: browse every asset's box number and clear the stale ones.

Flow:
  1. Full scan of all Snipe-IT assets (background thread, progress bar).
  2. Overview: collapsed tree  PREFIX-XX  ->  PREFIX-NN  ->  assets, with
     counts and checkboxes at every level (old numeric-only boxes live under
     N/A-XX).
  3. "Clear Box Numbers from Selected" blanks the box-number custom field on
     the ticked assets (background thread, progress + Stop), then optionally
     tells the drop-off box tracker about it (see dropOff.apply_removals_to_state).

The scan and the clears never show dialogs from the worker thread; every
hand-off to the UI goes through utilities/tk_thread.py.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

import requests

from assetManagementFunctions.dropOff import STREAMS, update_box_tracker
from otherManagementFunctions import boxNumberLogic as bl
from utilities import Key
from utilities.api_retry import default_is_success
from utilities.api_user import get_api_key
from utilities.logging_utils import configure_logging
from utilities.otherApiBits import get_headers
from utilities.scroll_support import bind_text_scroll
from utilities.settings import get_settings
from utilities.theme import get_ui_colors
from utilities.tk_geometry import center_window
from utilities.tk_thread import ensure_tk_thread_pump, run_on_tk_thread

logger = logging.getLogger(__name__)

PAGE_LIMIT = 500
INDENT_PX = 28


def _box_field_key() -> str:
    """Custom-field DB column for Box Number (same setting the drop-off flow writes)."""
    return (get_settings().get("dropOffBoxFieldKey", "") or "").strip() or "_snipeit_box_number_5"


def _extract_box(row: dict, box_key: str) -> str:
    """Pull the box-number value out of one /hardware list row ('' if none)."""
    fields = row.get("custom_fields") or {}
    for cf in fields.values():
        if isinstance(cf, dict) and cf.get("field") == box_key:
            return str(cf.get("value") or "").strip()
    return str((fields.get("Box Number") or {}).get("value") or "").strip()


def _http_error(resp) -> str:
    """Short, one-line description of a failed response."""
    try:
        body = resp.json()
        msg = body.get("messages") or body.get("message") or body
    except Exception:
        msg = resp.text
    return f"HTTP {resp.status_code}: {str(msg)[:160]}"


def _scan_assets(box_key: str, on_progress, cancel: threading.Event):
    """Fetch every asset (all pages); keep the ones that have a box number.

    Deliberately strict instead of best-effort: a short scan would make the
    tool believe a box (or a whole stream) is emptier than it is, which
    could mis-adjust the drop-off tracker. Any failed page aborts the scan,
    and the final count must match the API's reported total.

    Returns:
        (assets_with_box, scanned_count), or None if cancelled.

    Raises:
        RuntimeError: on an API error or an incomplete scan.
    """
    base = Key.API_URL_Base.rstrip("/")
    assets, scanned, offset, total = [], 0, 0, None
    while True:
        if cancel.is_set():
            return None
        url = f"{base}/hardware?limit={PAGE_LIMIT}&offset={offset}&sort=id&order=asc"
        resp = bl.request_with_backoff(lambda u=url: requests.get(u, headers=get_headers(), timeout=60))
        if not default_is_success(resp):
            raise RuntimeError(_http_error(resp))
        data = resp.json()
        rows = data.get("rows") or []
        total = data.get("total", total)
        for row in rows:
            scanned += 1
            box = _extract_box(row, box_key)
            if box:
                assets.append({
                    "id": row.get("id"),
                    "tag": str(row.get("asset_tag") or ""),
                    "name": str(row.get("name") or ""),
                    "model": str((row.get("model") or {}).get("name") or ""),
                    "box": box,
                })
        on_progress(scanned, total)
        if len(rows) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    if total is not None and scanned < total:
        raise RuntimeError(f"Scan incomplete: got {scanned} of {total} assets.")
    return assets, scanned


def _clear_box_number(asset_id, box_key: str) -> str | None:
    """PATCH one asset's box number to blank. Returns None on success, else an error string."""
    url = f"{Key.API_URL_Base.rstrip('/')}/hardware/{asset_id}"
    try:
        resp = bl.request_with_backoff(
            lambda: requests.patch(url, json={box_key: ""}, headers=get_headers(), timeout=25)
        )
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None if default_is_success(resp) else _http_error(resp)


class _BoxCleanupWindow:
    """The Box Number Cleanup window (loading view, then the overview)."""

    def __init__(self):
        self.theme = get_ui_colors()
        self.box_key = _box_field_key()
        self.win = tk.Toplevel()
        self.win.title("Box Number Cleanup")
        # Ask for the full screen height; macOS clamps a window to the visible area
        # (below the menu bar, above the Dock), so this fills it exactly.
        center_window(self.win, width=980, height=self.win.winfo_screenheight())
        self.win.minsize(720, 420)
        ensure_tk_thread_pump(self.win)
        self.win.protocol("WM_DELETE_WINDOW", self._exit)

        self.bold = tkfont.nametofont("TkDefaultFont").copy()
        self.bold.configure(weight="bold")
        # Monospace so the tree's guide lines and columns line up exactly.
        size = abs(int(tkfont.nametofont("TkDefaultFont").actual("size")))
        mono_family = tkfont.nametofont("TkFixedFont").actual("family")
        self.mono = tkfont.Font(family=mono_family, size=size)
        self.mono_bold = tkfont.Font(family=mono_family, size=size, weight="bold")

        self.assets: list[dict] = []
        self.scanned = 0
        self.cats: list[dict] = []
        self.expanded: set = {("root",)}  # root row starts open; categories/boxes start collapsed
        self.selected: set = set()
        self._rows: dict = {}
        self._hover_line = None
        self._clearing = False
        self._cancel_scan = threading.Event()
        self._stop_clear = threading.Event()

        self.content = ttk.Frame(self.win)
        self.content.pack(fill="both", expand=True)
        self._start_scan()

    # ------------------------------------------------------------------ scan
    def _reset_content(self):
        for child in self.content.winfo_children():
            child.destroy()

    def _start_scan(self):
        self._reset_content()
        self._cancel_scan.clear()
        box = ttk.Frame(self.content)
        box.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(box, text="Scanning all assets…", font=self.bold).pack(pady=(0, 10))
        bar = ttk.Progressbar(box, mode="indeterminate", length=360)
        bar.pack()
        bar.start(12)
        status = tk.StringVar(value="Starting…")
        ttk.Label(box, textvariable=status).pack(pady=(8, 14))
        ttk.Button(box, text="Exit", command=self._exit).pack()

        # Resolve the API key on the Tk thread (it may prompt) before the worker starts.
        get_api_key()

        def on_progress(scanned, total):
            def apply():
                if not self.win.winfo_exists():
                    return
                if total:
                    bar.stop()
                    bar.configure(mode="determinate", maximum=total, value=scanned)
                    status.set(f"{scanned:,} of {total:,} assets")
                else:
                    status.set(f"{scanned:,} assets")
            run_on_tk_thread(self.win, apply)

        def worker():
            configure_logging()
            try:
                result = _scan_assets(self.box_key, on_progress, self._cancel_scan)
            except Exception as exc:
                logger.exception("box cleanup: scan failed")
                msg = str(exc)
                run_on_tk_thread(self.win, lambda m=msg: self._show_scan_error(m))
                return
            if result is None:
                return
            run_on_tk_thread(self.win, lambda r=result: self._scan_done(*r))

        threading.Thread(target=worker, daemon=True).start()

    def _show_scan_error(self, message: str):
        self._reset_content()
        box = ttk.Frame(self.content)
        box.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(box, text="The asset scan failed.", font=self.bold).pack(pady=(0, 8))
        ttk.Label(box, text=message, wraplength=520, justify="center").pack(pady=(0, 14))
        btns = ttk.Frame(box)
        btns.pack()
        ttk.Button(btns, text="Retry", command=self._start_scan).pack(side="left", padx=6)
        ttk.Button(btns, text="Exit", command=self._exit).pack(side="left", padx=6)

    def _scan_done(self, assets: list[dict], scanned: int):
        logger.info("box cleanup: scan done, %s assets scanned, %s with a box number", scanned, len(assets))
        self.assets = assets
        self.scanned = scanned
        self._build_overview()

    # -------------------------------------------------------------- overview
    def _build_overview(self):
        self._reset_content()
        t = self.theme
        self.summary_var = tk.StringVar()
        ttk.Label(self.content, textvariable=self.summary_var).pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(
            self.content, foreground=t["muted_fg"],
            text="Click a row to expand or collapse it. Click a [ ] box to select: [ ] none  [~] some  [x] all.",
        ).pack(anchor="w", padx=12, pady=(0, 6))

        body = ttk.Frame(self.content)
        body.pack(fill="both", expand=True, padx=12)
        self.text = tk.Text(
            body, wrap="none", font=self.mono, bg=t["entry_bg"], fg=t["entry_fg"],
            relief="solid", borderwidth=1, highlightthickness=0, padx=10, pady=8,
            spacing1=0, spacing2=0, spacing3=0, cursor="arrow", state="disabled",
            takefocus=0, insertwidth=0,
        )
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        for tag, opts in {
            "conn": {"foreground": t["muted_fg"]},
            "info": {"foreground": t["muted_fg"]},
            "model": {"foreground": t["muted_fg"]},
            "bold": {"font": self.mono_bold},
            "hover": {"background": t["row_bg_2"]},
        }.items():
            self.text.tag_configure(tag, **opts)
        self.text.tag_raise("hover")
        self.text.bind("<Button-1>", self._on_click)
        self.text.bind("<Double-Button-1>", lambda e: "break")
        self.text.bind("<B1-Motion>", lambda e: "break")
        self.text.bind("<Motion>", self._on_motion)
        self.text.bind("<Leave>", lambda e: self._set_hover(None))
        bind_text_scroll(self.text)

        # Progress strip (only visible while clearing).
        self.progress_frame = ttk.Frame(self.content)
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode="determinate", length=300)
        self.progress_bar.pack(side="left", padx=(12, 8))
        self.progress_var = tk.StringVar()
        ttk.Label(self.progress_frame, textvariable=self.progress_var).pack(side="left")
        self.stop_btn = ttk.Button(self.progress_frame, text="Stop", command=self._request_stop)
        self.stop_btn.pack(side="right", padx=12)

        bottom = self.bottom = ttk.Frame(self.content)
        bottom.pack(fill="x", padx=12, pady=12)
        self.tracker_var = tk.BooleanVar(value=False)
        self.tracker_cb = ttk.Checkbutton(
            bottom, text="Also update the drop-off box tracker", variable=self.tracker_var)
        self.tracker_cb.pack(side="left")
        self.exit_btn = ttk.Button(bottom, text="Exit", command=self._exit)
        self.exit_btn.pack(side="right")
        self.clear_btn = ttk.Button(bottom, text="Clear Box Numbers from Selected", command=self._on_clear)
        self.clear_btn.pack(side="right", padx=(0, 8))
        self.selected_var = tk.StringVar()
        ttk.Label(bottom, textvariable=self.selected_var).pack(side="right", padx=(0, 16))

        self._regroup()
        self._render()

    def _regroup(self):
        self.cats = bl.group_assets(self.assets)
        boxes = sum(len(c["boxes"]) for c in self.cats)
        self.summary_var.set(
            f"{self.scanned:,} assets scanned — {len(self.assets):,} have a box number, in {boxes:,} boxes."
        )

    @staticmethod
    def _fit(text: str, width: int) -> str:
        """Pad to width, or truncate with an ellipsis (keeps the columns aligned)."""
        return text[: width - 1] + "…" if len(text) > width else text.ljust(width)

    def _render(self):
        """Redraw the whole tree as monospace text (keeps the top visible line)."""
        t = self.text
        top_line = int(t.index("@0,0").split(".")[0])
        t.configure(state="normal")
        t.delete("1.0", "end")
        self._rows = {}
        self._hover_line = None
        line = 1

        def emit(segments, row=None):
            nonlocal line
            for txt, tags in segments:
                t.insert("end", txt, tags)
            t.insert("end", "\n")
            if row is not None:
                self._rows[line] = row
            line += 1

        def glyph(ids):
            n = len(ids & self.selected)
            if not n:
                return "[ ]", ()
            return ("[x]", ("bold",)) if n == len(ids) else ("[~]", ("bold",))

        all_assets = [a for c in self.cats for b in c["boxes"] for a in b["assets"]]
        tag_w = max([len(a["tag"]) for a in all_assets] + [4])
        name_w = min(max([len(a["name"]) for a in all_assets] + [4]), 32)

        # The root row works like any group: [ ] selects everything, +/- hides or shows the tree.
        all_ids = frozenset(a["id"] for a in all_assets)
        root_key = ("root",)
        root_open = root_key in self.expanded
        g_txt, g_tags = glyph(all_ids)
        emit([("- " if root_open else "+ ", ()), (g_txt, g_tags + ("chk",)), (" ", ()),
              ("Box Numbers", ("bold",)), ("  ", ()), (self._count_text(all_ids), ("info",))],
             {"ids": all_ids, "expand_key": root_key})
        shown_cats = self.cats if root_open else []
        if root_open and not self.cats:
            emit([("└── ", ("conn",)), ("(no assets have a box number)", ("info",))])
        cat_label_w = max([len(c["label"]) for c in shown_cats] + [0])
        for ci, cat in enumerate(shown_cats):
            cat_last = ci == len(shown_cats) - 1
            cat_ids = frozenset(a["id"] for b in cat["boxes"] for a in b["assets"])
            cat_key = ("c", cat["key"])
            is_open = cat_key in self.expanded
            g_txt, g_tags = glyph(cat_ids)
            emit([("└── " if cat_last else "├── ", ("conn",)), ("- " if is_open else "+ ", ()),
                  (g_txt, g_tags + ("chk",)), (" ", ()),
                  (self._fit(cat["label"], cat_label_w), ("bold",)), ("  ", ()),
                  (self._count_text(cat_ids), ("info",))],
                 {"ids": cat_ids, "expand_key": cat_key})
            if not is_open:
                continue
            cat_pad = "    " if cat_last else "│   "
            box_label_w = max(len(b["label"]) for b in cat["boxes"])
            for bi, box in enumerate(cat["boxes"]):
                box_last = bi == len(cat["boxes"]) - 1
                box_ids = frozenset(a["id"] for a in box["assets"])
                box_key = ("b", cat["key"], box["key"])
                is_open_b = box_key in self.expanded
                g_txt, g_tags = glyph(box_ids)
                emit([(cat_pad, ("conn",)), ("└── " if box_last else "├── ", ("conn",)),
                      ("- " if is_open_b else "+ ", ()), (g_txt, g_tags + ("chk",)), (" ", ()),
                      (self._fit(box["label"], box_label_w), ()), ("  ", ()),
                      (self._count_text(box_ids), ("info",))],
                     {"ids": box_ids, "expand_key": box_key})
                if not is_open_b:
                    continue
                box_pad = cat_pad + ("    " if box_last else "│   ")
                for ai, a in enumerate(box["assets"]):
                    a_last = ai == len(box["assets"]) - 1
                    ids = frozenset([a["id"]])
                    g_txt, g_tags = glyph(ids)
                    sel_tags = ("bold",) if a["id"] in self.selected else ()
                    emit([(box_pad, ("conn",)), ("└── " if a_last else "├── ", ("conn",)),
                          (g_txt, g_tags + ("chk",)), (" ", ()),
                          (self._fit(a["tag"], tag_w), sel_tags), ("  ", ()),
                          (self._fit(a["name"], name_w), sel_tags), ("  ", ()),
                          (a["model"], ("model",))],
                         {"ids": ids, "expand_key": None})
        t.configure(state="disabled")
        t.yview(f"{top_line}.0")
        self._update_selection_ui()

    def _count_text(self, ids) -> str:
        n = len(ids & self.selected)
        noun = "asset" if len(ids) == 1 else "assets"
        return f"{len(ids)} {noun}" + (f"  ·  {n} selected" if n else "")

    def _row_at(self, event):
        """(line number, row dict or None, whether the click landed on a [ ] glyph)."""
        idx = self.text.index(f"@{event.x},{event.y}")
        line = int(idx.split(".")[0])
        return line, self._rows.get(line), "chk" in self.text.tag_names(idx)

    def _on_click(self, event):
        if not self._clearing:
            _line, row, on_chk = self._row_at(event)
            if row is not None:
                if row["expand_key"] is None or on_chk:
                    self._toggle_select(row["ids"])
                else:
                    self._toggle_expand(row["expand_key"])
        return "break"

    def _on_motion(self, event):
        line, row, _ = self._row_at(event)
        self._set_hover(line if row is not None else None)

    def _set_hover(self, line):
        if line == self._hover_line:
            return
        if self._hover_line is not None:
            self.text.tag_remove("hover", f"{self._hover_line}.0", f"{self._hover_line + 1}.0")
        self._hover_line = line
        if line is not None:
            self.text.tag_add("hover", f"{line}.0", f"{line + 1}.0")

    def _toggle_expand(self, key):
        self.expanded.symmetric_difference_update({key})
        self._render()

    def _toggle_select(self, ids):
        # All selected -> deselect; anything less -> select the lot.
        if ids <= self.selected:
            self.selected -= ids
        else:
            self.selected |= ids
        self._render()

    def _update_selection_ui(self):
        n = len(self.selected)
        self.selected_var.set(f"{n:,} selected" if n else "")
        self.clear_btn.configure(state="normal" if (n and not self._clearing) else "disabled")

    # ----------------------------------------------------------------- clear
    def _on_clear(self):
        if self._clearing or not self.selected:
            return
        n = len(self.selected)
        tracker_note = ("\n\nThe drop-off box tracker will then be adjusted to match."
                        if self.tracker_var.get() else "")
        if not messagebox.askyesno(
            "Clear Box Numbers",
            f"Clear the box number from {n:,} asset{'s' if n != 1 else ''} in Snipe-IT?\n\n"
            f"This can't be undone from here.{tracker_note}",
            icon="warning", default="no", parent=self.win,
        ):
            return

        items = [a for a in self.assets if a["id"] in self.selected]
        self._set_clearing(True, total=len(items))
        self._stop_clear.clear()
        logger.info("box cleanup: clearing %s assets (tracker=%s)", len(items), self.tracker_var.get())

        def worker():
            configure_logging()
            cleared, failures, stopped = set(), [], False
            for i, a in enumerate(items):
                if self._stop_clear.is_set():
                    stopped = True
                    break
                err = _clear_box_number(a["id"], self.box_key)
                if err is None:
                    cleared.add(a["id"])
                else:
                    failures.append((a["tag"], err))
                    logger.warning("box cleanup: failed to clear %s: %s", a["tag"], err)
                run_on_tk_thread(self.win, lambda d=i + 1: self._on_progress(d, len(items)))
            run_on_tk_thread(self.win, lambda: self._clear_done(cleared, failures, stopped))

        threading.Thread(target=worker, daemon=True).start()

    def _set_clearing(self, on: bool, total: int = 0):
        self._clearing = on
        if on:
            self.progress_bar.configure(maximum=max(total, 1), value=0)
            self.progress_var.set(f"Clearing 0 of {total:,}…")
            self.stop_btn.configure(state="normal")
            self.progress_frame.pack(fill="x", before=self.bottom, pady=(6, 0))
        else:
            self.progress_frame.pack_forget()
        state = "disabled" if on else "normal"
        self.tracker_cb.configure(state=state)
        self.exit_btn.configure(state=state)
        self._update_selection_ui()

    def _on_progress(self, done: int, total: int):
        if not self.win.winfo_exists():
            return
        self.progress_bar.configure(value=done)
        self.progress_var.set(f"Clearing {done:,} of {total:,}…")

    def _request_stop(self):
        self._stop_clear.set()
        self.stop_btn.configure(state="disabled")
        self.progress_var.set("Stopping after the current asset…")

    def _clear_done(self, cleared: set, failures: list, stopped: bool):
        if not self.win.winfo_exists():
            return
        before = list(self.assets)
        self.assets = [a for a in self.assets if a["id"] not in cleared]
        self.selected -= cleared

        tracker_lines = []
        if self.tracker_var.get() and cleared:
            removals = bl.tracker_removals(before, cleared, STREAMS)
            if removals:
                _ok, tracker_lines = update_box_tracker(removals)
            else:
                tracker_lines = ["No drop-off streams were affected, so the tracker was not touched."]

        self._set_clearing(False)
        self._regroup()
        self._render()

        lines = [f"Cleared {len(cleared):,} asset{'s' if len(cleared) != 1 else ''}."]
        if stopped:
            lines.append("Stopped early; the remaining selected assets were not touched.")
        if failures:
            lines.append(f"\n{len(failures)} failed (still selected):")
            lines += [f"  {tag}: {err}" for tag, err in failures[:8]]
            if len(failures) > 8:
                lines.append(f"  …and {len(failures) - 8} more (see the log).")
        if tracker_lines:
            lines.append("\nDrop-off tracker:")
            lines += [f"  {ln}" for ln in tracker_lines]
        show = messagebox.showwarning if failures else messagebox.showinfo
        show("Box Numbers Cleared", "\n".join(lines), parent=self.win)

    # ------------------------------------------------------------------ exit
    def _exit(self):
        if self._clearing:
            messagebox.showinfo("Clearing in Progress", "Press Stop first, then wait for it to finish.", parent=self.win)
            return
        self._cancel_scan.set()
        self.win.destroy()


def box_number_cleanup():
    """Open the Box Number Cleanup window (scans all assets first)."""
    configure_logging()
    logger.info("box_number_cleanup: opening")
    _BoxCleanupWindow()
    return "Box Number Cleanup opened."
