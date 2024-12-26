from Utilities.otherApiBits import *
import tkinter as tk
from tkinter import ttk
from tkcalendar import DateEntry
from tkinter import messagebox
import requests
from assetManagementFunctions.checkIn import checkIn


def checkoutTo(asset_tag):
    url = "https://trinityes.snipe-it.io/api/v1"
    ignore_name = False


    def on_enter_pressed(event):
        submit()

    def submit():
            
            var_list, assetData = getAssetInfo(asset_tag)

            if assetData['assigned_to'] is not None:
                print(f"Asset is currently checked out!")
                checkIn(asset_tag, "yes")
                return
                
            print(f"Done with check in")


            statusID = fetch_statuses(status_var.get())
            expectedCheckIn = date_var.get()

            statusID = statusID[list(statusID.keys())[0]]

            userID = fetch_users(checkout_to_var.get())
            if len(userID) < 1:
                messagebox.showerror("Error", "Multiple matching users")
                return

            if not statusID:
                messagebox.showerror("Error", "Status label is required")
                return

            if len(userID) == 1:
                userID = userID[list(userID.keys())[0]]

                payload = {
                    "checkout_to_type": "user",
                    "assigned_user": userID,
                    "status_id": statusID,
                    "expected_checkin": expectedCheckIn if expectedCheckIn else None
                }
                print(f"{payload}")

            response2 = requests.post(url + "/hardware/" + str(assetData["id"]) + "/checkout/", json=payload, headers=headers)
            print(response2.text)
            checkout_window.destroy()
            return f"Asset {asset_number.get()}  successfully checked out to {userID}"

    def fetch_users(query):
        response = requests.get(url + f"/users?search={query}&limit=5", headers=headers)

        if response.status_code != 200:
            return []

        data = response.json()
        users = {user['name']: user['id'] for user in data['rows']}
        return users

    def update_user_list(event):
        query = checkout_to_var.get()
        if len(query) < 1:
            return

        users = fetch_users(query)
        if users:
            user_combobox['values'] = list(users.keys())

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

    def on_tab_complete(event):
        values = user_combobox['values']
        if values:
            user_combobox.set(values[0])
        return "break"

    checkout_window = tk.Toplevel()

    var_list, assetData = getAssetInfo(asset_tag)
    exists2 = assetData['assigned_to']
    print(f"Exists2: {exists2}")

    if assetData['assigned_to'] is not None:
        print(f"It is not empty")
    else:
        print(f"It is empty")

    print(f"{exists2}")

    print(f"{assetData['assigned_to']}")
        
    #print(f'{assetData["status_label"]["name"]}')

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

    return f"Checking Out {asset_tag}"
