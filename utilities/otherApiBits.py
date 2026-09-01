"""Snipe-IT API helper utilities for asset and lookup data.

This module provides:
  - asset lookup by tag or serial
  - activity lookup for latest check-ins
  - cached/paged option builders for status/users/models
All requests use the dynamic API user header helper.
"""

from __future__ import annotations

import json
import logging

import requests
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

from utilities import Key
from utilities.api_retry import call_with_retry
from utilities.api_user import get_api_headers
from utilities.logging_utils import configure_logging
from utilities.settings import get_settings

logger = logging.getLogger(__name__)


def get_headers() -> dict:
    """Return API headers using the current API user selection.

    Returns:
        Dict of request headers for Snipe-IT calls.
    """
    logger.debug("get_headers: building API headers via get_api_headers")
    result = get_api_headers()
    logger.debug("get_headers: returning %s header keys", len(result))
    return result


def fetch_asset_by_tag(assetTag):
    """Issue the raw GET for a Snipe-IT asset lookup by tag.

    Args:
        assetTag: Asset tag to look up via the Snipe-IT API.

    Returns:
        The raw requests.Response (may be a non-2xx status; not raised here).
    """
    url = Key.API_URL_Base + "hardware/bytag/" + str(assetTag)
    return requests.get(url, headers=get_headers(), timeout=20)


def getAssetInfo(assetTag, allow_missing: bool = False):
    """Retrieve asset information from Snipe-IT by asset tag.

    Args:
        assetTag: Asset tag to search for.
        allow_missing: If True, return empty values when the asset doesn't exist.

    Returns:
        (var_list, assetData):
          - var_list: list of (label, value) tuples for UI display
          - assetData: raw JSON dict from the API

    Notes:
        Any API error prompts the user via messagebox and returns empty results.
    """
    configure_logging()
    # Issue the request and parse JSON.
    try:
        response = fetch_asset_by_tag(assetTag)
        response.raise_for_status()
        assetData = response.json()
    except Exception as e:
        logger.exception("Failed to fetch asset info for tag %s", assetTag)
        messagebox.showerror("Asset Lookup Failed", f"Could not fetch asset {assetTag}.\n\n{e}")
        return [], {}

    if not isinstance(assetData, dict):
        logger.error("Unexpected asset data response for %s: %r", assetTag, assetData)
        messagebox.showerror("Asset Lookup Failed", "Unexpected response from Snipe-IT.")
        return [], {}

    if assetData.get("status") == "error":
        msg = assetData.get("messages") or "Asset lookup failed."
        if isinstance(msg, list):
            msg = "; ".join(str(item) for item in msg if item is not None)
        if msg == "Asset does not exist." and allow_missing:
            logger.info("Asset %s does not exist (allow_missing).", assetTag)
            _log_asset_data(assetTag, assetData)
            return [], assetData

        logger.error("Snipe-IT error for %s: %s", assetTag, msg)
        messagebox.showerror("Asset Lookup Failed", f"Could not fetch asset {assetTag}.\n\n{msg}")
        return [], {}

    # Extract display-friendly values for the UI table.
    var_list = []

    _log_asset_data(assetTag, assetData)

    # Asset Tag
    var_list.append(("Asset Tag", assetData.get("asset_tag", "null")))

    # Serial Number
    if assetData.get("serial"):
        var_list.append(("Serial Number", assetData["serial"]))

    # Asset Name
    if assetData.get("name"):
        var_list.append(("Asset Name", assetData["name"]))

    # Status
    status_label = assetData.get("status_label", {})
    if status_label.get("name"):
        var_list.append(("Status", status_label["name"]))

    # Assigned To
    assigned_to = assetData.get("assigned_to") or {}
    if assigned_to.get("name"):
        var_list.append(("Assigned to User", assigned_to["name"]))
    if assigned_to.get("email"):
        var_list.append(("Assigned to Email", assigned_to["email"]))

    # Purchase Date
    purchase_date = assetData.get("purchase_date") or {}
    if purchase_date.get("date"):
        var_list.append(("Purchase Date", purchase_date["date"]))

    # Custom Fields
    custom_fields = assetData.get("custom_fields", {})

    hinge_weak = custom_fields.get("hingeWeak", {}).get("value")
    if hinge_weak:
        var_list.append(("Hinge Weak?", hinge_weak))

    charger_good = custom_fields.get("chargerInGoodCondition", {}).get("value")
    if charger_good:
        var_list.append(("Charger in Good Condition?", charger_good))

    battery_data = custom_fields.get("batteryData", {}).get("value")
    if battery_data:
        var_list.append(("Battery Stats", battery_data))

    box_number = custom_fields.get("Box Number", {}).get("value")
    if box_number:
        var_list.append(("Box Number", box_number))

    return var_list, assetData


