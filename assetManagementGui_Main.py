import os
import re
import tkinter as tk
from tkinter import messagebox

from utilities.labelPrinting import sendToPrinter
from utilities.otherApiBits import getAssetInfo
from utilities.settings import settingsMenu
from assetFunctionsRouting import func_list, func_listTXT
from otherFunctionsRouting import other_func_list, other_func_listTXT


def print_label():
    """Checks for and sends the barcode label image to the printer.

    The image file is expected to be named 'barcode-label.jpg' and located
    in the same directory as this script.
    """
    script_dir = os.path.dirname(os.path.realpath(__file__))
    label_path = os.path.join(script_dir, "barcode-label.jpg")
    if os.path.isfile(label_path):
        sendToPrinter(label_path)


def open_second_window(parent, asset_tag, main_app_state):
    """Creates a secondary window to display asset info and select functions.

    This window appears when an asset is entered on the main screen without
    a function pre-selected.

    Args:
        parent (tk.Tk | tk.Toplevel): The parent window.
        asset_tag (str): The asset tag entered by the user.
        main_app_state (dict): The state dictionary from the main window, used
                               to update the result label.
    """
    top = tk.Toplevel(parent)
    top.title("Asset Detail Functions")

    # This nested function handles the logic when a function button is clicked.
    def run_func(func_index, asset_tag):
        """Executes a function with the selected asset and parameters."""
        checked_values = [value for var, value in check_vars if var.get()]
        checked_values.insert(0, asset_tag)

        result = func_list[func_index](asset_tag, checked_values)
        main_app_state['result_text'].set(result)
        top.destroy()

    # --- Widget Layout ---
    var_list, _ = getAssetInfo(asset_tag)
    check_vars = []

    var_frame = tk.Frame(top)
    var_frame.pack(side="top", fill="both", expand=True, padx=10, pady=10)
    for i, (name, value) in enumerate(var_list):
        check_var = tk.BooleanVar()
        if i != 0:
            tk.Checkbutton(var_frame, variable=check_var).grid(row=i, column=0, sticky='ew')

        tk.Label(var_frame, text=name, relief='solid', borderwidth=1, anchor='e').grid(row=i, column=1, sticky='ew',
                                                                                       padx=5, pady=5)
        tk.Label(var_frame, text=value, relief='solid', borderwidth=1, anchor='w').grid(row=i, column=2, sticky='ew',
                                                                                        padx=5, pady=5)
        check_vars.append((check_var, value))

    var_frame.grid_columnconfigure(0, weight=1)
    var_frame.grid_columnconfigure(1, weight=1)
    var_frame.grid_columnconfigure(2, weight=1)

    button_frame = tk.Frame(top)
    button_frame.pack(side="top", fill="both", padx=10, pady=5)
    for i, text in enumerate(func_listTXT):
        row, col = divmod(i, 4)
        button = tk.Button(button_frame, text=text, command=lambda j=i: run_func(j, asset_tag), height=2)
        button.grid(row=row, column=col, sticky='ew')

    tk.Button(top, text="Close", command=top.destroy, width=15).pack(side="top", pady=10)

    # --- Center Window on Screen ---
    top.update_idletasks()
    screen_width = top.winfo_screenwidth()
    screen_height = top.winfo_screenheight()
    x = (screen_width / 2) - (top.winfo_width() / 2)
    y = (screen_height / 2) - (top.winfo_height() / 2)
    top.geometry(f"+{int(x)}+{int(y)}")


