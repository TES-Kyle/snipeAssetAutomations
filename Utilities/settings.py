import tkinter as tk
from tkinter import messagebox
import os
import json


def settingsMenu():
    def resetAll():
        for i in range(len(keys)):
            entry_vars[i].set(defaultsDict[keys[i]])

    def reset(ind):
        entry_vars[ind].set(defaultsDict[keys[ind]])

    def checkUpdate():
        messagebox.showerror(message="this feature is not yet implemented")

    def apply():
        output = dict()
        for i in range(len(keys)):
            output[keys[i]] = entry_vars[i].get()

        open(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json", "w").write(json.dumps(output))

        settings_window.destroy()

    def cancel():
        settings_window.destroy()

    settingsDict = json.loads(open(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json").read())
    defaultsDict = json.loads(open(str(os.path.dirname(os.path.realpath(__file__))) + "/defaultSettings.json").read())

    keys = list(settingsDict.keys())

    settings_window = tk.Toplevel()

    # Update Frame
    update_frame = tk.Frame(settings_window)
    update_frame.pack(padx=10, pady=5, anchor="center")
    update_label = tk.Label(update_frame, text="Check For Updates")
    update_label.pack(side="left")
    update_button = tk.Button(update_frame, text="🗘", command=checkUpdate)
    update_button.pack(side="left")

    # Settings frame
    settings_frame = tk.Frame(settings_window)
    settings_frame.pack(padx=10, pady=5, anchor="center")

    labels = []
    entries = []
    entry_vars = []
    resets = []
    for index, label in enumerate(keys):
        labels.append(tk.Label(settings_frame, text=label))
        labels[index].grid(row=index, column=0, pady=2, padx=2)

        entry_vars.append(tk.StringVar(value=settingsDict[label]))
        entries.append(tk.Entry(settings_frame, textvariable=entry_vars[index], width=25))
        entries[index].grid(row=index, column=1, pady=2, padx=2)

        resets.append(tk.Button(settings_frame, text="⟳", command=lambda x=index: reset(x)))
        resets[index].grid(row=index, column=2, pady=2, padx=2)

    # Reset Frame
    reset_frame = tk.Frame(settings_window)
    reset_frame.pack(padx=10, pady=5, anchor="center")
    reset_label = tk.Label(reset_frame, text="Reset All")
    reset_label.pack(side="left")
    reset_button = tk.Button(reset_frame, text="⟳", command=resetAll)
    reset_button.pack(side="left")

    # End Frame
    end_frame = tk.Frame(settings_window)
    end_frame.pack(padx=10, pady=5, anchor="center", fill="x")
    end_label = tk.Button(end_frame, text="Apply", command=apply)
    end_label.pack(side="left", fill="x", expand=True)
    end_button = tk.Button(end_frame, text="Cancel", command=cancel)
    end_button.pack(side="right", fill="x", expand=True)

    # Wait for the window to update its dimensions
    settings_window.update_idletasks()

    # Get the screen width and height
    screen_width = settings_window.winfo_screenwidth()
    screen_height = settings_window.winfo_screenheight()

    # Get the window width and height
    window_width = settings_window.winfo_width()
    window_height = settings_window.winfo_height()

    # Calculate the center position
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))

    # Set the position of the window to the center of the screen
    settings_window.geometry(f"+{center_x}+{center_y}")



# Get or make setting dictionary
if os.path.isfile(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json"):
    settings = json.loads(open(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json").read())
else:
    settings = dict()

# get default settings
defaults = json.loads(open(str(os.path.dirname(os.path.realpath(__file__))) + "/defaultSettings.json").read())

# fill missing settings from defaults
for key in defaults.keys():
    if key not in settings.keys():
        settings[key] = defaults[key]

# Write settings to json file
open(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json", "w").write(json.dumps(settings))
