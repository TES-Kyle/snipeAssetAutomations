from Utilities.otherApiBits import *
from Utilities.Key import *
import tkinter as tk
from tkinter import messagebox
from datetime import date, timedelta
from Utilities.messaging import *


def sendFineEmail(name, charge, assetTag, divert=False):
    if name is not None and divert is False:
        content = f"The following Student needs to be charged ${charge} for breaking their laptop:\n" + name
        message(content, operations_email, subject='Laptop Repair Fine')
    else:
        content = f"Failed to find name for fine email.\nCharge: {charge}\nAsset Tag: {assetTag}"
        message(content, support_email, subject='Laptop Repair Fine Email Failed')


def set_loan_checkin(email):
    if email:
        user_data = requests.get(Key.API_URL_Base + f"users?username= {email}", headers=headers).json()

        if user_data['total'] == 1: #fix this
            user_assets = requests.get(Key.API_URL_Base + f"users/{user_data['rows'][0]['id']}/assets", headers=headers).json()
            asset_id = []
            for row in user_assets['rows']:
                if row['category']['id'] == 24 and row['status_label']['id'] == 31:
                    asset_id.append(row['id'])

            if len(asset_id) == 1:
                payload = {
                    "expected_checkin": (date.today() + timedelta(days=1)).isoformat()
                }
                res = requests.patch(Key.API_URL_Base + f"hardware/{asset_id[0]}", json=payload, headers=headers).json()
                return True
            else:
                return False
        else:
            return False
    else:
        return False



