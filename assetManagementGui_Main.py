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
from utilities.logging_utils import configure_logging
from utilities.api_user import (
    get_api_user_status,
    clear_cached_api_user,
    set_api_user_static_name,
)
from utilities.otherApiBits import getAssetInfo, build_asset_info_frame
from utilities.settingsMenu import settingsMenu
from utilities.settings import get_settings
from utilities.theme import get_ui_colors
from assetManagementFunctions.assetFunctionsRouting import func_list, func_listTXT
from otherManagementFunctions.otherFunctionsRouting import other_func_list, other_func_listTXT

logger = logging.getLogger(__name__)


def print_label():
    """Send the barcode label image to the printer if it exists.

    The image file is expected to be named 'barcode-label.jpg' and located
    in the utilities directory. If missing, a user-facing error is shown.
    """
    logger.debug("print_label: called")
    # Resolve the expected label path relative to the project root.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    label_path = os.path.join(script_dir, "utilities/barcode-label.jpg")
    logger.debug("print_label: label_path=%s", label_path)
    if os.path.isfile(label_path):
        # Dispatch the image to the configured printer.
        logger.info("print_label: sending label to printer, path=%s", label_path)
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
    logger.debug("open_second_window: asset_tag=%s", asset_tag)
    # Load settings and derive layout settings.
    settings = get_settings()
    try:
        button_cols = int(settings.get("guiButtonColumns", 4))
    except Exception:
        button_cols = 4
    logger.debug("open_second_window: button_cols=%s", button_cols)

    # Create the detail window and set its title.
    top = tk.Toplevel(parent)
    top.title("Asset Detail Functions")
    logger.debug("open_second_window: toplevel window created")

    # This nested function handles the logic when a function button is clicked.
    def run_func(func_index, asset_tag):
        """Execute a function with the selected asset and parameters.

        Args:
            func_index: Index into func_list/func_listTXT.
            asset_tag: Asset tag passed to the automation.
        """
        logger.debug("run_func: func_index=%s func_name=%s asset_tag=%s", func_index, func_listTXT[func_index], asset_tag)
        # Build the checked value list to pass to the automation.
        checked_values = [value for var, value in check_vars if var.get()]
        checked_values.insert(0, asset_tag)
        logger.debug("run_func: checked_values=%s", checked_values)

        try:
            # Prefer the function signature that accepts checked values.
            logger.info("run_func: invoking %s for asset_tag=%s", func_listTXT[func_index], asset_tag)
            result = func_list[func_index](asset_tag, checked_values)
        except TypeError:
            # Fallback to the basic signature when args aren't supported.
            logger.debug("run_func: TypeError on full signature, retrying with basic signature")
            result = func_list[func_index](asset_tag)
        except Exception as exc:
            logger.exception("Asset function failed (%s) for tag %s", func_listTXT[func_index], asset_tag)
            messagebox.showerror(
                "Automation Error",
                f"'{func_listTXT[func_index]}' failed for asset {asset_tag}.\n\n{exc}",
            )
            return

        # Update the main window result text and close the detail window.
        logger.info("run_func: completed func=%s asset_tag=%s result=%s", func_listTXT[func_index], asset_tag, result)
        main_app_state["result_text"].set(result)
        logger.info("Asset function completed: %s (tag=%s)", func_listTXT[func_index], asset_tag)
        top.destroy()

    # --- Widget Layout ---
    # Load asset info for the top section table.
    logger.debug("open_second_window: fetching asset info for tag=%s", asset_tag)
    try:
        var_list, _ = getAssetInfo(asset_tag)
    except Exception as exc:
        logger.exception("Failed to load asset info for %s", asset_tag)
        messagebox.showerror("Asset Lookup Failed", f"Could not fetch asset {asset_tag}.\n\n{exc}")
        top.destroy()
        return
    logger.debug("open_second_window: asset info loaded, building frame")
    # Render a simple table of asset fields with optional checkboxes.
    var_frame, check_vars = build_asset_info_frame(
        top, var_list, include_checkboxes=True, skip_first_checkbox=True, padx=5, pady=5
    )
    var_frame.pack(side="top", fill="both", expand=True, padx=10, pady=10)

    # Create function buttons in a grid.
    logger.debug("open_second_window: adding %s function buttons", len(func_listTXT))
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
    logger.debug("open_second_window: centering at x=%s y=%s", int(x), int(y))
    top.geometry(f"+{int(x)}+{int(y)}")


