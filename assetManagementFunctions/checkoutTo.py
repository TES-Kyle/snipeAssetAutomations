"""Checkout workflow for Snipe-IT assets."""

import logging

from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings
from utilities.otherApiBits import *
from utilities.api_user import get_api_key
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
    url = "https://trinityes.snipe-it.io/api/v1"
    ignore_name = False


    def on_enter_pressed(event):
        """Handle Enter key submission."""
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
        statusID = fetch_statuses(status_var.get())
        expectedCheckIn = date_var.get()

        # Extract the single status ID from the lookup mapping.
        statusID = statusID[list(statusID.keys())[0]]

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

        # Debounce keystrokes to avoid spamming the API.
        if debounce_timer:
            debounce_timer.cancel()

        if len(query) < 1:
            return

        debounce_timer = threading.Timer(0.3, lambda: fetch_users_async(query))
        debounce_timer.start()

    def fetch_users_async(query):
        """Fetch user matches asynchronously and update the combobox."""
        # Use cached results when available.
        if query in user_cache:
            user_combobox['values'] = list(user_cache[query].keys())
            return

        def fetch():
            """Fetch and cache user results for the query."""
            users = fetch_users(query)
            if users:
                user_cache[query] = users
                user_combobox['values'] = list(users.keys())

        threading.Thread(target=fetch).start()

    def fetch_statuses(filter_str=None):
        """Fetch status options with optional filtering.

        Args:
            filter_str: Optional filter string for server-side search.

        Returns:
            Dict mapping status label -> status ID.
        """
        settings = get_settings()
        try:
            limit_full = int(settings.get("statusSearchLimit", 30))
        except Exception:
            limit_full = 30
        try:
            limit_filtered = int(settings.get("statusSearchLimitFiltered", 5))
        except Exception:
            limit_filtered = 5

        # Use a filtered endpoint when text is provided.
        if filter_str:
            response = requests.get(
                url + f"/statuslabels?search={filter_str}&limit={limit_filtered}",
                headers=get_headers(),
            )
        else:
            response = requests.get(url + f"/statuslabels?limit={limit_full}", headers=get_headers())

        # Return empty results on error.
        if response.status_code != 200:
            logger.error("Status lookup failed for %s: %s", filter_str, response.text)
            return []

        data = response.json()
        statuses = {status['name']: status['id'] for status in data['rows']}
        return statuses

    def update_status_list():
        """Populate the status combobox with API results."""
        logger.debug("Updating status list for %s", asset_tag)
        statuses = fetch_statuses()
        logger.debug("Status options: %s", statuses)
        if statuses:
            status_combobox['values'] = list(statuses.keys())

    def on_status_tab_complete(event):
        """Autocomplete the first status option on Tab."""
        values = status_combobox['values']
        if values:
            status_combobox.set(values[0])
        return "break"

    def on_tab_complete(event):
        """Autocomplete the first user option on Tab."""
        values = user_combobox['values']
        if values:
            user_combobox.set(values[0])
        return "break"

    checkout_window = tk.Toplevel()

    var_list, assetData = getAssetInfo(asset_tag)
    exists2 = assetData['assigned_to']
    logger.debug("Assigned_to for %s: %s", asset_tag, exists2)
    logger.debug("Assigned_to raw value for %s: %s", asset_tag, assetData['assigned_to'])
        

    # Frame for the "Asset Tag" question
    asset_frame = tk.Frame(checkout_window)
    asset_frame.pack(fill='x', padx=10, pady=5)
    asset_label = tk.Label(asset_frame, text="Asset Tag:")
    asset_label.pack(side='left')

    asset_number = tk.StringVar(value=asset_tag)
    asset_entry = tk.Entry(asset_frame, textvariable=asset_number, width=7)
    asset_entry.pack(side='left', expand=True, fill='x')
    asset_entry.bind('<Return>', on_enter_pressed)

    # Status Frame
    status_frame = tk.Frame(checkout_window)
    status_frame.pack(fill='x', padx=10, pady=5)

    status_label = tk.Label(status_frame, text="Status:")
    status_label.pack(side='left')
    # Set the initial value of the combobox
    #currentStatus = assetData["status_label"]["name"] 
    currentStatus = {assetData["status_label"]["name"]: assetData["status_label"]["id"]}
    # Replace with the actual current status

    status_var = tk.StringVar()
    status_var.set(list(currentStatus.keys())[0])
    logger.debug("Current Status 2: %s", status_var)

    #status_combobox = ttk.Combobox(status_frame, textvariable=status_var)
    status_combobox = ttk.Combobox(status_frame, textvariable=status_var, postcommand=update_status_list)
    status_combobox.pack(side='left', expand=True, fill='x')
    logger.debug("Current Status 3: %s", status_var)

    #status_combobox.bind('<KeyRelease>', update_status_list)
    status_combobox.bind('<Tab>', on_status_tab_complete)

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
    soft_message_frame = tk.Frame(checkout_window)
    soft_message_frame.pack(fill='x', padx=10, pady=5)
    soft_message = tk.StringVar()
    soft_message_label = tk.Label(soft_message_frame, textvariable=soft_message)
    soft_message_label.pack()

    # Wait for the window to update its dimensions
    checkout_window.update_idletasks()

    # Get the screen width and height
    screen_width = checkout_window.winfo_screenwidth()
    screen_height = checkout_window.winfo_screenheight()

    # Get the window width and height
    window_width = checkout_window.winfo_width()
    window_height = checkout_window.winfo_height()

    # Calculate the center position
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))

    # Set the position of the window to the center of the screen
    checkout_window.geometry(f"+{center_x}+{center_y}")

    # Ensure API user prompt (if needed) happens on the UI thread.
    get_api_key()

    return f"Checkout window opened for {asset_tag}. Submit to complete."
