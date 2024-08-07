import requests
import json
import Key
import tkinter as tk
from tkinter import ttk
from tkcalendar import DateEntry
from tkinter import messagebox
from labelPrinting import createImage
from datetime import date
from emailing import sendFineEmail
import subprocess
import platform
import threading
import time

# API Key which can be created in your SnipeIT Account, place it inbetween quotes as one line
# REF: https://snipe-it.readme.io/reference/generating-api-tokens
token = Key.API_Key

# Headers used in the request library to pass the authorization bearer token
headers = {
    "accept": "application/json",
    "Authorization": "Bearer " + token,
    "content-type": "application/json"
}


def func3(asset_tag, *args):
    if args:
        printVar = args[0]
        print(printVar)
        print(args)
        createImage(printVar)
        return f"Running func3 on {asset_tag}, printing parameters {printVar}"
    else:
        print("No Args")
        junk, genericValues = getAssetInfo(asset_tag)
        printData = list()
        printData.append(genericValues["asset_tag"])
        createImage(printData)
        return f"Running func3 on {asset_tag} with generic args"


def func4(asset_tag):
    title = ""
    at_fault = 'yes'
    issue_description = ""

    def submit_response():
        title = title_entry.get()
        at_fault = 'Yes' if at_fault_var.get() == 1 else 'No'
        issue_description = issue_entry.get("1.0", tk.END).strip()

        # For now, just printing the values. You can modify this to do something else
        print(f"Title: {title}")
        print(f"User at fault: {at_fault}")
        print(f"Issue Description: {issue_description}")

        submitMaintenance(asset_tag, at_fault, issue_description, title)

        issue_window.destroy()  # Close the window after submitting

    def on_enter_pressed_in_issue_entry(event):
        if event.state & 0x0001:  # Check if Shift key is pressed
            issue_entry.insert(tk.INSERT, "\n")  # Insert a new line
        else:
            submit_response()

    def on_enter_pressed(event):
        at_fault_yes.focus_set()

    # Create a new top-level window
    issue_window = tk.Toplevel()

    # Wait for the window to update its dimensions
    issue_window.update_idletasks()

    # Get the screen width and height
    screen_width = issue_window.winfo_screenwidth()
    screen_height = issue_window.winfo_screenheight()

    # Get the window width and height
    window_width = issue_window.winfo_width()
    window_height = issue_window.winfo_height()

    # Calculate the center position
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))

    # Set the position of the window to the center of the screen
    issue_window.geometry(f"+{center_x}+{center_y}")

    # Frame for the "Title" question
    title_frame = tk.Frame(issue_window)
    title_frame.pack(fill='x', padx=10, pady=5)
    title_label = tk.Label(title_frame, text="Title:")
    title_label.pack(side='left')
    title_entry = tk.Entry(title_frame, width=50)  # Text entry for title
    title_entry.pack(side='left', expand=True, fill='x')
    title_entry.bind('<Return>', on_enter_pressed)  # Bind Enter key to shift focus
    title_entry.focus_set()  # Set focus to the D number entry box

    # Frame for the "Is the user at fault?" question
    fault_frame = tk.Frame(issue_window)
    fault_frame.pack(fill='x', padx=10, pady=5)
    at_fault_label = tk.Label(fault_frame, text="Is the user at fault?")
    at_fault_label.pack(side='left')
    at_fault_var = tk.IntVar(value=-1)  # Default value set to -1 (none selected)
    at_fault_yes = tk.Radiobutton(fault_frame, text="Yes", variable=at_fault_var, value=1)
    at_fault_yes.pack(side='left')
    at_fault_no = tk.Radiobutton(fault_frame, text="No", variable=at_fault_var, value=0)
    at_fault_no.pack(side='left')

    # Frame for the "Please describe the issue" question
    issue_frame = tk.Frame(issue_window)
    issue_frame.pack(fill='x', padx=10, pady=5)
    issue_label = tk.Label(issue_frame, text="Please describe the issue:")
    issue_label.pack(side='left')
    issue_entry = tk.Text(issue_frame, height=5, width=40)  # Text widget for multiline input
    issue_entry.pack(side='left', expand=True, fill='x')
    issue_entry.bind('<Return>', on_enter_pressed_in_issue_entry)

    # Submit button
    submit_button = tk.Button(issue_window, text="Submit", command=submit_response)
    submit_button.pack(pady=10)

    def submitMaintenance(asset_tag, at_fault, issue_description, title):
        junk, assetData = getAssetInfo(asset_tag)
        url = "https://trinityes.snipe-it.io/api/v1"
        issue_description = " At Fault: ".join([issue_description, at_fault])
        today = str(date.today())

        payload1 = {
            "status_id": assetData["status_label"]["id"]
        }

        response1 = requests.post(url + "/hardware/" + str(assetData["id"]) + "/checkin", json=payload1,
                                  headers=headers)
        print(response1.text)

        payload2 = {
            "asset_tag": asset_tag,
            "model_id": assetData["model"]["id"],
            "status_id": 17
        }

        response2 = requests.put(url + "/hardware/" + str(assetData["id"]), json=payload2, headers=headers)
        print(response2.text)

        payload3 = {
            "asset_maintenance_type": "Repair",
            "start_date": today,
            "title": title,
            "asset_id": assetData["id"],
            "supplier_id": 1,
            "notes": issue_description
        }

        response3 = requests.post(url + "/maintenances", json=payload3, headers=headers)
        print(response3.text)

        junk, assetData = getAssetInfo(asset_tag)

        printData = []
        printData.append(assetData["asset_tag"])
        printData.append(assetData["status_label"]["name"])
        printData.append(assetData["name"])
        printData.append(title)
        createImage(printData)

    return f"Running func4 on {asset_tag}"