def create_main_window(root):
    """Initialize and build the main application window.

    Args:
        root: Root Tkinter object (tk.Tk).
    """
    logger.debug("create_main_window: starting window construction")
    # Ensure logging is configured before any UI events fire.
    configure_logging()
    settings = get_settings()
    root.title("Asset Management GUI")
    # Resolve OS theme once at window creation so all tab colours are consistent.
    _theme = get_ui_colors()
    window_state = str(settings.get("guiWindowState", "zoomed")).strip().lower()
    logger.debug("create_main_window: window_state=%s", window_state)
    # Apply requested window state when available.
    if window_state == "zoomed":
        logger.debug("create_main_window: applying zoomed state")
        root.state("zoomed")

    # Shared mutable state for widgets and callbacks.
    app_state = {}

    # Read GUI style settings with fallbacks.
    # Tab colours come directly from the OS theme (dark/light auto-detected).
    ACTIVE_TAB_COLOR   = _theme["tab_active_bg"]
    INACTIVE_TAB_COLOR = _theme["tab_inactive_bg"]
    TAB_FG_COLOR       = _theme["tab_fg"]
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
    small_font_size = max(10, base_font_size - 8)
    logger.debug("create_main_window: font_family=%s base_font_size=%s button_cols=%s", font_family, base_font_size, button_cols)

    # =========================================================================
    # == Nested Functions (Callbacks and Helpers)
    # =========================================================================

    def show_frame(frame_to_show):
        """Raise the selected frame and update tab button styles."""
        logger.debug("show_frame: raising frame=%s", frame_to_show)
        # Reset all tab buttons to inactive style; set fg explicitly so dark-mode
        # system text colour doesn't bleed through the light/dark tab background.
        for button in app_state['tab_buttons'].values():
            button.config(relief='raised', bg=INACTIVE_TAB_COLOR, fg=TAB_FG_COLOR)

        # Activate the selected tab.
        for frame, button in app_state['tab_buttons'].items():
            if frame == frame_to_show:
                logger.debug("show_frame: activating tab button for frame=%s", frame)
                button.config(relief='sunken', bg=ACTIVE_TAB_COLOR, fg=TAB_FG_COLOR)
                break

        frame_to_show.tkraise()

    def clear_radiobuttons():
        """Reset the selected asset function radio button."""
        logger.debug("clear_radiobuttons: clearing func_var selection")
        app_state['func_var'].set(-1)

    def process_asset(event=None):
        """Validate the asset tag and route to the selected automation or detail window."""
        # Read the asset tag and clear the entry for the next scan.
        asset_tag = app_state['asset_entry'].get()
        logger.debug("process_asset: asset_tag=%s", asset_tag)
        app_state['asset_entry'].delete(0, tk.END)

        # Validate the tag using the configured regex.
        settings = get_settings()
        pattern = settings.get("assetTagRegex", r"^\d{4,5}$")
        logger.debug("process_asset: validating against pattern=%s", pattern)
        try:
            is_valid = re.match(pattern, asset_tag)
        except re.error:
            logger.error("Invalid assetTagRegex setting: %s", pattern)
            pattern = r"^\d{4,5}$"
            is_valid = re.match(pattern, asset_tag)

        if is_valid:
            # Route to the selected function or open the detail picker.
            selected_func_index = app_state['func_var'].get()
            logger.debug("process_asset: tag valid, selected_func_index=%s", selected_func_index)
            if selected_func_index != -1:
                logger.info("process_asset: invoking %s for asset_tag=%s", func_listTXT[selected_func_index], asset_tag)
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
                logger.debug("process_asset: no function selected, opening detail window for tag=%s", asset_tag)
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

    # API user indicator + logout (anchored to bottom-right; no layout shifts).
    api_user_frame = tk.Frame(root)
    api_user_frame.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-12)

    api_user_text = tk.StringVar(value="API user: …")
    api_user_label = tk.Label(api_user_frame, textvariable=api_user_text, font=(font_family, small_font_size),
                              justify="right", anchor="e")
    api_user_label.pack(side="top", anchor="e")

    def _format_remaining(seconds):
        """Return MM:SS string for a remaining seconds value.

        Args:
            seconds: Number of seconds remaining, or None.

        Returns:
            Formatted string like '02:30', or empty string if None.
        """
        logger.debug("_format_remaining: seconds=%s", seconds)
        if seconds is None:
            return ""
        secs = max(0, int(seconds))
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def _update_api_user_status():
        """Update the API user indicator and logout button state."""
        logger.debug("_update_api_user_status: polling status")
        status = get_api_user_status()
        mode = status.get("mode")
        name = status.get("name")
        remaining = status.get("expires_in")
        logger.debug("_update_api_user_status: mode=%s name=%s", mode, name)

        if mode == "static" and name:
            logger.debug("_update_api_user_status: static user=%s", name)
            api_user_text.set(f"API user: {name} (static)")
            logout_btn.config(state="normal")
        elif mode == "cached" and name:
            logger.debug("_update_api_user_status: cached user=%s remaining=%s", name, remaining)
            api_user_text.set(f"API user: {name}\nAuto-logout in {_format_remaining(remaining)}")
            logout_btn.config(state="normal")
        elif mode == "fallback":
            if status.get("detail") == "static_missing":
                logger.debug("_update_api_user_status: fallback mode, static_missing")
                api_user_text.set("API user: Default key\nStatic user missing")
                logout_btn.config(state="normal")
            else:
                logger.debug("_update_api_user_status: fallback mode, default key")
                api_user_text.set("API user: Default key")
                logout_btn.config(state="disabled")
        elif mode == "prompt":
            logger.debug("_update_api_user_status: prompt mode, no user set")
            api_user_text.set("API user: not set\nPrompt on use")
            logout_btn.config(state="disabled")
        else:
            logger.debug("_update_api_user_status: unknown mode=%s", mode)
            api_user_text.set("API user: none")
            logout_btn.config(state="disabled")

    def _poll_api_user_status():
        """Poll the API user status on a steady interval."""
        logger.debug("_poll_api_user_status: tick")
        _update_api_user_status()
        root.after(1000, _poll_api_user_status)

    def _logout_api_user():
        """Clear any cached API user so the next call prompts."""
        logger.debug("_logout_api_user: logout requested")
        status = get_api_user_status()
        logger.debug("_logout_api_user: current mode=%s detail=%s", status.get("mode"), status.get("detail"))
        if status.get("mode") == "static" or status.get("detail") == "static_missing":
            logger.info("_logout_api_user: clearing static API user name")
            set_api_user_static_name("none")
        logger.info("_logout_api_user: clearing cached API user")
        clear_cached_api_user()
        _update_api_user_status()

    logout_btn = tk.Button(api_user_frame, text="Log Out", command=_logout_api_user,
                            font=(font_family, small_font_size))
    logout_btn.pack(side="top", anchor="e", pady=(2, 0))

    # MODIFIED: Settings button is now packed inside its pre-packed frame
    logger.debug("create_main_window: adding settings button")
    tk.Button(settings_frame, text="⚙️", command=settingsMenu, font=(font_family, base_font_size)).pack(pady=5)

    # Initialize API user indicator loop.
    logger.debug("create_main_window: starting API user status poll loop")
    _poll_api_user_status()

    # --- Tab 1: Asset Functions ---
    logger.debug("create_main_window: building Tab 1 - Asset Functions")
    tab1 = app_state['tab1_frame']
    app_state['asset_entry'] = tk.Entry(tab1, font=(font_family, base_font_size), width=30)
    app_state['asset_entry'].pack(pady=20)
    app_state['asset_entry'].bind('<Return>', process_asset)
    app_state['asset_entry'].bind('<KP_Enter>', process_asset)
    app_state['asset_entry'].focus_set()
    logger.debug("create_main_window: asset entry widget created and focused")

    button_frame = tk.Frame(tab1)
    button_frame.pack(padx=10, pady=20, anchor='center')
    tk.Button(button_frame, text="Enter", command=process_asset, font=(font_family, base_font_size)).pack(side='left', padx=20, pady=20)
    tk.Button(button_frame, text="Print Label", command=print_label, font=(font_family, base_font_size)).pack(side='left', padx=20,
                                                                                              pady=20)

    func_frame = tk.LabelFrame(tab1, text='Asset Functions', font=(font_family, base_font_size))
    func_frame.pack(pady=20)

    app_state['func_var'] = tk.IntVar(value=-1)
    logger.debug("create_main_window: adding %s asset function radio buttons", len(func_listTXT))
    for i, text in enumerate(func_listTXT):
        row, col = divmod(i, button_cols)
        lf = tk.Frame(func_frame)
        tk.Radiobutton(lf, text=text, variable=app_state['func_var'], value=i, font=(font_family, base_font_size)).pack(anchor='w')
        lf.grid(row=row, column=col, padx=10, pady=10)

    tk.Button(tab1, text="Clear", command=clear_radiobuttons, font=(font_family, base_font_size)).pack(pady=20)

    app_state['result_text'] = tk.StringVar()
    tk.Label(tab1, textvariable=app_state['result_text'], font=(font_family, base_font_size)).pack(pady=20)

    # --- Tab 2: Other Functions ---
    logger.debug("create_main_window: building Tab 2 - Other Functions")
    tab2 = app_state['tab2_frame']

    other_frame = tk.LabelFrame(tab2, text='Other Functions', font=(font_family, base_font_size))
    other_frame.pack(pady=20)

    logger.debug("create_main_window: adding %s other function buttons", len(other_func_listTXT))
    for i, text in enumerate(other_func_listTXT):
        row, col = divmod(i, button_cols)
        button = tk.Button(other_frame, text=text, command=other_func_list[i], height=2, font=(font_family, base_font_size))
        button.grid(row=row, column=col, sticky='ew', padx=10, pady=10)

    # Select the first tab on startup.
    logger.info("create_main_window: window construction complete, showing tab 1")
    show_frame(app_state['tab1_frame'])


# =========================================================================
# == Application Entry Point
# =========================================================================
if __name__ == "__main__":
    configure_logging()
    logger.info("assetManagementGui_Main: application starting")
    main_window = tk.Tk()
    from utilities import Key as _Key
    if _Key.SECRETS_LOAD_ERROR:
        logger.error("assetManagementGui_Main: secrets load error: %s", _Key.SECRETS_LOAD_ERROR)
        messagebox.showerror(
            "Configuration Error",
            "Credential Loading Error.\n\n"
            + _Key.SECRETS_LOAD_ERROR
            + "\n\nThe app will start but some features may not work."
        )
    logger.debug("assetManagementGui_Main: calling create_main_window")
    create_main_window(main_window)
    logger.info("assetManagementGui_Main: entering mainloop")
    main_window.mainloop()
