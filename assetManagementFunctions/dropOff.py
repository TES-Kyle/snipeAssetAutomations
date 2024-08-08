from Utilities.otherApiBits import *
from Utilities.labelPrinting import createImage
import tkinter as tk
from tkinter import messagebox


def dropOff(asset_tag):
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
            putURL = Key.API_URL_Base + "hardware/" + id

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
