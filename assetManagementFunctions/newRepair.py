from utilities.otherApiBits import *
from utilities.labelPrinting import createImage
from utilities.messaging import *
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
    
    # Info Frame
    var_list, assetData = getAssetInfo(asset_tag)
    info_frame = tk.Frame(issue_window)  # create a frame for the variables
    info_frame.grid(row=0, column=0, sticky='nsew')

    for i, (name, value) in enumerate(var_list):
        label_name = tk.Label(info_frame, text=name, relief='solid', borderwidth=1, anchor='e')
        label_name.grid(row=i, column=0, sticky='ew', padx=5, pady=5)  # add the name label to the grid

        label_value = tk.Label(info_frame, text=value, relief='solid', borderwidth=1, anchor='w')
        label_value.grid(row=i, column=1, sticky='ew', padx=5, pady=5)  # add the value label to the grid

    # Entry Frame
    entry_frame = tk.Frame(issue_window)
    entry_frame.grid(row=0, column=1, sticky='nsew')

    # Frame for the "Title" question
    title_frame = tk.Frame(entry_frame)
    title_frame.pack(fill='x', padx=10, pady=5)
    title_label = tk.Label(title_frame, text="Title:")
    title_label.pack(side='left')
    title_entry = tk.Entry(title_frame, width=50)  # Text entry for title
    title_entry.pack(side='left', expand=True, fill='x')
    title_entry.bind('<Return>', on_enter_pressed)  # Bind Enter key to shift focus
    title_entry.focus_set()  # Set focus to the D number entry box

    # Frame for the "Is the user at fault?" question
    fault_frame = tk.Frame(entry_frame)
    fault_frame.pack(fill='x', padx=10, pady=5)
    at_fault_label = tk.Label(fault_frame, text="Is the user at fault?")
    at_fault_label.pack(side='left')
    at_fault_var = tk.IntVar(value=-1)  # Default value set to -1 (none selected)
    at_fault_yes = tk.Radiobutton(fault_frame, text="Yes", variable=at_fault_var, value=1)
    at_fault_yes.pack(side='left')
    at_fault_no = tk.Radiobutton(fault_frame, text="No", variable=at_fault_var, value=0)
    at_fault_no.pack(side='left')

    # Frame for Emailing questions
    email_frame = tk.Frame(entry_frame)
    email_frame.pack(fill='x', padx=10, pady=5)
    email_label = tk.Label(email_frame, text="Send Emails")
    email_label.pack(side='left')
    email_var = tk.BooleanVar(value=False)  # Default value set to -1 (none selected)
    email = tk.Checkbutton(email_frame, variable=email_var)
    email.pack(side='left')
    text_label = tk.Label(email_frame, text="Text Student?")
    text_label.pack(side='left')
    text_var = tk.BooleanVar(value=False) # Default value set to -1 (none selected)
    text = tk.Checkbutton(email_frame, variable=text_var)
    text.pack(side='left')
    parent_label = tk.Label(email_frame, text="Email Parents?")
    parent_label.pack(side='left')
    parent_var = tk.BooleanVar(value=True)  # Default value set to -1 (none selected)
    parent = tk.Checkbutton(email_frame, variable=parent_var)
    parent.pack(side='left')

    # Frame for the "Please describe the issue" question
    issue_frame = tk.Frame(entry_frame)
    issue_frame.pack(fill='x', padx=10, pady=5)
    issue_label = tk.Label(issue_frame, text="Please describe the issue:")
    issue_label.pack(side='left')
    issue_entry = tk.Text(issue_frame, height=5, width=40)  # Text widget for multiline input
    issue_entry.pack(side='left', expand=True, fill='x')
    issue_entry.bind('<Return>', on_enter_pressed_in_issue_entry)

    # Submit button
    submit_button = tk.Button(entry_frame, text="Submit", command=submit_response)
    submit_button.pack(pady=10)

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

    def submitMaintenance(asset_tag, at_fault, issue_description, title):
        junk, assetData = getAssetInfo(asset_tag)
        url = "https://trinityes.snipe-it.io/api/v1"
        issue_description = " At Fault: ".join([issue_description, at_fault])
        issue_description += " Send Emails: " + str(email_var.get())
        issue_description += " Text Student: " + str(text_var.get())
        issue_description += " Email Parent: " + str(parent_var.get())

        if email_var.get() and assetData.get("assigned_to", {}).get("email"):
            full_name = assetData["assigned_to"]["name"]

            if remove_fine_warning(assetData["assigned_to"]["email"]):
                content = repair_notice_no_fine(full_name)
                issue_description += " Remove Charge: True"
            else:
                content = repair_notice(full_name)

            subject = "Repair Notice"
            recipient = assetData["assigned_to"]["email"]

            if not is_email(recipient):
                subject = "Error email not valid: " + subject
                recipient = support_email

            message(content, recipient, subject=subject, text_student_recipient=text_var.get(), email_parent=parent_var.get())



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

