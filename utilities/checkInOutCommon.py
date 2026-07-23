"""Shared status-picker and form-row widgets for checkIn.py/checkoutTo.py.

These two forms independently implemented the same "Asset Tag:" entry row,
"Status:" autocomplete combobox (backed by a Snipe-IT /statuslabels search),
and blank status-line row. Consolidated here so both share one
implementation instead of two copies that could drift apart.
"""

import logging
import tkinter as tk
from tkinter import ttk

import requests

from utilities.otherApiBits import get_headers
from utilities.settings import get_settings

logger = logging.getLogger(__name__)


def fetch_statuses(url, filter_str=None):
    """Fetch status label options from Snipe-IT, optionally filtered.

    Args:
        url: Snipe-IT API base URL (no trailing slash).
        filter_str: Optional search text; when omitted, fetches the full
            (unfiltered) list up to statusSearchLimit.

    Returns:
        Dict mapping status label -> status ID, or [] if the request failed
        (matches the original callers' behavior -- not hardened here, since
        callers already rely on this shape).
    """
    logger.debug("fetch_statuses: filter_str=%s", filter_str)
    settings = get_settings()
    try:
        limit_full = int(settings.get("statusSearchLimit", 30))
    except Exception:
        limit_full = 30
    try:
        limit_filtered = int(settings.get("statusSearchLimitFiltered", 5))
    except Exception:
        limit_filtered = 5
    logger.debug("fetch_statuses: limit_full=%s limit_filtered=%s", limit_full, limit_filtered)

    # Choose the appropriate endpoint depending on filter text.
    if filter_str:
        logger.debug("fetch_statuses: fetching filtered statuses for filter=%s", filter_str)
        response = requests.get(
            url + f"/statuslabels?search={filter_str}&limit={limit_filtered}",
            headers=get_headers(),
        )
    else:
        logger.debug("fetch_statuses: fetching all statuses with limit=%s", limit_full)
        response = requests.get(url + f"/statuslabels?limit={limit_full}", headers=get_headers())

    # Return empty list on errors to avoid crashing the UI.
    if response.status_code != 200:
        logger.error("fetch_statuses: API returned status=%s", response.status_code)
        return []

    data = response.json()
    statuses = {status['name']: status['id'] for status in data['rows']}
    logger.debug("fetch_statuses: returned %s status options", len(statuses))
    return statuses


def resolve_status_id(url, status_text):
    """Resolve a status combobox's current text to a Snipe-IT status ID.

    Mirrors the original inline `fetch_statuses(text)[list(...)[0]]` pattern
    from checkIn.py/checkoutTo.py's submit() exactly, including its behavior
    when the lookup is empty (raises rather than returning None) -- not
    defensively hardened here, since that would be a behavior change beyond
    deduplication.

    Args:
        url: Snipe-IT API base URL.
        status_text: Current text in the status combobox.

    Returns:
        Resolved status ID.
    """
    statuses = fetch_statuses(url, status_text)
    return statuses[list(statuses.keys())[0]]


def build_asset_tag_frame(parent, asset_tag, on_enter):
    """Build the 'Asset Tag:' label + entry row.

    Args:
        parent: Tk parent widget.
        asset_tag: Initial asset tag value for the entry.
        on_enter: Callback bound to the entry's <Return> event.

    Returns:
        (frame, asset_number_var, asset_entry).
    """
    frame = tk.Frame(parent)
    frame.pack(fill='x', padx=10, pady=5)
    label = tk.Label(frame, text="Asset Tag:")
    label.pack(side='left')

    asset_number = tk.StringVar(value=asset_tag)
    entry = tk.Entry(frame, textvariable=asset_number, width=7)
    entry.pack(side='left', expand=True, fill='x')
    entry.bind('<Return>', on_enter)

    return frame, asset_number, entry


def build_status_picker_frame(parent, url, current_status_name=""):
    """Build the 'Status:' label + autocomplete combobox row.

    Args:
        parent: Tk parent widget.
        url: Snipe-IT API base URL, used by the combobox's postcommand to
            refresh options via fetch_statuses().
        current_status_name: Initial status label to show.

    Returns:
        (frame, status_var, status_combobox).
    """
    frame = tk.Frame(parent)
    frame.pack(fill='x', padx=10, pady=5)
    label = tk.Label(frame, text="Status:")
    label.pack(side='left')

    status_var = tk.StringVar(value=current_status_name)

    def update_status_list():
        """Populate the status combobox with API results."""
        logger.debug("update_status_list: refreshing status options")
        statuses = fetch_statuses(url)
        logger.debug("Status options: %s", statuses)
        if statuses:
            status_combobox['values'] = list(statuses.keys())

    def on_status_tab_complete(event):
        """Autocomplete the first status option on Tab."""
        logger.debug("on_status_tab_complete: Tab pressed for status combobox")
        values = status_combobox['values']
        if values:
            status_combobox.set(values[0])
            logger.debug("on_status_tab_complete: set to first status option: %s", values[0])
        return "break"

    status_combobox = ttk.Combobox(frame, textvariable=status_var, postcommand=update_status_list)
    status_combobox.pack(side='left', expand=True, fill='x')
    status_combobox.bind('<Tab>', on_status_tab_complete)

    return frame, status_var, status_combobox


def build_soft_message_frame(parent):
    """Build the blank status-line frame shown below the submit button.

    Declared and displayed in both original forms but never populated by
    either -- kept as-is (a StringVar callers can .set() later if needed).

    Args:
        parent: Tk parent widget.

    Returns:
        (frame, soft_message_var).
    """
    frame = tk.Frame(parent)
    frame.pack(fill='x', padx=10, pady=5)
    soft_message = tk.StringVar()
    label = tk.Label(frame, textvariable=soft_message)
    label.pack()
    return frame, soft_message