def backFromApple(asset_tag):
    def submit_repair_info(event=None):
        d_number = d_number_entry.get()
        repair_notes = repair_notes_entry.get("1.0", tk.END).strip()

        # For now, just printing the values. You can modify this to do something else
        if charge_entry.get().strip().isnumeric():
            print(f"D Number: {d_number}")
            print(f"Repair Notes: {repair_notes}")
            updateMaintenance(asset_tag, d_number, repair_notes, fault.get())
            name = getLatestCheckinName(assetData["id"])
            email = getLatestCheckinName(assetData["id"], email=True)
            charge = int(charge_entry.get().strip())

            if fault.get() and charge > 0:
                if remove_fine_warning(email):
                    charge = 0
                else:
                    sendFineEmail(name, charge, asset_tag, divert=divert.get())

            if "Send Emails: True" in notes:
                subject ="Computer Ready for Pickup"

                if fault.get() and (charge > 0):
                    content = ready_fine(name, charge)
                else:
                    content = ready_no_fine(name)

                if  name is not None and divert.get() is False:
                    recipient = email
                else:
                    recipient = support_email
                    if name is None:
                        subject = "Error name not found: " + subject
                    if divert.get():
                        subject = "Error email diverted: " + subject

                message(content, recipient, subject=subject, text=("Text Student: True" in notes), parent=("Email Parent: True" in notes))

            loan_checkin = set_loan_checkin(email)
            if not loan_checkin:
                messagebox.showinfo("Warning", "Loan computer check-in date not set.")

            repair_window.destroy()  # Close the window after submitting
        else:
            messagebox.showerror("Error", "Dumb dumb, only numbers")

    def on_enter_pressed(event):
        repair_notes_entry.focus_set()

    def on_enter_pressed_in_repair_notes(event):
        repair_notes_entry.insert(tk.INSERT, "\n")

    # Create a new top-level window
    repair_window = tk.Toplevel()

    # Frame for the "D Number" question
    d_number_frame = tk.Frame(repair_window)
    d_number_frame.pack(fill='x', padx=10, pady=5)
    d_number_label = tk.Label(d_number_frame, text="D Number:")
    d_number_label.pack(side='left')
    d_number_entry = tk.Entry(d_number_frame, width=50)  # Text entry for D Number
    d_number_entry.pack(side='left', expand=True, fill='x')
    d_number_entry.bind('<Return>', on_enter_pressed)  # Bind Enter key to shift focus
    d_number_entry.focus_set()  # Set focus to the D number entry box

    # Frame for Charge question
    _, assetData = getAssetInfo(asset_tag)
    res = requests.get(
        Key.API_URL_Base + "maintenances?limit=1&offset=0&sort=created_at&order=desc&asset_id="
        + str(assetData["id"]), headers=headers).json()
    try:
        notes = res["rows"][0]["notes"]
    except (KeyError, IndexError):
        notes = ""

    fault = "At Fault: Yes" in (notes or "")
    charge_frame = tk.Frame(repair_window)
    charge_frame.pack(fill='x', padx=10, pady=5)

    fault_label = tk.Label(charge_frame, text="Student at Fault?:")
    fault_label.pack(side='left')
    fault = tk.BooleanVar(value=fault)
    yes = tk.Radiobutton(charge_frame, text="Yes", variable=fault, value=True)
    yes.pack(side='left')
    no = tk.Radiobutton(charge_frame, text="No  |", variable=fault, value=False)
    no.pack(side='left')

    charge_label = tk.Label(charge_frame, text="Charge: $")
    charge_label.pack(side='left')
    charge_entry = tk.Entry(charge_frame, width=10)  # Text entry for charge
    charge_entry.insert(0, "100" if "Remove Charge: True" not in notes else "0")
    charge_entry.pack(side='left', expand=True, fill='x')
    charge_entry.bind('<Return>', on_enter_pressed)  # Bind Enter key to shift focus

    divert_label = tk.Label(charge_frame, text="Divert email?")
    divert_label.pack(side='left')
    divert = tk.BooleanVar(value=False)
    divert.set(False)
    d_yes = tk.Radiobutton(charge_frame, text="Yes", variable=divert, value=True)
    d_yes.pack(side='left')
    d_no = tk.Radiobutton(charge_frame, text="No", variable=divert, value=False)
    d_no.pack(side='left')

    # Frame for the "Repair Notes" question
    repair_notes_frame = tk.Frame(repair_window)
    repair_notes_frame.pack(fill='x', padx=10, pady=5)
    repair_notes_label = tk.Label(repair_notes_frame, text="Repair Notes:")
    repair_notes_label.pack(side='left')
    repair_notes_entry = tk.Text(repair_notes_frame, height=10, width=40)  # Text widget for multiline input
    repair_notes_entry.pack(side='left', expand=True, fill='x')
    repair_notes_entry.bind('<Return>', on_enter_pressed_in_repair_notes)

    # Submit button
    submit_button = tk.Button(repair_window, text="Submit", command=submit_repair_info)
    submit_button.pack(pady=10)

    # error text
    error_text = tk.StringVar(value="")
    error_label = tk.Label(repair_window, textvariable=error_text)
    error_label.pack(pady=10)

    # Wait for the window to update its dimensions
    repair_window.update_idletasks()

    # Get the screen width and height
    screen_width = repair_window.winfo_screenwidth()
    screen_height = repair_window.winfo_screenheight()

    # Get the window width and height
    window_width = repair_window.winfo_width()
    window_height = repair_window.winfo_height()

    # Calculate the center position
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))

    # Set the position of the window to the center of the screen
    repair_window.geometry(f"+{center_x}+{center_y}")

    def updateMaintenance(asset_tag, d_number, repair_notes, atFault):
        today = str(date.today())
        url = Key.API_URL_Base + "maintenances?limit=1&offset=0&sort=created_at&order=desc&asset_id=" + str(
            assetData["id"])
        response = requests.get(url, headers=headers)
        parsedRes = response.json()

        repair_notes = " D Num: ".join([repair_notes, d_number])

        try:
            notes = parsedRes["rows"][0]["notes"] if parsedRes["rows"][0]["notes"] is not None else ""
        except LookupError as err:
            err.add_note("No maintenance found")
            error_text.set("No maintenance found")
            raise err

        if atFault is True and "At Fault: No" in notes:
            notes.replace("At Fault: No", "At Fault: Yes")
        elif atFault is False and "At Fault: Yes" in notes:
            notes.replace("At Fault: No", "At Fault: Yes")

        repair_notes = " Repair Notes: ".join([notes, repair_notes])
        # repair_notes = " Repair Notes: ".join([parsedRes["rows"][0]["notes"], repair_notes])

        print(parsedRes["rows"][0]["notes"])
        print(parsedRes["rows"][0]["start_date"]["date"])

        payload = {
            "asset_maintenance_type": "Repair",
            "completion_date": today,
            "notes": repair_notes
        }

        response2 = requests.patch(
            Key.API_URL_Base + "maintenances/" + str(parsedRes["rows"][0]["id"]), json=payload,
            headers=headers)

        payload2 = {
            "asset_tag": asset_tag,
            "model_id": assetData["model"]["id"],
            "status_id": 2
        }

        response2 = requests.put(Key.API_URL_Base + "hardware/" + str(assetData["id"]), json=payload2,
                                 headers=headers)
        print(response2.text)

    assetName = assetData["name"]
    return f"Running func6 on {assetName}"