def build_asset_info_frame(parent, var_list, *, include_checkboxes=False,
                           skip_first_checkbox=True, padx=5, pady=5):
    """Create a simple asset info table frame.

    Args:
        parent: Tk widget to contain the table.
        var_list: List of (label, value) tuples to render.
        include_checkboxes: If True, add a checkbox column.
        skip_first_checkbox: If True, skip checkbox for the first row.
        padx: Horizontal padding for each cell.
        pady: Vertical padding for each cell.

    Returns:
        (frame, check_vars) where check_vars is a list of (BooleanVar, value).
    """
    logger.debug("build_asset_info_frame: var_list length=%s, include_checkboxes=%s", len(var_list), include_checkboxes)
    frame = tk.Frame(parent)
    check_vars = []
    for i, (name, value) in enumerate(var_list):
        logger.debug("build_asset_info_frame: row %s name=%s value=%s", i, name, value)
        col_offset = 0
        if include_checkboxes:
            check_var = tk.BooleanVar()
            if not (skip_first_checkbox and i == 0):
                tk.Checkbutton(frame, variable=check_var).grid(row=i, column=0, sticky='ew')
            check_vars.append((check_var, value))
            col_offset = 1

        tk.Label(frame, text=name, relief='solid', borderwidth=1, anchor='e').grid(
            row=i, column=col_offset, sticky='ew', padx=padx, pady=pady
        )
        tk.Label(frame, text=value, relief='solid', borderwidth=1, anchor='w').grid(
            row=i, column=col_offset + 1, sticky='ew', padx=padx, pady=pady
        )

    if include_checkboxes:
        logger.debug("build_asset_info_frame: configuring checkbox column weights")
        frame.grid_columnconfigure(0, weight=0)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=1)
    else:
        frame.grid_columnconfigure(0, weight=0)
        frame.grid_columnconfigure(1, weight=1)

    logger.debug("build_asset_info_frame: built frame with %s rows, %s check_vars", len(var_list), len(check_vars))
    return frame, check_vars


