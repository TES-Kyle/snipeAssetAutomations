"""Checkout workflow for Snipe-IT assets."""

import logging

from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings
from utilities.otherApiBits import *
from utilities.api_user import get_api_key
from utilities.tk_geometry import center_window
from utilities.checkInOutCommon import (
    resolve_status_id,
    build_asset_tag_frame,
    build_status_picker_frame,
    build_soft_message_frame,
)
import tkinter as tk
from tkinter import ttk
from tkcalendar import DateEntry
from tkinter import messagebox
import requests
from assetManagementFunctions.checkIn import checkIn
import threading

debounce_timer = None
user_cache = {}
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

        # Resolve status/user selections and build the payload.
        statusID = resolve_status_id(url, status_var.get())
        expectedCheckIn = date_var.get()

        # Look up the user selection by search text.
        userID = fetch_users(checkout_to_var.get())
        if len(userID) < 1:
            messagebox.showerror("Error", "Multiple matching users")
            return

        if not statusID:
            messagebox.showerror("Error", "Status label is required")
            return

        # Build the checkout payload when a single user is resolved.
        if len(userID) == 1:
            userID = userID[list(userID.keys())[0]]
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

    def fetch_users(query):
        """Fetch a list of users based on a search query.

        Args:
            query: Search query for the users endpoint.

        Returns:
            Dict of {user_name: user_id} or empty dict on failure.
        """
        settings = get_settings()
        try:
            limit = int(settings.get("userSearchLimit", 5))
        except Exception:
            limit = 5

        # Query the Snipe-IT users endpoint with a limit.
        response = requests.get(
            url + f"/users?search={query}&limit={limit}",
            headers=get_headers(),
        )

        # Return empty results on error.
        if response.status_code != 200:
            logger.error("User lookup failed for %s: %s", query, response.text)
            return []

        data = response.json()
        users = {user['name']: user['id'] for user in data['rows']}
        return users

    def update_user_list(event):
        """Debounce user lookup as the entry text changes."""
        global debounce_timer
        # Ensure API user prompt (if needed) happens on the UI thread.
        get_api_key()
        query = checkout_to_var.get()
        logger.debug("update_user_list: query=%s", query)

        # Debounce keystrokes to avoid spamming the API.
        if debounce_timer:
            debounce_timer.cancel()

        if len(query) < 1:
            logger.debug("update_user_list: query too short, skipping")
            return

        logger.debug("update_user_list: scheduling async fetch for query=%s", query)
        debounce_timer = threading.Timer(0.3, lambda: fetch_users_async(query))
        debounce_timer.start()

    def fetch_users_async(query):
        """Fetch user matches asynchronously and update the combobox.

        Args:
            query: Search query to look up users.
        """
        logger.debug("fetch_users_async: query=%s", query)
        # Use cached results when available.
        if query in user_cache:
            logger.debug("fetch_users_async: cache hit for query=%s", query)
            user_combobox['values'] = list(user_cache[query].keys())
            return

        def fetch():
            """Fetch and cache user results for the query."""
            logger.debug("fetch: fetching users for query=%s in background", query)
            users = fetch_users(query)
            if users:
                logger.debug("fetch: caching %s users for query=%s", len(users), query)
                user_cache[query] = users
                user_combobox['values'] = list(users.keys())

        threading.Thread(target=fetch).start()

    def on_tab_complete(event):
        """Autocomplete the first user option on Tab."""
        logger.debug("on_tab_complete: Tab pressed for user combobox")
        values = user_combobox['values']
        if values:
            user_combobox.set(values[0])
            logger.debug("on_tab_complete: set to first user option: %s", values[0])
        return "break"

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
    status_frame, status_var, status_combobox = build_status_picker_frame(checkout_window, url, current_status_name)

    # Checkout To Frame
    checkout_to_frame = tk.Frame(checkout_window)
    checkout_to_frame.pack(fill='x', padx=10, pady=5)
    checkout_to_label = tk.Label(checkout_to_frame, text="Checkout To:")
    checkout_to_label.pack(side='left')

    checkout_to_var = tk.StringVar()
    user_combobox = ttk.Combobox(checkout_to_frame, textvariable=checkout_to_var)
    user_combobox.pack(side='left', expand=True, fill='x')
    user_combobox.bind('<KeyRelease>', update_user_list)
    user_combobox.bind('<Tab>', on_tab_complete)


    # More parameters here #######
    # Consider adding "checkout to", "notes" and "status" options later

    # Purchase Date Frame
    date_frame = tk.Frame(checkout_window)
    date_frame.pack(fill='x', padx=10, pady=5)
    date_label = tk.Label(date_frame, text="Expected Check-In:")
    date_label.pack(side='left')

    date_var = tk.StringVar()
    date_entry = DateEntry(date_frame, textvariable=date_var, date_pattern='yyyy-mm-dd')
    date_var.set('')

    date_entry.pack(side='left', expand=True, fill='x')

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