def create_main_window(root):
    """Initializes and builds the main application window.

    Args:
        root (tk.Tk): The root Tkinter object.
    """
    root.title("Asset Management GUI")
    root.state('zoomed')

    app_state = {}

    ACTIVE_TAB_COLOR = "#d9d9d9"
    INACTIVE_TAB_COLOR = "#f0f0f0"

    # =========================================================================
    # == Nested Functions (Callbacks and Helpers)
    # =========================================================================

    def show_frame(frame_to_show):
        """Raises the selected frame and updates button styles to show the active tab."""
        for button in app_state['tab_buttons'].values():
            button.config(relief='raised', bg=INACTIVE_TAB_COLOR)

        for frame, button in app_state['tab_buttons'].items():
            if frame == frame_to_show:
                button.config(relief='sunken', bg=ACTIVE_TAB_COLOR)
                break

        frame_to_show.tkraise()

    def clear_radiobuttons():
        app_state['func_var'].set(-1)

    def process_asset(event=None):
        asset_tag = app_state['asset_entry'].get()
        app_state['asset_entry'].delete(0, tk.END)

        if re.match(r"^\d{4,5}$", asset_tag):
            selected_func_index = app_state['func_var'].get()
            if selected_func_index != -1:
                result = func_list[selected_func_index](asset_tag)
                app_state['result_text'].set(result)
            else:
                open_second_window(root, asset_tag, app_state)
        else:
            messagebox.showerror("Invalid Input", "Please enter a 4 or 5 digit asset tag.")

    # =========================================================================
    # == Main Window UI Construction
    # =========================================================================

    # --- NEW: Top bar to hold tabs and settings button ---
    top_bar_frame = tk.Frame(root)
    top_bar_frame.pack(side="top", fill="x", padx=10, pady=5)

    # MODIFIED: Frame for tabs is now packed inside the top_bar_frame
    tab_button_frame = tk.Frame(top_bar_frame)
    tab_button_frame.pack(side="left")

    # MODIFIED: Settings frame is now packed inside the top_bar_frame
    settings_frame = tk.Frame(top_bar_frame)
    settings_frame.pack(side="right")

    # MODIFIED: Main content container is now packed to fill the remaining space
    main_container = tk.Frame(root)
    main_container.pack(side="top", fill="both", expand=True)

    app_state['tab1_frame'] = tk.Frame(main_container)
    app_state['tab2_frame'] = tk.Frame(main_container)

    # The grid layout for stacking the tab frames remains the same
    app_state['tab1_frame'].grid(row=0, column=0, sticky="nsew")
    app_state['tab2_frame'].grid(row=0, column=0, sticky="nsew")
    main_container.grid_rowconfigure(0, weight=1)
    main_container.grid_columnconfigure(0, weight=1)

    # --- Create custom tab "buttons" using tk.Label for full style control ---
    tab1_label_button = tk.Label(tab_button_frame, text="Asset Functions", font=('Arial', 20),
                                 borderwidth=2, relief='raised', padx=5, pady=5)
    tab1_label_button.pack(side='left', padx=0, pady=10)  # Reduced pady
    tab1_label_button.bind("<Button-1>", lambda event: show_frame(app_state['tab1_frame']))

    tab2_label_button = tk.Label(tab_button_frame, text="Other Functions", font=('Arial', 20),
                                 borderwidth=2, relief='raised', padx=5, pady=5)
    tab2_label_button.pack(side='left', padx=0, pady=10)  # Reduced pady
    tab2_label_button.bind("<Button-1>", lambda event: show_frame(app_state['tab2_frame']))

    app_state['tab_buttons'] = {
        app_state['tab1_frame']: tab1_label_button,
        app_state['tab2_frame']: tab2_label_button
    }

    # MODIFIED: Settings button is now packed inside its pre-packed frame
    tk.Button(settings_frame, text="⚙️", command=settingsMenu, font=('Arial', 20)).pack(pady=5)

    # --- Tab 1: Asset Functions ---
    tab1 = app_state['tab1_frame']
    app_state['asset_entry'] = tk.Entry(tab1, font=('Arial', 20), width=30)
    app_state['asset_entry'].pack(pady=20)
    app_state['asset_entry'].bind('<Return>', process_asset)
    app_state['asset_entry'].bind('<KP_Enter>', process_asset)
    app_state['asset_entry'].focus_set()

    button_frame = tk.Frame(tab1)
    button_frame.pack(padx=10, pady=20, anchor='center')
    tk.Button(button_frame, text="Enter", command=process_asset, font=('Arial', 20)).pack(side='left', padx=20, pady=20)
    tk.Button(button_frame, text="Print Label", command=print_label, font=('Arial', 20)).pack(side='left', padx=20,
                                                                                              pady=20)

    func_frame = tk.LabelFrame(tab1, text='Asset Functions', font=('Arial', 20))
    func_frame.pack(pady=20)

    app_state['func_var'] = tk.IntVar(value=-1)
    for i, text in enumerate(func_listTXT):
        row, col = divmod(i, 4)
        lf = tk.Frame(func_frame)
        tk.Radiobutton(lf, text=text, variable=app_state['func_var'], value=i, font=('Arial', 20)).pack(anchor='w')
        lf.grid(row=row, column=col, padx=10, pady=10)

    tk.Button(tab1, text="Clear", command=clear_radiobuttons, font=('Arial', 20)).pack(pady=20)

    app_state['result_text'] = tk.StringVar()
    tk.Label(tab1, textvariable=app_state['result_text'], font=('Arial', 20)).pack(pady=20)

    # --- Tab 2: Other Functions ---
    tab2 = app_state['tab2_frame']

    other_frame = tk.LabelFrame(tab2, text='Other Functions', font=('Arial', 20))
    other_frame.pack(pady=20)

    for i, text in enumerate(other_func_listTXT):
        row, col = divmod(i, 4)
        button = tk.Button(other_frame, text=text, command=other_func_list[i], height=2, font=('Arial', 20))
        button.grid(row=row, column=col, sticky='ew', padx=10, pady=10)


    show_frame(app_state['tab1_frame'])


# =========================================================================
# == Application Entry Point
# =========================================================================
if __name__ == "__main__":
    main_window = tk.Tk()
    create_main_window(main_window)
    main_window.mainloop()