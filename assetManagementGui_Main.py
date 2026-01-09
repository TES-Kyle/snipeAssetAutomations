"""Main GUI entry point for Asset Automations.

This module builds the main Tkinter window used by the Asset Automations
tool, wires button callbacks to automation functions, and handles
asset tag input/validation.
"""

import logging
import os
import re
import tkinter as tk
from tkinter import messagebox

from utilities.labelPrinting import sendToPrinter
from utilities.logging_utils import configure_logging, get_settings
from utilities.otherApiBits import getAssetInfo
from utilities.settings import settingsMenu
from assetManagementFunctions.assetFunctionsRouting import func_list, func_listTXT
from otherManagementFunctions.otherFunctionsRouting import other_func_list, other_func_listTXT

logger = logging.getLogger(__name__)


def print_label():
    """Send the barcode label image to the printer if it exists.

    The image file is expected to be named 'barcode-label.jpg' and located
    in the utilities directory. If missing, a user-facing error is shown.
    """
    # Resolve the expected label path relative to the project root.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    label_path = os.path.join(script_dir, "utilities/barcode-label.jpg")
    if os.path.isfile(label_path):
        # Dispatch the image to the configured printer.
        sendToPrinter(label_path)
        logger.info("Label sent to printer: %s", label_path)
        return

    # Show a user-facing error if the label image is missing.
    logger.error("Barcode label image not found: %s", label_path)
    messagebox.showerror("Print Label", "Barcode label image not found. Generate a label first.")


