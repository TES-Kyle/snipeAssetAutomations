"""Checkout workflow for Snipe-IT assets."""

import logging

from utilities.logging_utils import configure_logging
from utilities import Key, optionsCache
from utilities.otherApiBits import getAssetInfo, get_headers
from utilities.api_user import get_api_key
from utilities.autocomplete import AutoCompleteEntry
from utilities.tk_geometry import center_window
from utilities.tk_date_entry import build_date_entry_frame
from utilities.checkInOutCommon import (
    resolve_status_id,
    build_asset_tag_frame,
    build_status_picker_frame,
    build_soft_message_frame,
)
import tkinter as tk
from tkinter import messagebox
import requests
from assetManagementFunctions.checkIn import checkIn

logger = logging.getLogger(__name__)

def checkoutTo(asset_tag):
    """Check out an asset to a user with optional expected check-in.

    Args:
        asset_tag: Asset tag to check out.

    Returns:
        Status string for the main UI on success, otherwise None.
    """
    configure_logging()
    url = Key.API_URL_Base.rstrip("/")


    def on_enter_pressed(event):
        """Handle Enter key submission."""
        logger.debug("on_enter_pressed: Enter key pressed for %s", asset_tag)
        submit()

    def submit():
        """Validate inputs and perform the checkout API call."""

        # Fetch current asset to confirm it is not already checked out.
        var_list, assetData = getAssetInfo(asset_tag)

        if assetData['assigned_to'] is not None:
            # If already checked out, route to check-in flow first.
            logger.info("Asset %s is currently checked out; prompting check-in.", asset_tag)
            checkIn(asset_tag, "yes")
            return

        logger.debug("Proceeding with checkout for %s", asset_tag)

        # Confirm selections are still valid before resolving them --
        # catches a value picked before a live-refresh dropped it.
        if not optionsCache.revalidate_for_submit("status", status_ac):
            messagebox.showerror("Outdated Selection", "The selected Status is no longer available. Please pick again.")
            return
        if not optionsCache.revalidate_for_submit("assignee", checkout_to_ac, transform=optionsCache.filter_to_users):
            messagebox.showerror("Outdated Selection", "The selected person is no longer available. Please pick again.")
            return

        # Resolve status/user selections and build the payload.
        statusID = resolve_status_id(url, status_ac.get())
        expectedCheckIn = date_var.get()

        selected_user = checkout_to_ac.get_selected()
        if selected_user is None:
            messagebox.showerror("Error", "Pick a person to check the device out to.")
            return

        if not statusID:
            messagebox.showerror("Error", "Status label is required")
            return

        userID = selected_user["id"]
        logger.info(
            "Checkout target resolved for %s: user_id=%s status=%s expected_checkin=%s",
            asset_tag,
            userID,
            statusID,
            expectedCheckIn,
        )

        payload = {
            "checkout_to_type": "user",
            "assigned_user": userID,
            "status_id": statusID,
            "expected_checkin": expectedCheckIn if expectedCheckIn else None
        }
        logger.debug("Checkout payload for %s: %s", asset_tag, payload)

        # Perform checkout request and handle errors.
        response2 = requests.post(
            url + "/hardware/" + str(assetData["id"]) + "/checkout/",
            json=payload,
            headers=get_headers(),
        )
        if response2.status_code >= 400:
            logger.error("Checkout failed for %s: %s", asset_tag, response2.text)
            messagebox.showerror("Checkout Failed", f"Checkout failed for {asset_tag}.\n\n{response2.text}")
            return None

        # Close the dialog and return a status string.
        logger.info("Asset checked out: %s", asset_tag)
        checkout_window.destroy()
        return f"Checkout complete for {asset_number.get()} (user {userID})."

    logger.debug("checkoutTo: creating checkout window for %s", asset_tag)
    checkout_window = tk.Toplevel()

    logger.debug("checkoutTo: fetching asset info for %s", asset_tag)
    var_list, assetData = getAssetInfo(asset_tag)
    logger.debug("checkoutTo: asset fetched id=%s name=%s", assetData.get("id"), assetData.get("name"))
    exists2 = assetData['assigned_to']
    logger.debug("Assigned_to for %s: %s", asset_tag, exists2)
    logger.debug("Assigned_to raw value for %s: %s", asset_tag, assetData['assigned_to'])
        

    # Frame for the "Asset Tag" question
    asset_frame, asset_number, asset_entry = build_asset_tag_frame(checkout_window, asset_tag, on_enter_pressed)

    # Status Frame
    current_status_name = assetData["status_label"]["name"]
    status_frame, status_ac = build_status_picker_frame(checkout_window, current_status_name)

    # Checkout To Frame
    checkout_to_frame = tk.Frame(checkout_window)
    checkout_to_frame.pack(fill='x', padx=10, pady=5)
    checkout_to_label = tk.Label(checkout_to_frame, text="Checkout To:")
    checkout_to_label.pack(side='left')

    checkout_to_ac = AutoCompleteEntry(checkout_to_frame, width=30)
    checkout_to_ac.pack(side='left', expand=True, fill='x')
    optionsCache.load_widget(checkout_window, "assignee", checkout_to_ac, transform=optionsCache.filter_to_users)
    optionsCache.start_live_refresh(
        checkout_window, "assignee", lambda opts: checkout_to_ac.set_options(optionsCache.filter_to_users(opts)),
    )


    # More parameters here #######
    # Consider adding "checkout to", "notes" and "status" options later

    # Expected Check-In date -- keystroke-validated plain Entry (same pattern
    # as makeCharger.py's Purchase Date field) rather than tkcalendar.DateEntry,
    # whose popup positioning was unreliable across multiple monitors/desktops
    # and whose field couldn't reliably be cleared.
    date_frame, date_var, date_entry = build_date_entry_frame(checkout_window, "Expected Check-In (YYYY-MM-DD):")

    # Submit button
    submit_button = tk.Button(checkout_window, text="Submit", command=submit)
    submit_button.pack(pady=10)

    # Soft Message Frame
    soft_message_frame, soft_message = build_soft_message_frame(checkout_window)

    # Center the window on screen.
    center_window(checkout_window)

    # Ensure API user prompt (if needed) happens on the UI thread.
    get_api_key()

    return f"Checkout window opened for {asset_tag}. Submit to complete."