def func5(asset_tag, *args):
    junk, genericValues = getAssetInfo(asset_tag)

    putURL =  Key.API_URL_Base + "hardware/" + str(genericValues["id"])
    print(putURL)
    payload1 = {
        "status_id": genericValues["status_label"]["id"]
    }
    payload2 = {
        "asset_tag": asset_tag,
        "model_id": genericValues["model"]["id"],
        "status_id": 9,
    }
    response = requests.post(putURL + "/checkin", json=payload1, headers=headers)
    print(response.text)
    response2 = requests.put(putURL, json=payload2, headers=headers)
    print(response2.text)
    junk, genericValues = getAssetInfo(asset_tag)
    printData = []
    printData.append(genericValues["asset_tag"])
    printData.append(genericValues["status_label"]["name"])
    printData.append(genericValues["name"])

    # createImage(printData)

    return f"Running func5 on {asset_tag}"


# Laptop Returned from Apple
def func6(asset_tag):
    def submit_repair_info(event=None):
        d_number = d_number_entry.get()
        repair_notes = repair_notes_entry.get("1.0", tk.END).strip()

        # For now, just printing the values. You can modify this to do something else
        if charge_entry.get().strip().isnumeric():
            print(f"D Number: {d_number}")
            print(f"Repair Notes: {repair_notes}")
            updateMaintenance(asset_tag, d_number, repair_notes, fault.get())
            if fault.get() and int(charge_entry.get().strip()) > 0:
                name = getLatestCheckinName(assetData["id"])
                sendFineEmail(name, int(charge_entry.get().strip()), asset_tag, divert=divert.get())
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

    fault = "At Fault: Yes" in notes
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
    charge_entry.insert(0, "100")
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
        url =  Key.API_URL_Base + "maintenances?limit=1&offset=0&sort=created_at&order=desc&asset_id=" + str(
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

        response2 = requests.put( Key.API_URL_Base + "hardware/" + str(assetData["id"]), json=payload2,
                                 headers=headers)
        print(response2.text)

    assetName = assetData["name"]
    return f"Running func6 on {assetName}"


def getAssetInfo(assetTag):
    # API URL of Snipe-IT Server -- this one includes the specific API call of listing hardware info by asset tag
    url =  Key.API_URL_Base + "hardware/bytag/"

    # Makes API request, combines Asset Tag that was passed through the function into the URL -- requires requests header
    response = requests.get(url + assetTag, headers=headers)
    # Loads the response in text format into a readable format -- requires import json header
    assetData = json.loads(response.text)
    # Returns the parsed JSON data back to where the function was called
    var_list = []

    if "asset_tag" in assetData:
        var_list.append(("Asset Tag", assetData["asset_tag"]))
    else:
        var_list.append(("Asset Tag", "null"))
    if "serial" in assetData:
        var_list.append(("Serial Number", assetData["serial"]))
    if "name" in assetData:
        var_list.append(("Asset Name", assetData["name"]))
    if "status_label" in assetData and "name" in assetData["status_label"]:
        var_list.append(("Status", assetData["status_label"]["name"]))
    if (
            "custom_fields" in assetData
            and "hingeWeak" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["hingeWeak"]
            and len(assetData["custom_fields"]["hingeWeak"]["value"]) != 0
    ):
        var_list.append(("Hinge Weak?", assetData["custom_fields"]["hingeWeak"]["value"]))
    if (
            "custom_fields" in assetData
            and "chargerInGoodCondition" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["chargerInGoodCondition"]
            and len(assetData["custom_fields"]["chargerInGoodCondition"]["value"]) != 0
    ):
        var_list.append(("Charger in Good Condition?", assetData["custom_fields"]["chargerInGoodCondition"]["value"]))
    if (
            "custom_fields" in assetData
            and "batteryData" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["batteryData"]
            and len(assetData["custom_fields"]["batteryData"]["value"]) != 0
    ):
        var_list.append(("Battery Stats", assetData["custom_fields"]["batteryData"]["value"]))
    if (
            "custom_fields" in assetData
            and "Box Number" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["Box Number"]
            and len(assetData["custom_fields"]["Box Number"]["value"]) != 0
    ):
        var_list.append(("Box Number", assetData["custom_fields"]["Box Number"]["value"]))

    # var_list = [
    # ("Asset Tag", assetData["asset_tag"]),
    # ("Serial Number", assetData["serial"]),
    # ("Asset Name", assetData["name"]),
    # ("Status", assetData["status_label"]["name"]),
    # ("Hinge Weak?", assetData["custom_fields"]["hingeWeak"]["value"]),
    # ("Charger in Good Condition?", assetData["custom_fields"]["chargerInGoodCondition"]["value"]),
    # ("Battery Stats", assetData["custom_fields"]["batteryData"]["value"]),
    # ("Box Number", assetData["custom_fields"]["Box Number"]["value"]),
    # # ...
    # # ("var10", "Variable 10")
    # ]
    return var_list, assetData


def getLatestCheckinName(asset_id):
    activity_url =  Key.API_URL_Base + f'reports/activity?limit=1&offset=0&item_type=asset&item_id={asset_id}&action_type=checkin%20from&order=desc&sort=created_at'
    activity_response = requests.get(activity_url, headers=headers)
    activity_data = activity_response.json()
    try:
        return activity_data['rows'][0]['target']['name']
    except (KeyError, IndexError):
        return None


def func1(asset_tag):
    def process_dropoff(assetData):
        if hinge.get() >=0 and charger.get() >= 0 and drop.get() >= 0:
            seniorStatus = drop.get()
            q1 = charger.get()
            sq1 = "y" if q1 == 1 else "n"
            q1_2 = cord.get()
            sq1_2 = "y" if q1_2 == 1 else "n"
            q2 = hinge.get()
            sq2 = "n" if q2 == 1 else "y"
            q3 = repair.get()
            status = 0
            box = 0
            notes = ""
            if seniorStatus == 1:
                if q3 == 0:
                    status = 18
                    try:
                        box = assetData["custom_fields"]["Box Number"]["value"]
                    except KeyError:
                        box = 412
                elif q3 == 1:
                    status = 18
                    box = 403
                    notes = "Slight damage, do not pick for 8th grade"
                elif q3 == 2:
                    status = 17
                    box = 402
                elif q3 == 3:
                    status = 21
                    box = 404
            elif seniorStatus == 0:
                if q3 == 0:
                    status = 18
                    box = 410
                else:
                    status = 17
                    box = 402

            updateAsset(str(assetData["id"]), assetData["asset_tag"], status, assetData["model"]["id"], sq1, sq1_2, sq2,
                        box, assetData, notes=notes)

            # Prints the Asset Tag info that is in every asset so we are not worried about exceptions
            var1 = assetData["asset_tag"]
            var2 = assetData["serial"]
            var3 = "Hinge Weak: " + sq2
            try:
                var4 = assetData["custom_fields"]["batteryData"]["value"]
            except KeyError:
                var4 = "No Battery Data"
            var5 = "Box: " + str(box)

            # passes the variables back to the image creator, and takes the ones that are numbers and turns them into strings so they can be concatenated
            createImage([str(var1), var2, var3, str(var4), str(var5)])
            dropoff_window.destroy()
        else:
            messagebox.showerror("Error", "Dumb dumb, answer all the questions!")


    varlist, assetData = getAssetInfo(asset_tag)
    proceed = False

    if assetData["status_label"]["id"] != 20:
        proceed = messagebox.askyesno(title="Proceed?", message='This asset is not "Pending Drop-Off"\n\nProceed anyway?')

    if assetData["status_label"]["id"] == 20 or proceed:
        # Create a new top-level window
        dropoff_window = tk.Toplevel()

        # Frame for the "Drop-Off Type" question
        type_frame = tk.Frame(dropoff_window)
        type_frame.pack(fill='x', padx=10, pady=5)
        type_label = tk.Label(type_frame, text="Drop-Off Type:")
        type_label.pack(side='left')
        drop = tk.IntVar(value=-1)
        senior = tk.Radiobutton(type_frame, text="Senior", variable=drop, value=1)
        senior.pack(side='left')
        withdraw = tk.Radiobutton(type_frame, text="Withdrawal", variable=drop, value=0)
        withdraw.pack(side='left')

        # Frame for the "Has Good Charger" question
        charger_frame = tk.Frame(dropoff_window)
        charger_frame.pack(fill='x', padx=10, pady=5)
        charger_label = tk.Label(charger_frame, text="Do they have a good charger?")
        charger_label.pack(side='left')
        charger = tk.IntVar(value=-1)
        c_yes = tk.Radiobutton(charger_frame, text="Yes", variable=charger, value=1)
        c_yes.pack(side='left')
        c_no = tk.Radiobutton(charger_frame, text="No", variable=charger, value=0)
        c_no.pack(side='left')

        # Frame for the "Has Good Cord" question
        cord_frame = tk.Frame(dropoff_window)
        cord_frame.pack(fill='x', padx=10, pady=5)
        cord_label = tk.Label(cord_frame, text="Do they have a good cord?")
        cord_label.pack(side='left')
        cord = tk.IntVar(value=-1)
        cord_yes = tk.Radiobutton(cord_frame, text="Yes", variable=cord, value=1)
        cord_yes.pack(side='left')
        cord_no = tk.Radiobutton(cord_frame, text="No", variable=cord, value=0)
        cord_no.pack(side='left')

        # Frame for the "Hinge good" question
        hinge_frame = tk.Frame(dropoff_window)
        hinge_frame.pack(fill='x', padx=10, pady=5)
        hinge_label = tk.Label(hinge_frame, text="Hinge in good condition?")
        hinge_label.pack(side='left')
        hinge = tk.IntVar(value=-1)
        h_yes = tk.Radiobutton(hinge_frame, text="Yes", variable=hinge, value=1)
        h_yes.pack(side='left')
        h_no = tk.Radiobutton(hinge_frame, text="No", variable=hinge, value=0)
        h_no.pack(side='left')

        # Frame for the "Damge level" question
        repair_frame = tk.Frame(dropoff_window)
        repair_frame.pack(fill='x', padx=10, pady=5)
        repair_label = tk.Label(repair_frame, text="Damage Level:")
        repair_label.pack(side='left')
        repair = tk.IntVar(value=0)
        none = tk.Radiobutton(repair_frame, text="Little/None", variable=repair, value=0)
        none.pack(side='left')
        minor = tk.Radiobutton(repair_frame, text="Minor", variable=repair, value=1)
        minor.pack(side='left')
        some = tk.Radiobutton(repair_frame, text="Significant", variable=repair, value=2)
        some.pack(side='left')
        lots = tk.Radiobutton(repair_frame, text="Irreparable", variable=repair, value=3)
        lots.pack(side='left')

        # Submit button
        submit_button = tk.Button(dropoff_window, text="Submit", command=lambda x=assetData: process_dropoff(x))
        submit_button.pack(pady=10)

        # Wait for the window to update its dimensions
        dropoff_window.update_idletasks()

        # Get the screen width and height
        screen_width = dropoff_window.winfo_screenwidth()
        screen_height = dropoff_window.winfo_screenheight()

        # Get the window width and height
        window_width = dropoff_window.winfo_width()
        window_height = dropoff_window.winfo_height()

        # Calculate the center position
        center_x = int((screen_width / 2) - (window_width / 2))
        center_y = int((screen_height / 2) - (window_height / 2))

        # Set the position of the window to the center of the screen
        dropoff_window.geometry(f"+{center_x}+{center_y}")

        def updateAsset(id, assetTag, statusID, modelID, chargerCond, cordCond, hingeWeak, boxNumber, assetData, notes=""):
            putURL =  Key.API_URL_Base + "hardware/" + id

            payload = {
                "asset_tag": assetTag,
                "status_id": statusID,
                "model_id": modelID,
                "notes": str(assetData["notes"]) + str(notes) if notes != "" else assetData["notes"],
                "_snipeit_chargeringoodcondition_6": chargerCond,
                "_snipeit_cordingoodcondition_11": cordCond,
                "_snipeit_hingeweak_7": hingeWeak,
                "_snipeit_box_number_5": boxNumber
            }
            response = requests.put(putURL, json=payload, headers=headers)

    return f"Running func1 on {asset_tag}"


def func2(asset_tag):
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


func_list = [func3, func4, func5, func6, func1, func2]
func_listTXT = "Print Selected", "New Repair", "Pants Shipping", "Back from Apple", "Drop-Off", "Make charger"