def open_second_window(parent, asset_tag, main_app_state):
    """Create a secondary window to display asset info and select functions.

    This window appears when an asset is entered on the main screen without
    a function pre-selected, letting the user choose from all asset actions.

    Args:
        parent: Parent Tk window.
        asset_tag: Asset tag entered by the user.
        main_app_state: State dict from main window, used to update result label.
    """
    # Load settings and derive layout settings.
    settings = get_settings()
    try:
        button_cols = int(settings.get("guiButtonColumns", 4))
    except Exception:
        button_cols = 4

    # Create the detail window and set its title.
    top = tk.Toplevel(parent)
    top.title("Asset Detail Functions")

    # This nested function handles the logic when a function button is clicked.
    def run_func(func_index, asset_tag):
        """Execute a function with the selected asset and parameters.

        Args:
            func_index: Index into func_list/func_listTXT.
            asset_tag: Asset tag passed to the automation.
        """
        # Build the checked value list to pass to the automation.
        checked_values = [value for var, value in check_vars if var.get()]
        checked_values.insert(0, asset_tag)

        try:
            # Prefer the function signature that accepts checked values.
            result = func_list[func_index](asset_tag, checked_values)
        except TypeError:
            # Fallback to the basic signature when args aren't supported.
            result = func_list[func_index](asset_tag)
        except Exception as exc:
            logger.exception("Asset function failed (%s) for tag %s", func_listTXT[func_index], asset_tag)
            messagebox.showerror(
                "Automation Error",
                f"'{func_listTXT[func_index]}' failed for asset {asset_tag}.\n\n{exc}",
            )
            return

        # Update the main window result text and close the detail window.
        main_app_state["result_text"].set(result)
        logger.info("Asset function completed: %s (tag=%s)", func_listTXT[func_index], asset_tag)
        top.destroy()

    # --- Widget Layout ---
    # Load asset info for the top section table.
    try:
        var_list, _ = getAssetInfo(asset_tag)
    except Exception as exc:
        logger.exception("Failed to load asset info for %s", asset_tag)
        messagebox.showerror("Asset Lookup Failed", f"Could not fetch asset {asset_tag}.\n\n{exc}")
        top.destroy()
        return
    check_vars = []

    # Render a simple table of asset fields with optional checkboxes.
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

    # Create function buttons in a grid.
    button_frame = tk.Frame(top)
    button_frame.pack(side="top", fill="both", padx=10, pady=5)
    for i, text in enumerate(func_listTXT):
        row, col = divmod(i, button_cols)
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
    """Initialize and build the main application window.

    Args:
        root: Root Tkinter object (tk.Tk).
    """
    # Ensure logging is configured before any UI events fire.
    configure_logging()
    settings = get_settings()
    root.title("Asset Management GUI")
    window_state = str(settings.get("guiWindowState", "zoomed")).strip().lower()
    # Apply requested window state when available.
    if window_state == "zoomed":
        root.state("zoomed")

    # Shared mutable state for widgets and callbacks.
    app_state = {}

    # Read GUI style settings with fallbacks.
    ACTIVE_TAB_COLOR = settings.get("guiActiveTabColor", "#d9d9d9")
    INACTIVE_TAB_COLOR = settings.get("guiInactiveTabColor", "#f0f0f0")
    font_family = settings.get("guiFontFamily", "Arial")
    try:
        base_font_size = int(settings.get("guiFontSize", 20))
    except Exception:
        base_font_size = 20
    try:
        tab_font_size = int(settings.get("guiTabFontSize", base_font_size))
    except Exception:
        tab_font_size = base_font_size
    try:
        button_cols = int(settings.get("guiButtonColumns", 4))
    except Exception:
        button_cols = 4

    # =========================================================================
    # == Nested Functions (Callbacks and Helpers)
    # =========================================================================

    def show_frame(frame_to_show):
        """Raise the selected frame and update tab button styles."""
        # Reset all tab buttons to inactive style.
        for button in app_state['tab_buttons'].values():
            button.config(relief='raised', bg=INACTIVE_TAB_COLOR)

        # Activate the selected tab.
        for frame, button in app_state['tab_buttons'].items():
            if frame == frame_to_show:
                button.config(relief='sunken', bg=ACTIVE_TAB_COLOR)
                break

        frame_to_show.tkraise()

    def clear_radiobuttons():
        """Reset the selected asset function radio button."""
        app_state['func_var'].set(-1)

    def process_asset(event=None):
        """Validate the asset tag and route to the selected automation or detail window."""
        # Read the asset tag and clear the entry for the next scan.
        asset_tag = app_state['asset_entry'].get()
        app_state['asset_entry'].delete(0, tk.END)

        # Validate the tag using the configured regex.
        settings = get_settings()
        pattern = settings.get("assetTagRegex", r"^\d{4,5}$")
        try:
            is_valid = re.match(pattern, asset_tag)
        except re.error:
            logger.error("Invalid assetTagRegex setting: %s", pattern)
            pattern = r"^\d{4,5}$"
            is_valid = re.match(pattern, asset_tag)

        if is_valid:
            # Route to the selected function or open the detail picker.
            selected_func_index = app_state['func_var'].get()
            if selected_func_index != -1:
                try:
                    result = func_list[selected_func_index](asset_tag)
                    app_state['result_text'].set(result)
                    logger.info("Asset function completed: %s (tag=%s)", func_listTXT[selected_func_index], asset_tag)
                except Exception as exc:
                    logger.exception(
                        "Asset function failed (%s) for tag %s",
                        func_listTXT[selected_func_index],
                        asset_tag,
                    )
                    messagebox.showerror(
                        "Automation Error",
                        f"'{func_listTXT[selected_func_index]}' failed for asset {asset_tag}.\n\n{exc}",
                    )
            else:
                open_second_window(root, asset_tag, app_state)
        else:
            # Reject invalid tags and alert the user.
            logger.warning("Invalid asset tag input: %s", asset_tag)
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
    tab1_label_button = tk.Label(tab_button_frame, text="Asset Functions", font=(font_family, tab_font_size),
                                 borderwidth=2, relief='raised', padx=5, pady=5)
    tab1_label_button.pack(side='left', padx=0, pady=10)  # Reduced pady
    tab1_label_button.bind("<Button-1>", lambda event: show_frame(app_state['tab1_frame']))

    tab2_label_button = tk.Label(tab_button_frame, text="Other Functions", font=(font_family, tab_font_size),
                                 borderwidth=2, relief='raised', padx=5, pady=5)
    tab2_label_button.pack(side='left', padx=0, pady=10)  # Reduced pady
    tab2_label_button.bind("<Button-1>", lambda event: show_frame(app_state['tab2_frame']))

    app_state['tab_buttons'] = {
        app_state['tab1_frame']: tab1_label_button,
        app_state['tab2_frame']: tab2_label_button
    }

    # MODIFIED: Settings button is now packed inside its pre-packed frame
    tk.Button(settings_frame, text="⚙️", command=settingsMenu, font=(font_family, base_font_size)).pack(pady=5)

    # --- Tab 1: Asset Functions ---
    tab1 = app_state['tab1_frame']
    app_state['asset_entry'] = tk.Entry(tab1, font=(font_family, base_font_size), width=30)
    app_state['asset_entry'].pack(pady=20)
    app_state['asset_entry'].bind('<Return>', process_asset)
    app_state['asset_entry'].bind('<KP_Enter>', process_asset)
    app_state['asset_entry'].focus_set()

    button_frame = tk.Frame(tab1)
    button_frame.pack(padx=10, pady=20, anchor='center')
    tk.Button(button_frame, text="Enter", command=process_asset, font=(font_family, base_font_size)).pack(side='left', padx=20, pady=20)
    tk.Button(button_frame, text="Print Label", command=print_label, font=(font_family, base_font_size)).pack(side='left', padx=20,
                                                                                              pady=20)

    func_frame = tk.LabelFrame(tab1, text='Asset Functions', font=(font_family, base_font_size))
    func_frame.pack(pady=20)

    app_state['func_var'] = tk.IntVar(value=-1)
    for i, text in enumerate(func_listTXT):
        row, col = divmod(i, button_cols)
        lf = tk.Frame(func_frame)
        tk.Radiobutton(lf, text=text, variable=app_state['func_var'], value=i, font=(font_family, base_font_size)).pack(anchor='w')
        lf.grid(row=row, column=col, padx=10, pady=10)

    tk.Button(tab1, text="Clear", command=clear_radiobuttons, font=(font_family, base_font_size)).pack(pady=20)

    app_state['result_text'] = tk.StringVar()
    tk.Label(tab1, textvariable=app_state['result_text'], font=(font_family, base_font_size)).pack(pady=20)

    # --- Tab 2: Other Functions ---
    tab2 = app_state['tab2_frame']

    other_frame = tk.LabelFrame(tab2, text='Other Functions', font=(font_family, base_font_size))
    other_frame.pack(pady=20)

    for i, text in enumerate(other_func_listTXT):
        row, col = divmod(i, button_cols)
        button = tk.Button(other_frame, text=text, command=other_func_list[i], height=2, font=(font_family, base_font_size))
        button.grid(row=row, column=col, sticky='ew', padx=10, pady=10)


    # Select the first tab on startup.
    show_frame(app_state['tab1_frame'])


# =========================================================================
# == Application Entry Point
# =========================================================================
if __name__ == "__main__":
    configure_logging()
    main_window = tk.Tk()
    create_main_window(main_window)
    main_window.mainloop()
