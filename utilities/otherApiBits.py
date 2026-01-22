"""Snipe-IT API helper utilities for asset and lookup data.

This module provides:
  - asset lookup by tag or serial
  - activity lookup for latest check-ins
  - cached/paged option builders for status/users/models
All requests use the dynamic API user header helper.
"""

import json
import logging

import requests
import tkinter as tk
from tkinter import messagebox

from utilities import Key
from utilities.api_user import get_api_headers
from utilities.logging_utils import configure_logging, get_settings

logger = logging.getLogger(__name__)


def get_headers() -> dict:
    """Return API headers using the current API user selection.

    Returns:
        Dict of request headers for Snipe-IT calls.
    """
    return get_api_headers()


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
    # Build the by-tag endpoint and perform the lookup.
    url = Key.API_URL_Base + "hardware/bytag/"

    # Issue the request and parse JSON.
    try:
        headers = get_headers()
        response = requests.get(url + assetTag, headers=headers, timeout=20)
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
    frame = tk.Frame(parent)
    check_vars = []
    for i, (name, value) in enumerate(var_list):
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
        frame.grid_columnconfigure(0, weight=0)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=1)
    else:
        frame.grid_columnconfigure(0, weight=0)
        frame.grid_columnconfigure(1, weight=1)

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
        if email:
            user_url = Key.API_URL_Base + f"users/{activity_data['rows'][0]['target']['id']}"
            headers = get_headers()
            user_response = requests.get(user_url, headers=headers)
            user_data = user_response.json()
            return user_data['email']
        elif username:
            user_url = Key.API_URL_Base + f"users/{activity_data['rows'][0]['target']['id']}"
            headers = get_headers()
            user_response = requests.get(user_url, headers=headers)
            user_data = user_response.json()
            return user_data['username']
        else:
            return activity_data['rows'][0]['target']['name']
    except (KeyError, IndexError):
        return None


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
    # Construct a base URL and iterate paginated results.
    base = Key.API_URL_Base.rstrip("/")
    offset = 0
    rows_all = []
    headers = headers or get_headers()
    while True:
        try:
            sep = "&" if "?" in url else "?"
            page_url = f"{base}{url}{sep}limit={limit}&offset={offset}"
            if extra_params:
                page_url += f"&{extra_params.lstrip('&')}"
            r = requests.get(page_url, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
            rows = data.get("rows") or data.get("data") or []
        except Exception:
            logger.exception("Failed to fetch paged data from %s", url)
            break
        rows_all.extend(rows)
        if len(rows) < limit:
            break
        offset += limit
    return rows_all

def getAllStatusOptions():
    """Return all asset status options for autocomplete.

    Returns:
        List of dicts: {"label": <status name>, "id": <status id>, "meta": {...}}
    """
    # /api/v1/statuslabels?type=asset is the endpoint.
    rows = _get_paged("/statuslabels", get_headers(), extra_params="type=asset")
    out = []
    for st in rows:
        out.append({
            "label": (st.get("name") or "").strip(),
            "id": st.get("id"),
            "meta": st,
        })
    # Unique & sorted.
    seen, uniq = set(), []
    for o in out:
        if o["id"] in seen:
            continue
        seen.add(o["id"])
        uniq.append(o)
    return sorted(uniq, key=lambda o: o["label"].lower())

def getAllAssigneeOptions():
    """Return combined user+location options for assignment autocomplete.

    Returns:
        List of dicts with fields: label, id, type, username, email, meta.
    """
    headers = get_headers()
    users = _get_paged("/users", headers)
    locs  = _get_paged("/locations", headers)

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
    for l in locs:
        out.append({
            "label": (l.get("name") or "").strip(),
            "id": l.get("id"),
            "type": "location",
            "username": "",
            "email": "",
            "meta": l,
        })

    # unique by (type,id) & sorted
    seen, uniq = set(), []
    for o in out:
        k = (o["type"], o["id"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    return sorted(uniq, key=lambda o: o["label"].lower())

def getAllModelOptions():
    """
    All asset models as:
      {"label": <model name>, "id": <model id>, "meta": {...}}
    """
    rows = _get_paged("/models", get_headers())
    out = []
    for m in rows:
        out.append({
            "label": (m.get("name") or "").strip(),
            "id": m.get("id"),
            "meta": m,
        })
    # unique by id & sorted by label
    seen, uniq = set(), []
    for o in out:
        if o["id"] in seen:
            continue
        seen.add(o["id"])
        uniq.append(o)
    return sorted(uniq, key=lambda o: o["label"].lower())
