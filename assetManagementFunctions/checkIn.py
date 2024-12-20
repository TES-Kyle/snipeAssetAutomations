from Utilities.otherApiBits import *
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import requests
import itertools
import time



def checkIn(asset_tag, checkOutOrigin=None):
    url = "https://trinityes.snipe-it.io/api/v1"
    ignore_name = False


    def on_enter_pressed(event):
        submit()

    def submit():
        
            statusID = fetch_statuses(status_var.get())

            statusID = statusID[list(statusID.keys())[0]]

            if not statusID:
                messagebox.showerror("Error", "Status label is required")
                return


            payload = {
                "status_id": statusID,
            }

            response2 = requests.post(url + "/hardware/" + str(assetData["id"]) + "/checkin/", json=payload, headers=headers)
            print(response2.text)
            checkin_window.destroy()
            return f"Asset {asset_number.get()}  successfully checked in"

    def fetch_statuses(filter_str=None):

        if filter_str:
            response = requests.get(url + f"/statuslabels?search={filter_str}&limit=5", headers=headers)
        else:
            response = requests.get(url + f"/statuslabels?limit=30", headers=headers)

        if response.status_code != 200:
            return []

        data = response.json()
        statuses = {status['name']: status['id'] for status in data['rows']}
        return statuses

    def update_status_list():
        print(f"In status def")

        statuses = fetch_statuses()
        print(f"{statuses}")
        if statuses:
            status_combobox['values'] = list(statuses.keys())

    def on_status_tab_complete(event):
        values = status_combobox['values']
        if values:
            status_combobox.set(values[0])
        return "break"
    
    def flash_window(window, duration=3000, interval=500):
        """
        Flash the window background for `duration` milliseconds,
        toggling every `interval` milliseconds.
        """
        start_time = time.time() * 1000  # current time in ms
        colors = itertools.cycle(["yellow", "white"])  # Alternate colors
        def toggle_color():
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


    #print(f'{assetData["status_label"]["name"]}')

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
    #print(f"Current Status 1: {status_var}")

    status_var = tk.StringVar()
    status_var.set(list(currentStatus.keys())[0])
    print(f"Current Status 2: {status_var}")

    #status_combobox = ttk.Combobox(status_frame, textvariable=status_var)
    status_combobox = ttk.Combobox(status_frame, textvariable=status_var, postcommand=update_status_list)
    status_combobox.pack(side='left', expand=True, fill='x')
    print(f"Current Status 3: {status_var}")

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


    return f"Checking In {asset_tag}"
