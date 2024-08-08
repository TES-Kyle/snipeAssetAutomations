from Utilities.otherApiBits import *
from Utilities.labelPrinting import createImage
import tkinter as tk
from datetime import date


def newRepair(asset_tag):
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

