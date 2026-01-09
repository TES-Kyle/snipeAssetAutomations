"""Check-in workflow for Snipe-IT assets."""

import logging

from utilities.logging_utils import configure_logging, get_settings
from utilities.otherApiBits import *
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import requests
import itertools
import time

logger = logging.getLogger(__name__)

def checkIn(asset_tag, checkOutOrigin=None):
    """Check in an asset and prompt for a new status label.

    Args:
        asset_tag: Asset tag to check in.
        checkOutOrigin: Optional flag indicating a check-out origin context.

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
        """Perform the check-in API call and close the window."""

        # Resolve the selected status label into an ID.
        statusID = fetch_statuses(status_var.get())

        # Extract the single status ID from the lookup mapping.
        statusID = statusID[list(statusID.keys())[0]]

        # Block submission if the status list did not resolve to an ID.
        if not statusID:
            messagebox.showerror("Error", "Status label is required")
            return

        # Build the check-in payload and call Snipe-IT.
        # Build the check-in payload.
        payload = {
            "status_id": statusID,
        }
        logger.debug("Check-in payload for %s: %s", asset_tag, payload)

        # Call the check-in endpoint.
        response2 = requests.post(
            url + "/hardware/" + str(assetData["id"]) + "/checkin/",
            json=payload,
            headers=get_headers(),
        )
        if response2.status_code >= 400:
            logger.error("Check-in failed for %s: %s", asset_tag, response2.text)
            messagebox.showerror("Check-in Failed", f"Check-in failed for {asset_tag}.\n\n{response2.text}")
            return None

        # Close the dialog and return a status string.
        logger.info("Asset checked in: %s", asset_tag)
        checkin_window.destroy()
        return f"Check-in complete for {asset_number.get()}."

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

        # Choose the appropriate endpoint depending on filter text.
        if filter_str:
            response = requests.get(
                url + f"/statuslabels?search={filter_str}&limit={limit_filtered}",
                headers=get_headers(),
            )
        else:
            response = requests.get(url + f"/statuslabels?limit={limit_full}", headers=get_headers())

        # Return empty list on errors to avoid crashing the UI.
        if response.status_code != 200:
            return []

        data = response.json()
        statuses = {status['name']: status['id'] for status in data['rows']}
        return statuses

    def update_status_list():
        """Populate the status combobox with API results."""
        # Refresh values before opening the dropdown.
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
    
    def flash_window(window, duration=3000, interval=500):
        """Flash the window background to draw attention.

        Args:
            window: Tk widget to flash.
            duration: Total duration in milliseconds.
            interval: Toggle interval in milliseconds.
        """
        """
        Flash the window background for `duration` milliseconds,
        toggling every `interval` milliseconds.
        """
        start_time = time.time() * 1000  # current time in ms
        colors = itertools.cycle(["yellow", "white"])  # Alternate colors
        def toggle_color():
            """Toggle the flash color until the duration elapses."""
            elapsed = (time.time() * 1000) - start_time
            if elapsed < duration:
                # Change the background color
                window.configure(bg=next(colors))
                # Schedule another toggle
                window.after(interval, toggle_color)
            else:
                # Reset to original color when done
                window.configure(bg="SystemButtonFace")  # or whatever the original color was

        toggle_color()
    

    checkin_window = tk.Toplevel()
    var_list, assetData = getAssetInfo(asset_tag)

    checkin_window.geometry('500x150')
    if checkOutOrigin is not None:
        w = tk.Label(checkin_window, text="THIS ASSET IS STILL CHECKED IN.")
        w.pack()



    # Frame for the "Asset Tag" question
    asset_frame = tk.Frame(checkin_window)
    asset_frame.pack(fill='x', padx=10, pady=5)
    asset_label = tk.Label(asset_frame, text="Asset Tag:")
    asset_label.pack(side='left')

    asset_number = tk.StringVar(value=asset_tag)
    asset_entry = tk.Entry(asset_frame, textvariable=asset_number, width=7)
    asset_entry.pack(side='left', expand=True, fill='x')
    asset_entry.bind('<Return>', on_enter_pressed)

    # Status Frame
    status_frame = tk.Frame(checkin_window)
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


    # More parameters here #######
    # Consider adding "checkout to", "notes" and "status" options later

    # Submit button
    submit_button = tk.Button(checkin_window, text="Submit", command=submit)
    submit_button.pack(pady=10)

    # Soft Message Frame
    soft_message_frame = tk.Frame(checkin_window)
    soft_message_frame.pack(fill='x', padx=10, pady=5)
    soft_message = tk.StringVar()
    soft_message_label = tk.Label(soft_message_frame, textvariable=soft_message)
    soft_message_label.pack()

    # Wait for the window to update its dimensions
    checkin_window.update_idletasks()

    # Get the screen width and height
    screen_width = checkin_window.winfo_screenwidth()
    screen_height = checkin_window.winfo_screenheight()

    # Get the window width and height
    window_width = checkin_window.winfo_width()
    window_height = checkin_window.winfo_height()

    # Calculate the center position
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))

    # Set the position of the window to the center of the screen
    checkin_window.geometry(f"+{center_x}+{center_y}")
    
    if checkOutOrigin is not None:
        flash_window(checkin_window, duration=3000, interval=500)


    return f"Check-in window opened for {asset_tag}. Submit to complete."
