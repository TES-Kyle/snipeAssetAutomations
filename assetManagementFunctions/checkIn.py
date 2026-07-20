"""Check-in workflow for Snipe-IT assets."""

import logging

from utilities.logging_utils import configure_logging
from utilities.otherApiBits import *
from utilities.tk_geometry import center_window
from utilities.checkInOutCommon import (
    resolve_status_id,
    build_asset_tag_frame,
    build_status_picker_frame,
    build_soft_message_frame,
)
import tkinter as tk
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
    logger.info("checkIn: starting check-in for asset_tag=%s checkOutOrigin=%s", asset_tag, checkOutOrigin)
    url = Key.API_URL_Base.rstrip("/")


    def on_enter_pressed(event):
        """Handle Enter key submission."""
        logger.debug("on_enter_pressed: Enter key pressed, submitting check-in for %s", asset_tag)
        submit()

    def submit():
        """Perform the check-in API call and close the window."""
        logger.debug("submit: checking in asset_tag=%s", asset_tag)

        # Resolve the selected status label into an ID.
        statusID = resolve_status_id(url, status_var.get())
        logger.debug("submit: resolved statusID=%s for %s", statusID, asset_tag)

        # Block submission if the status list did not resolve to an ID.
        if not statusID:
            logger.warning("submit: no status ID resolved for %s", asset_tag)
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

    def flash_window(window, duration=3000, interval=500):
        """Flash the window background to draw attention.

        Args:
            window: Tk widget to flash.
            duration: Total duration in milliseconds.
            interval: Toggle interval in milliseconds.
        """
        logger.debug("flash_window: starting flash duration=%s interval=%s", duration, interval)
        start_time = time.time() * 1000  # current time in ms
        colors = itertools.cycle(["yellow", "white"])  # Alternate colors
        def toggle_color():
            """Toggle the flash color until the duration elapses."""
            elapsed = (time.time() * 1000) - start_time
            logger.debug("toggle_color: elapsed=%s ms duration=%s ms", elapsed, duration)
            if elapsed < duration:
                # Change the background color
                new_color = next(colors)
                logger.debug("toggle_color: setting bg to %s", new_color)
                window.configure(bg=new_color)
                # Schedule another toggle
                window.after(interval, toggle_color)
            else:
                # Reset to original color when done
                logger.debug("toggle_color: flash complete, resetting bg")
                window.configure(bg="SystemButtonFace")  # or whatever the original color was

        toggle_color()
    

    logger.debug("checkIn: creating check-in window for %s", asset_tag)
    checkin_window = tk.Toplevel()
    logger.debug("checkIn: fetching asset info for %s", asset_tag)
    var_list, assetData = getAssetInfo(asset_tag)
    logger.debug("checkIn: asset fetched id=%s name=%s", assetData.get("id"), assetData.get("name"))

    checkin_window.geometry('500x150')
    if checkOutOrigin is not None:
        logger.debug("checkIn: checkOutOrigin set, showing already-checked-in warning")
        w = tk.Label(checkin_window, text="THIS ASSET IS STILL CHECKED IN.")
        w.pack()



    # Frame for the "Asset Tag" question
    asset_frame, asset_number, asset_entry = build_asset_tag_frame(checkin_window, asset_tag, on_enter_pressed)

    # Status Frame
    current_status_name = assetData["status_label"]["name"]
    status_frame, status_var, status_combobox = build_status_picker_frame(checkin_window, url, current_status_name)

    # More parameters here #######
    # Consider adding "checkout to", "notes" and "status" options later

    # Submit button
    submit_button = tk.Button(checkin_window, text="Submit", command=submit)
    submit_button.pack(pady=10)

    # Soft Message Frame
    soft_message_frame, soft_message = build_soft_message_frame(checkin_window)

    # Center the window on screen.
    center_window(checkin_window)
    
    if checkOutOrigin is not None:
        flash_window(checkin_window, duration=3000, interval=500)


    return f"Check-in window opened for {asset_tag}. Submit to complete."
