"""Plain-Entry date field with keystroke validation (YYYY-MM-DD).

Restricts typed input to valid partial/complete YYYY-MM-DD text via Tk's
built-in validate="key" mechanism, instead of a calendar-popup widget.
Originally written inline for makeCharger.py's Purchase Date field (the
pattern this app settled on after tkcalendar.DateEntry proved unreliable --
its popup positioning was inconsistent across multiple monitors/desktops,
and the field couldn't reliably be cleared). Promoted here so makeCharger.py,
checkoutTo.py, and loanCheckout.py all share the same validator instead of
a separate copy per module.
"""

import re
import tkinter as tk
from tkinter import ttk

_DATE_PARTIAL_RE = re.compile(r"^\d{0,4}(-\d{0,2}(-\d{0,2})?)?$")


def is_valid_partial_date(value: str) -> bool:
    """Return True if value is blank or a valid partial/complete YYYY-MM-DD string.

    Blank is always accepted so the field can be fully cleared; any prefix
    of the YYYY-MM-DD shape (digits and hyphens in the right positions) is
    accepted so typing is validated incrementally rather than only at submit.

    Args:
        value: Proposed new entry content (Tk's "%P" validatecommand substitution).

    Returns:
        True if the value is an acceptable partial or full date, or blank.
    """
    if value == "":
        return True
    if len(value) > 10:
        return False
    return bool(_DATE_PARTIAL_RE.fullmatch(value))


def build_date_entry_frame(parent, label_text="Date (YYYY-MM-DD):", width=None):
    """Build a label + keystroke-validated date Entry row.

    Args:
        parent: Tk parent widget.
        label_text: Text for the row's label (should state the expected format,
            since there's no in-field placeholder -- matches makeCharger.py's
            "Purchase Date (YYYY-MM-DD):" convention).
        width: Optional entry width in characters.

    Returns:
        (frame, date_var, entry) tuple. date_var is the StringVar holding the
        raw YYYY-MM-DD text (or blank); entry is the ttk.Entry widget itself,
        useful for .configure(state=...).
    """
    frame = ttk.Frame(parent)
    frame.pack(fill="x", padx=10, pady=5)
    frame.grid_columnconfigure(0, weight=0)
    frame.grid_columnconfigure(1, weight=1)
    ttk.Label(frame, text=label_text).grid(row=0, column=0, sticky="w")

    date_var = tk.StringVar()
    entry_kwargs = {"textvariable": date_var}
    if width is not None:
        entry_kwargs["width"] = width
    entry = ttk.Entry(frame, **entry_kwargs)
    vcmd = (entry.register(is_valid_partial_date), "%P")
    entry.configure(validate="key", validatecommand=vcmd)
    entry.grid(row=0, column=1, sticky="ew")

    return frame, date_var, entry
