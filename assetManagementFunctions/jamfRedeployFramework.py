#!/usr/bin/env python3
"""
Redeploy the Jamf management framework for a computer found by Snipe-IT asset tag.
"""

from __future__ import annotations

import os
import sys

# Allow running as a standalone script by adding the project root to sys.path.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import logging
from tkinter import messagebox

from utilities.logging_utils import configure_logging
from utilities.otherApiBits import getAssetInfo
from utilities.jamfPrestageCommon import (
    _find_jamf_computer_by_serial,
    create_jamf_client,
    get_prestage_settings,
)

logger = logging.getLogger(__name__)


def redeploy_jamf_framework(asset_tag: str) -> str:
    """Redeploy the Jamf management framework for the given Snipe-IT asset tag."""
    configure_logging()
    if not asset_tag:
        return "[ERROR] No asset tag provided."

    _, asset = getAssetInfo(asset_tag)
    if not asset:
        return f"[ERROR] SNIPE: Could not load asset {asset_tag}."

    serial = (asset.get("serial") or "").strip()
    if not serial:
        messagebox.showerror("Redeploy Failed", f"Asset {asset_tag} has no serial number.")
        return f"[ERROR] SNIPE: No serial for asset {asset_tag}."

    settings = get_prestage_settings()
    try:
        jamf_client = create_jamf_client(settings)
    except Exception as e:
        messagebox.showerror("Jamf Error", f"Could not initialize Jamf client.\n\n{e}")
        return f"[ERROR] JAMF: Client init failed: {e}"

    comp = _find_jamf_computer_by_serial(jamf_client, serial, settings)
    if not comp:
        messagebox.showerror("Redeploy Failed", f"No Jamf computer found for serial {serial}.")
        return f"[ERROR] JAMF: No computer with serial {serial}."

    cid = comp["id"]
    cname = comp.get("name") or f"ID {cid}"
    logger.info("Redeploying Jamf framework for %s (ID %s)", cname, cid)

    try:
        r = jamf_client.pro_api_request(
            method="POST",
            resource_path=f"v1/jamf-management-framework/redeploy/{cid}",
            override_headers={"Accept": "application/json"},
        )
    except Exception as e:
        logger.exception("Jamf framework redeploy request failed")
        messagebox.showerror("Redeploy Failed", f"Jamf request failed.\n\n{e}")
        return f"[ERROR] JAMF: Redeploy request failed: {e}"

    if not (200 <= r.status_code < 300):
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        logger.error("Jamf redeploy failed (%s): %s", r.status_code, detail)
        messagebox.showerror("Redeploy Failed", f"Jamf API error ({r.status_code}).\n\n{detail}")
        return f"[ERROR] JAMF: Redeploy failed for ID {cid}."

    logger.info("Jamf framework redeploy requested for %s (ID %s)", cname, cid)
    return f"Redeploy requested for {asset_tag} (Jamf ID {cid})."


if __name__ == "__main__":
    TEST_ASSET_TAG = "6529"
    configure_logging(log_to_console=True)
    logger.info(redeploy_jamf_framework(TEST_ASSET_TAG))