def build_user_asset_list_frame(parent, user_id, *, include_checkboxes=False,
                                checkbox_header="", padx=5, pady=5):
    """Create a frame listing all assets currently checked out to a user.

    Fetches and parses the user's asset list internally rather than accepting
    a pre-built var_list, unlike build_asset_info_frame.

    Args:
        parent: Tk widget to contain the table.
        user_id: Snipe-IT user ID to fetch assets for.
        include_checkboxes: If True, add a clickable checkbox column as the last column.
        checkbox_header: Header text for the checkbox column.
        padx: Horizontal padding around the table.
        pady: Vertical padding around the table.

    Returns:
        (frame, check_vars) where check_vars is a list of (BooleanVar, asset_tag)
        for each row; empty when include_checkboxes is False.
    """
    configure_logging()
    logger.debug("build_user_asset_list_frame: user_id=%s, include_checkboxes=%s", user_id, include_checkboxes)
    frame = tk.Frame(parent)
    check_vars = []

    default_font = tkfont.nametofont("TkDefaultFont")
    bold_font = tkfont.Font(font=default_font)
    bold_font.configure(weight='bold')
    logger.debug("build_user_asset_list_frame: fonts initialized")

    tk.Label(frame, text="Assets assigned to computer user", font=bold_font).grid(
        row=0, column=0, sticky='w', padx=padx, pady=(pady, 2)
    )

    url = Key.API_URL_Base + f"users/{user_id}/assets"
    logger.info("build_user_asset_list_frame: fetching assets for user %s from %s", user_id, url)
    try:
        api_headers = get_headers()
        response = requests.get(url, headers=api_headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        logger.debug("build_user_asset_list_frame: API response status=%s", response.status_code)
    except Exception as e:
        logger.exception("Failed to fetch assets for user %s", user_id)
        messagebox.showerror("User Assets Lookup Failed", f"Could not fetch assets for user {user_id}.\n\n{e}")
        tk.Label(frame, text="Could not load user assets.", anchor='w').grid(
            row=1, column=0, sticky='ew', padx=padx, pady=pady
        )
        return frame, check_vars

    rows = data.get("rows") or []
    logger.debug("build_user_asset_list_frame: received %s asset rows", len(rows))

    col_ids = ["asset_tag", "name", "status", "model"]
    col_headings = ["Asset Tag", "Asset Name", "Status", "Model"]
    if include_checkboxes:
        col_ids.append("check")
        col_headings.append(checkbox_header or "")
        logger.debug("build_user_asset_list_frame: checkbox column added with header=%s", checkbox_header)

    # Build flat row data and measure column widths in one pass.
    row_data = []
    col_widths = [bold_font.measure(h) + 16 for h in col_headings]
    for asset in rows:
        asset_tag = asset.get("asset_tag", "")
        vals = [
            asset_tag,
            asset.get("name", ""),
            (asset.get("status_label") or {}).get("name", ""),
            (asset.get("model") or {}).get("name", ""),
        ]
        if include_checkboxes:
            vals.append("☐")
        for i, v in enumerate(vals):
            col_widths[i] = max(col_widths[i], default_font.measure(str(v)) + 16)
        row_data.append((asset_tag, vals))
        logger.debug("build_user_asset_list_frame: added row for asset_tag=%s", asset_tag)

    logger.debug("build_user_asset_list_frame: %s data rows prepared, col_widths=%s", len(row_data), col_widths)

    # ttk style — keyed to this widget so repeated calls don't bleed into other Treeviews.
    style = ttk.Style()
    style.configure("UserAssets.Treeview", font=default_font)
    style.configure("UserAssets.Treeview.Heading", font=bold_font)
    logger.debug("build_user_asset_list_frame: ttk style configured")

    border_frame = tk.Frame(frame, relief='solid', borderwidth=1)
    border_frame.grid(row=1, column=0, sticky='nsew', padx=padx, pady=pady)

    tree = ttk.Treeview(
        border_frame,
        columns=col_ids,
        show='headings',
        style="UserAssets.Treeview",
        height=max(len(row_data), 1),
    )
    for col_id, heading, width in zip(col_ids, col_headings, col_widths):
        tree.heading(col_id, text=heading)
        tree.column(col_id, width=width, minwidth=width, stretch=False)

    iid_to_var = {}
    for asset_tag, vals in row_data:
        iid = tree.insert("", "end", values=vals)
        if include_checkboxes:
            cb_var = tk.BooleanVar(value=False)
            check_vars.append((cb_var, asset_tag))
            iid_to_var[iid] = cb_var
    logger.debug("build_user_asset_list_frame: tree populated; iid_to_var size=%s", len(iid_to_var))

    if not row_data:
        tree.insert("", "end", values=["No assets checked out to this user"] + [""] * (len(col_ids) - 1))
        logger.debug("build_user_asset_list_frame: no assets row inserted")

    if include_checkboxes:
        last_col_idx = len(col_ids) - 1
        logger.debug("build_user_asset_list_frame: binding click handler for checkbox column idx=%s", last_col_idx)
        def _toggle_check(event):
            """Toggle the checkbox state for the clicked row in the asset list.

            Args:
                event: Tk mouse event containing x/y coordinates.
            """
            logger.debug("_toggle_check: click event at x=%s y=%s", event.x, event.y)
            region = tree.identify_region(event.x, event.y)
            if region != "cell":
                logger.debug("_toggle_check: click not in cell region (%s); ignoring", region)
                return
            col = tree.identify_column(event.x)
            if int(col[1:]) - 1 != last_col_idx:
                logger.debug("_toggle_check: click in col %s, not last_col_idx %s; ignoring", col, last_col_idx)
                return
            iid = tree.identify_row(event.y)
            if not iid or iid not in iid_to_var:
                logger.debug("_toggle_check: iid=%s not in iid_to_var; ignoring", iid)
                return
            cb_var = iid_to_var[iid]
            new_val = not cb_var.get()
            logger.debug("_toggle_check: toggling iid=%s to new_val=%s", iid, new_val)
            cb_var.set(new_val)
            cur = list(tree.item(iid, "values"))
            cur[last_col_idx] = "☑" if new_val else "☐"
            tree.item(iid, values=cur)
        tree.bind("<Button-1>", _toggle_check)

    tree.grid(row=0, column=0, sticky='nsew')
    border_frame.grid_columnconfigure(0, weight=1)
    border_frame.grid_rowconfigure(0, weight=1)

    frame.grid_rowconfigure(1, weight=1)
    frame.grid_columnconfigure(0, weight=1)

    return frame, check_vars


def _log_asset_data(asset_tag: str, asset_data: dict) -> None:
    """Log full asset payloads at INFO/DEBUG based on settings.

    Args:
        asset_tag: Asset tag being logged.
        asset_data: Raw JSON payload.
    """
    settings = get_settings()
    raw = settings.get("logAssetData", "0")
    val = str(raw).strip().lower()
    # Use INFO when explicitly enabled; otherwise keep at DEBUG.
    enabled = val in ("1", "true", "yes", "on")
    payload = json.dumps(asset_data, ensure_ascii=True, default=str)
    if enabled:
        logger.info("Asset data for %s: %s", asset_tag, payload)
    else:
        logger.debug("Asset data for %s: %s", asset_tag, payload)

def getAssetInfoSerialAssignedTo(serialNum):
    """Return the assigned-to name for an asset matching a serial number.

    Args:
        serialNum: Serial number to search for.

    Returns:
        Name string or None if not found.
    """
    configure_logging()
    logger.debug("Fetching asset assignment for serial %s", serialNum)
    url = Key.API_URL_Base + "hardware/byserial/"
    try:
        headers = get_headers()
        response = requests.get(url + serialNum, headers=headers, timeout=20)
        response.raise_for_status()
        assetData = response.json()
    except Exception as e:
        logger.exception("Failed to fetch asset info for serial %s", serialNum)
        messagebox.showerror("Asset Lookup Failed", f"Could not fetch asset by serial {serialNum}.\n\n{e}")
        return None
    
    # Safely navigate through the nested structure
    rows = assetData.get("rows")
    if rows and len(rows) > 0:
        assigned_to = rows[0].get("assigned_to")
        if assigned_to and "name" in assigned_to:
            return assigned_to["name"]
    
    # If we get here, it means something wasn't present
    return None

def getLatestCheckinName(asset_id, email=False, username=False):
    """Fetch the latest check-in actor for an asset.

    Args:
        asset_id: Snipe-IT asset id.
        email: If True, return user email.
        username: If True, return username.

    Returns:
        Name/email/username string or None.
    """
    configure_logging()
    logger.debug("Fetching latest check-in name for asset %s", asset_id)
    activity_url = Key.API_URL_Base + f'reports/activity?limit=1&offset=0&item_type=asset&item_id={asset_id}&action_type=checkin%20from&order=desc&sort=created_at'
    try:
        headers = get_headers()
        activity_response = requests.get(activity_url, headers=headers, timeout=20)
        activity_response.raise_for_status()
        activity_data = activity_response.json()
    except Exception as e:
        logger.exception("Failed to fetch activity for asset %s", asset_id)
        messagebox.showerror("Asset Lookup Failed", f"Could not fetch activity for asset {asset_id}.\n\n{e}")
        return None
    try:
        if email or username:
            user_url = Key.API_URL_Base + f"users/{activity_data['rows'][0]['target']['id']}"
            headers = get_headers()
            user_response = requests.get(user_url, headers=headers)
            user_data = user_response.json()
            return user_data['email'] if email else user_data['username']
        return activity_data['rows'][0]['target']['name']
    except (KeyError, IndexError):
        return None


def append_note(existing_notes_raw, new_note):
    """Append new_note to existing notes (rstripped), or return new_note alone if there were none.

    Snipe-IT has no atomic "append note" endpoint for any record type, so
    every caller that maintains a running log in a notes field builds the
    full replacement text with this helper before PUTting it back via
    put_notes_with_retry(). Shared by dropOff.py (asset notes) and
    loanCheckout.py (user notes).

    Args:
        existing_notes_raw: Current notes value from the API (may be None/empty).
        new_note: Note text to append.

    Returns:
        Combined notes string.
    """
    existing = (existing_notes_raw or "").rstrip()
    return (existing + "\n" + new_note) if existing else new_note


def put_notes_with_retry(record_kind: str, record_id, new_notes: str) -> bool:
    """Update just the notes field of a Snipe-IT hardware or user record, with Retry/Cancel.

    Uses PATCH rather than PUT: Snipe-IT's PUT endpoints validate as a full
    resource replace (e.g. /users/{id} rejects a notes-only PUT because
    first_name/username are "required"), while its PATCH endpoints are
    documented as true partial updates -- send only the field(s) you want
    to change. See https://snipe-it.readme.io/reference/users-3 and
    https://snipe-it.readme.io/reference/hardware-partial-update.

    Args:
        record_kind: Snipe-IT API path segment for the record type, e.g.
            "hardware" or "users".
        record_id: Numeric Snipe-IT record ID.
        new_notes: Full replacement notes text to write (build it with
            append_note() first if you're adding to existing notes).

    Returns:
        True on success, False if the user cancels after repeated failures.
    """
    configure_logging()
    url = Key.API_URL_Base + f"{record_kind}/" + str(record_id)
    payload = {"notes": new_notes}
    # Deliberately no is_success override here -- use call_with_retry's
    # default_is_success, which also rejects Snipe-IT's "HTTP 200 but body
    # says status: error" responses (e.g. a permissions/validation error on
    # this specific record type) instead of treating them as success.
    result = call_with_retry(
        f"Update {record_kind} {record_id} notes",
        lambda: requests.patch(url, json=payload, headers=get_headers(), timeout=20),
    )
    return result is not None


def _get_paged(url: str, headers: dict | None = None, limit: int = 500, extra_params: str = ""):
    """Yield all rows from a paginated Snipe-IT endpoint.

    Args:
        url: API endpoint path (e.g., /statuslabels).
        headers: Optional headers override.
        limit: Page size.
        extra_params: Additional query parameters.

    Returns:
        List of row dicts across all pages.
    """
    logger.debug("_get_paged: url=%s, limit=%s, extra_params=%s", url, limit, extra_params)
    # Construct a base URL and iterate paginated results.
    base = Key.API_URL_Base.rstrip("/")
    offset = 0
    rows_all = []
    headers = headers or get_headers()
    logger.debug("_get_paged: starting pagination loop for %s", url)
    while True:
        try:
            sep = "&" if "?" in url else "?"
            page_url = f"{base}{url}{sep}limit={limit}&offset={offset}"
            if extra_params:
                page_url += f"&{extra_params.lstrip('&')}"
            logger.debug("_get_paged: fetching page offset=%s, url=%s", offset, page_url)
            r = requests.get(page_url, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
            rows = data.get("rows") or data.get("data") or []
            logger.debug("_get_paged: page offset=%s returned %s rows", offset, len(rows))
        except Exception:
            logger.exception("Failed to fetch paged data from %s", url)
            break
        rows_all.extend(rows)
        if len(rows) < limit:
            logger.debug("_get_paged: last page reached (rows=%s < limit=%s)", len(rows), limit)
            break
        offset += limit
    logger.debug("_get_paged: total rows fetched from %s: %s", url, len(rows_all))
    return rows_all

def _dedup_and_sort_options(options, key_fn=lambda o: o["id"]):
    """Remove duplicate option dicts by key_fn and sort the rest by label.

    Shared by getAllStatusOptions/getAllAssigneeOptions/getAllModelOptions,
    which only differ in how they build each option dict and what makes an
    option a duplicate (plain id, vs. (type, id) for mixed user/location lists).

    Args:
        options: List of option dicts, each with at least a "label" key.
        key_fn: Callable(option) -> hashable key used to detect duplicates.
            Defaults to the option's "id".

    Returns:
        Deduplicated list sorted by label (case-insensitive).
    """
    seen, uniq = set(), []
    for o in options:
        k = key_fn(o)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    return sorted(uniq, key=lambda o: o["label"].lower())


def getAllStatusOptions():
    """Return all asset status options for autocomplete.

    Returns:
        List of dicts: {"label": <status name>, "id": <status id>, "meta": {...}}
    """
    logger.debug("getAllStatusOptions: fetching status labels from Snipe-IT")
    # /api/v1/statuslabels?type=asset is the endpoint.
    rows = _get_paged("/statuslabels", get_headers(), extra_params="type=asset")
    logger.debug("getAllStatusOptions: received %s raw status rows", len(rows))
    out = []
    for st in rows:
        out.append({
            "label": (st.get("name") or "").strip(),
            "id": st.get("id"),
            "meta": st,
        })
    logger.debug("getAllStatusOptions: built %s status option entries", len(out))
    result = _dedup_and_sort_options(out)
    logger.debug("getAllStatusOptions: returning %s unique sorted status options", len(result))
    return result

def getAllAssigneeOptions():
    """Return combined user+location options for assignment autocomplete.

    Returns:
        List of dicts with fields: label, id, type, username, email, meta.
    """
    logger.debug("getAllAssigneeOptions: fetching users and locations from Snipe-IT")
    headers = get_headers()
    users = _get_paged("/users", headers)
    locs  = _get_paged("/locations", headers)
    logger.debug("getAllAssigneeOptions: got %s users and %s locations", len(users), len(locs))

    out = []
    for u in users:
        label = (u.get("name") or u.get("username") or "").strip()
        out.append({
            "label": label,
            "id": u.get("id"),
            "type": "user",
            "username": (u.get("username") or "").strip(),
            "email": (u.get("email") or "").strip(),
            "meta": u,
        })
    logger.debug("getAllAssigneeOptions: appended %s user options", len(users))
    for l in locs:
        out.append({
            "label": (l.get("name") or "").strip(),
            "id": l.get("id"),
            "type": "location",
            "username": "",
            "email": "",
            "meta": l,
        })
    logger.debug("getAllAssigneeOptions: appended %s location options", len(locs))

    result = _dedup_and_sort_options(out, key_fn=lambda o: (o["type"], o["id"]))
    logger.debug("getAllAssigneeOptions: returning %s unique sorted assignee options", len(result))
    return result

def getAllModelOptions():
    """Return all asset model options for autocomplete.

    Returns:
        List of dicts: {"label": <model name>, "id": <model id>, "meta": {...}}
    """
    logger.debug("getAllModelOptions: fetching models from Snipe-IT")
    rows = _get_paged("/models", get_headers())
    logger.debug("getAllModelOptions: received %s raw model rows", len(rows))
    out = []
    for m in rows:
        out.append({
            "label": (m.get("name") or "").strip(),
            "id": m.get("id"),
            "meta": m,
        })
    logger.debug("getAllModelOptions: built %s model option entries", len(out))
    result = _dedup_and_sort_options(out)
    logger.debug("getAllModelOptions: returning %s unique sorted model options", len(result))
    return result
