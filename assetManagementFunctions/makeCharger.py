from Utilities.otherApiBits import *
import tkinter as tk
from tkinter import ttk
from tkcalendar import DateEntry
from tkinter import messagebox
import requests
import json
import subprocess
import platform
import threading
import time


def makeCharger(asset_tag):
    url = "https://trinityes.snipe-it.io/api/v1"
    ignore_name = False

    def get_charger_serial_number():
        os_type = platform.system()

        if os_type == "Darwin":  # macOS
            try:
                result = subprocess.run(
                    "system_profiler SPPowerDataType | awk '/AC Charger Information:/,/Charging/' | grep 'Serial Number'",
                    shell=True,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True
                )
                serial_number = result.stdout.strip().split(": ")[-1]
                return serial_number
            except subprocess.CalledProcessError as e:
                return ""
        else:
            raise OSError("Unsupported operating system")

    def on_enter_pressed(event):
        submit()

    def submit():
        var_list, assetData = getAssetInfo(asset_number.get())
        try:
            exists = assetData['messages'] != 'Asset does not exist.'
        except KeyError:
            exists = True

        if exists:
            messagebox.showerror(title="Process Failed", message="Asset already exists")
            return f"Failed to run func2 on {asset_number.get()}"
        else:
            serial = serial_number.get()
            purchase_date = date_var.get()
            purchase_cost = cost_var.get()
            order_number = order_var.get()
            group = group_var.get()
            vintage = vintage_var.get()
            name = name_var.get()

            statusID = fetch_statuses(status_var.get())
            if len(statusID) != 1:
                messagebox.showerror("Error", "Multiple matching status labels")
                return

            statusID = statusID[list(statusID.keys())[0]]

            userID = fetch_users(checkout_to_var.get())
            if len(userID) < 1:
                messagebox.showerror("Error", "Multiple matching users")
                return

            if not statusID:
                messagebox.showerror("Error", "Status label is required")
                return

            if not serial:
                messagebox.showerror("Error", "Serial number is required")
                return

            if not vintage:
                messagebox.showerror("Error", "Vintage is required")
                return

            if not name:
                proceed = messagebox.askyesno(title="Name Eot Entered", message='Are you sure you want to use the default name?')
                if not proceed:
                    return

            if not model_var.get() or model_var.get() not in models:
                messagebox.showerror("Error", "Valid model is required")
                return

            if group not in group_options:
                messagebox.showerror("Error", "Valid group is required")
                return

            payload = {
                "asset_tag": asset_number.get(),
                "status_id": statusID,
                "model_id": models[model_var.get()],
                "name": ("Charger-" + name) if name else "Charger",
                "serial": serial,
                "purchase_date": purchase_date if purchase_date else None,
                "purchase_cost": float(purchase_cost) if purchase_cost else None,
                "order_number": order_number if order_number else None,
                "_snipeit_group_9": group,
                "_snipeit_vintage_10": vintage
            }

            response1 = requests.post(url + "/hardware/", json=payload, headers=headers)
            print(response1.text)

            if len(userID) == 1:
                userID = userID[list(userID.keys())[0]]

                payload = {
                    "checkout_to_type": "user",
                    "assigned_user": userID,
                    "status_id": statusID
                }

                response2 = requests.post(url + "/hardware/" + str(json.loads(response1.text)['payload']['id']) + "/checkout/", json=payload, headers=headers)
                print(response2.text)

            if response1.status_code != 200:
                messagebox.showerror("Error", "Something went wrong while making charger")
            else:
                if batch_var.get():
                    message = "Asset Created: tag = " + asset_number.get() + ", name = " + (("Charger-" + name) if name else "Charger")
                    asset_number.set(str(int(asset_number.get())+1))
                    checkout_to_var.set("")
                    name_var.set("")
                    soft_message.set(message)
                    return
                else:
                    charger_window.destroy()
                    return

    def serial_updater():
        while True:
            try:
                serial_number.set(get_charger_serial_number())
                time.sleep(0.1)  # Adjust the interval as needed
            except Exception as e:
                messagebox.showerror(title="Error", message=str(e))
                break

    def start_serial_update():
        serial_update_thread = threading.Thread(target=serial_updater)
        serial_update_thread.daemon = True
        serial_update_thread.start()

    def validate_float(P):
        if P == "":
            return True
        try:
            float(P)
            return True
        except ValueError:
            return False

    def get_models_by_category(category_id):
        response = requests.get(url + "/models", headers=headers)

        if response.status_code != 200:
            messagebox.showerror("Error","Unable to fetch charger models")
            return {}

        data = response.json()
        models = dict()

        for model in data['rows']:
            if model['category']['id'] == category_id:
                models[model['name']] = model['id']
        return models

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

    def fetch_statuses(query):
        # Replace this with the actual API endpoint to fetch statuses
        response = requests.get(url + f"/statuslabels?search={query}&limit=5", headers=headers)

        if response.status_code != 200:
            return []

        data = response.json()
        statuses = {status['name']: status['id'] for status in data['rows']}
        return statuses

    def update_status_list(event):
        query = status_var.get()
        if len(query) < 2:
            return

        statuses = fetch_statuses(query)
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

    try:
        serial_number = tk.StringVar(value=get_charger_serial_number())
    except OSError:
        messagebox.showerror(title="Process Failed", message="Unsupported Operating System")
        return "func2 failed due to unsupported operating system"

    charger_window = tk.Toplevel()

    # Frame for the "Asset Tag" question
    asset_frame = tk.Frame(charger_window)
    asset_frame.pack(fill='x', padx=10, pady=5)
    asset_label = tk.Label(asset_frame, text="Asset Tag:")
    asset_label.pack(side='left')

    asset_number = tk.StringVar(value=asset_tag)
    asset_entry = tk.Entry(asset_frame, textvariable=asset_number, width=7)
    asset_entry.pack(side='left', expand=True, fill='x')
    asset_entry.bind('<Return>', on_enter_pressed)

    batch_var = tk.BooleanVar()
    batch_check = tk.Checkbutton(asset_frame, text="Batch", variable=batch_var)
    batch_check.pack(side='left')

    # Serial Number Frame
    serial_frame = tk.Frame(charger_window)
    serial_frame.pack(fill='x', padx=10, pady=5)
    serial_label = tk.Label(serial_frame, text="Serial Number:")
    serial_label.pack(side='left')

    serial_number_label = tk.Label(serial_frame, textvariable=serial_number)
    serial_number_label.pack(side='left')
    start_serial_update()

    # Model Frame
    model_frame = tk.Frame(charger_window)
    model_frame.pack(fill='x', padx=10, pady=5)
    model_label = tk.Label(model_frame, text="Model:")
    model_label.pack(side='left')

    models = get_models_by_category(35)
    model_options = list(models.keys())  # Placeholder model names
    model_var = tk.StringVar()
    model_combobox = ttk.Combobox(model_frame, textvariable=model_var, values=model_options)
    model_combobox.pack(side='left', expand=True, fill='x')

    # Status Frame
    status_frame = tk.Frame(charger_window)
    status_frame.pack(fill='x', padx=10, pady=5)
    status_label = tk.Label(status_frame, text="Status:")
    status_label.pack(side='left')

    status_var = tk.StringVar()
    status_combobox = ttk.Combobox(status_frame, textvariable=status_var)
    status_combobox.pack(side='left', expand=True, fill='x')
    status_combobox.bind('<KeyRelease>', update_status_list)
    status_combobox.bind('<Tab>', on_status_tab_complete)

    # Group Frame
    group_frame = tk.Frame(charger_window)
    group_frame.pack(fill='x', padx=10, pady=5)
    group_label = tk.Label(group_frame, text="Group:")
    group_label.pack(side='left')

    group_options = ["Student", "Faculty-Staff", "Loan", "Other"]
    group_var = tk.StringVar()
    group_combobox = ttk.Combobox(group_frame, textvariable=group_var, values=group_options)
    group_combobox.pack(side='left', expand=True, fill='x')

    # Vintage Frame
    vintage_frame = tk.Frame(charger_window)
    vintage_frame.pack(fill='x', padx=10, pady=5)
    vintage_label = tk.Label(vintage_frame, text="Vintage (format as xx-xx. eg.\"24-25\"):")
    vintage_label.pack(side='left')

    vintage_var = tk.StringVar()
    vintage_entry = ttk.Entry(vintage_frame, textvariable=vintage_var,width=5)
    vintage_entry.pack(side='left', expand=True, fill='x')

    # Checkout To Frame
    checkout_to_frame = tk.Frame(charger_window)
    checkout_to_frame.pack(fill='x', padx=10, pady=5)
    checkout_to_label = tk.Label(checkout_to_frame, text="Checkout To:")
    checkout_to_label.pack(side='left')

    checkout_to_var = tk.StringVar()
    user_combobox = ttk.Combobox(checkout_to_frame, textvariable=checkout_to_var)
    user_combobox.pack(side='left', expand=True, fill='x')
    user_combobox.bind('<KeyRelease>', update_user_list)
    user_combobox.bind('<Tab>', on_tab_complete)

    # Name Frame
    name_frame = tk.Frame(charger_window)
    name_frame.pack(fill='x', padx=10, pady=5)
    name_label = tk.Label(name_frame, text="Asset Name: Charger-")
    name_label.pack(side='left')

    name_var = tk.StringVar()
    name_entry = tk.Entry(name_frame, textvariable=name_var)
    name_entry.pack(side='left', expand=True, fill='x')
    name_entry.bind('<Return>', on_enter_pressed)

    # Purchase Cost Frame
    cost_frame = tk.Frame(charger_window)
    cost_frame.pack(fill='x', padx=10, pady=5)
    cost_label = tk.Label(cost_frame, text="Purchase Cost:")
    cost_label.pack(side='left')

    vcmd = (charger_window.register(validate_float), '%P')
    cost_var = tk.StringVar()
    cost_entry = tk.Entry(cost_frame, textvariable=cost_var, validate='key', validatecommand=vcmd)
    cost_entry.pack(side='left', expand=True, fill='x')

    # Purchase Date Frame
    date_frame = tk.Frame(charger_window)
    date_frame.pack(fill='x', padx=10, pady=5)
    date_label = tk.Label(date_frame, text="Purchase Date:")
    date_label.pack(side='left')

    date_var = tk.StringVar()
    date_entry = DateEntry(date_frame, textvariable=date_var, date_pattern='yyyy-mm-dd')
    date_var.set('')

    date_entry.pack(side='left', expand=True, fill='x')

    # Order Number Frame
    order_frame = tk.Frame(charger_window)
    order_frame.pack(fill='x', padx=10, pady=5)
    order_label = tk.Label(order_frame, text="Order Number:")
    order_label.pack(side='left')

    order_var = tk.StringVar()
    order_entry = tk.Entry(order_frame, textvariable=order_var)
    order_entry.pack(side='left', expand=True, fill='x')

    # More parameters here #######
    # Consider adding "checkout to", "notes" and "status" options later

    # Submit button
    submit_button = tk.Button(charger_window, text="Submit", command=submit)
    submit_button.pack(pady=10)

    # Soft Message Frame
    soft_message_frame = tk.Frame(charger_window)
    soft_message_frame.pack(fill='x', padx=10, pady=5)
    soft_message = tk.StringVar()
    soft_message_label = tk.Label(soft_message_frame, textvariable=soft_message)
    soft_message_label.pack()

    # Wait for the window to update its dimensions
    charger_window.update_idletasks()

    # Get the screen width and height
    screen_width = charger_window.winfo_screenwidth()
    screen_height = charger_window.winfo_screenheight()

    # Get the window width and height
    window_width = charger_window.winfo_width()
    window_height = charger_window.winfo_height()

    # Calculate the center position
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))

    # Set the position of the window to the center of the screen
    charger_window.geometry(f"+{center_x}+{center_y}")

    return f"Running func2 on {asset_tag}"
