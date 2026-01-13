"""Settings UI and persistence helpers.

This module renders the Settings window, loads/saves settings.json,
and applies changes to logging without requiring an app restart.
"""

import json
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

from utilities.logging_utils import configure_logging


def settingsMenu():
    """Render the settings window with schema-based grouping.

    Loads settings.json + defaultSettings.json, then uses settingsSchema.json
    to build a categorized, scrollable UI with reset/apply controls.
    """
    def _safe_read_json(path):
        """Read a JSON file path and return a dict fallback on failure.

        Args:
            path: Filesystem path to a JSON file.

        Returns:
            Dict parsed from JSON or {} on failure.
        """
        try:
            return json.loads(open(path).read())
        except Exception:
            return {}

    def resetAll():
        """Reset all editable fields to their default values."""
        # Reset every known entry variable to default values.
        for key in keys:
            if key in entry_by_key:
                entry_by_key[key].set(defaultsDict.get(key, ""))

    def reset(ind):
        """Reset a single entry by index to its default value."""
        # Reset the entry by index (aligned with keys list).
        entry_vars[ind].set(defaultsDict.get(keys[ind], ""))

    def checkUpdate():
        """Check for updates against the repo URL stored in meta.json.

        Uses the embedded meta.json file to discover repo URL and branch,
        then queries the GitHub API for the latest commit.
        """
        import subprocess, sys, datetime
        try:
            app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # …/Resources/app
            meta_path = os.path.join(app_root, ".build", "meta.json")
            if not os.path.isfile(meta_path):
                messagebox.showerror("Update", "Missing meta.json — please reinstall.")
                return

            meta = json.loads(open(meta_path).read())
            repo_url = meta.get("repo_url", "").strip()
            branch = meta.get("branch", "main").strip()
            installed_sha = meta.get("installed_sha", "unknown").strip()

            if not repo_url or "github.com" not in repo_url:
                messagebox.showerror("Update", "Unsupported or missing repo URL in meta.json.")
                return

            # Normalize repo owner/name from URL
            # Examples: https://github.com/owner/repo or .../owner/repo.git
            tail = repo_url.split("github.com/")[-1]
            owner_repo = tail.split(".git")[0].strip("/")

            # Query GitHub API for latest commit on branch (unauthenticated)
            import requests
            api = f"https://api.github.com/repos/{owner_repo}/commits/{branch}"
            r = requests.get(api, timeout=15)
            if r.status_code != 200:
                messagebox.showerror("Update", f"Failed to check updates.\nHTTP {r.status_code}")
                return
            latest_sha = r.json().get("sha", "").strip()

            if not latest_sha:
                messagebox.showerror("Update", "Could not determine the latest commit SHA.")
                return

            if latest_sha == installed_sha:
                messagebox.showinfo("Update", "You're up to date.")
                # Optionally update last_checked:
                meta["last_checked"] = datetime.datetime.now().isoformat()
                open(meta_path, "w").write(json.dumps(meta))
                return

            # Offer to update
            resp = messagebox.askyesno(
                "Update available",
                "A new version is available.\n\nInstalled:\n"
                f"{installed_sha[:7]}\nLatest:\n{latest_sha[:7]}\n\nUpdate now?"
            )
            if not resp:
                return

            # Run the embedded updater (it shows its own progress dialogs)
            updater = os.path.join(app_root, "shellScripts", "update_in_place.command")
            if not os.path.isfile(updater):
                messagebox.showerror("Update", "Updater script not found.\nPlease reinstall.")
                return

            # Launch updater detached so GUI stays responsive; updater will mutate files then prompt to restart.
            subprocess.Popen(
                ["bash", "-lc", f"exec {json.dumps(updater)}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
            )

            messagebox.showinfo("Update", "Update started.\n\nOnce complete, please quit and relaunch the app.")
        except Exception as e:
            messagebox.showerror("Update error", str(e))

    def make_installer_usb():
        """Launch the USB installer builder script."""
        try:
            app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            usb_maker = os.path.join(app_root, "shellScripts", "make_installer_usb.command")
            if not os.path.isfile(usb_maker):
                messagebox.showerror("USB Installer", "make_installer_usb.command not found.")
                return
            import subprocess
            subprocess.Popen(
                ["bash", "-lc", f"exec {json.dumps(usb_maker)}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            messagebox.showerror("USB Installer", str(e))

    def apply():
        """Persist settings, refresh logging config, and close the window."""
        output = dict()
        # Gather all known keys, preserving existing values for non-editable fields.
        for key in keys:
            if key in entry_by_key:
                output[key] = entry_by_key[key].get()
            else:
                output[key] = settingsDict.get(key, defaultsDict.get(key, ""))

        # Persist settings and refresh logging without restart.
        open(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json", "w").write(json.dumps(output))
        configure_logging()

        settings_window.destroy()

    def cancel():
        """Close the settings window without applying changes."""
        settings_window.destroy()

    # Load persisted settings, defaults, and schema for UI layout.
    settingsDict = _safe_read_json(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json")
    defaultsDict = _safe_read_json(str(os.path.dirname(os.path.realpath(__file__))) + "/defaultSettings.json")
    schemaDict = _safe_read_json(str(os.path.dirname(os.path.realpath(__file__))) + "/settingsSchema.json")

    # Merge keys from settings and defaults to ensure all fields render.
    keys = list(settingsDict.keys())
    for key in defaultsDict.keys():
        if key not in keys:
            keys.append(key)

    # Main settings window shell.
    settings_window = tk.Toplevel()
    screen_width = settings_window.winfo_screenwidth()
    screen_height = settings_window.winfo_screenheight()
    window_width = min(880, int(screen_width * 0.8))
    window_height = min(800, int(screen_height * 0.85))
    settings_window.geometry(f"{window_width}x{window_height}")
    settings_window.minsize(680, 550)

    base_font = tkfont.nametofont("TkDefaultFont")
    label_font = base_font.copy()
    label_font.configure(weight="bold")
    group_font = base_font.copy()
    group_font.configure(weight="bold")
    desc_font = base_font.copy()
    desc_font.configure(size=max(base_font.cget("size") - 1, 8))

    # Update Frame (check for app updates).
    update_frame = tk.Frame(settings_window)
    update_frame.pack(padx=10, pady=5, anchor="center")
    update_label = tk.Label(update_frame, text="Check For Updates")
    update_label.pack(side="left")
    update_button = tk.Button(update_frame, text="🗘", command=checkUpdate)
    update_button.pack(side="left")
    usb_button = tk.Button(update_frame, text="Make Installer USB", command=make_installer_usb)
    usb_button.pack(side="left", padx=(10, 0))

    # Settings list frame (scrollable).
    list_frame = tk.Frame(settings_window)
    list_frame.pack(fill="both", expand=True, padx=10, pady=5)

    canvas = tk.Canvas(list_frame, borderwidth=0, highlightthickness=0)
    scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas)
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(_event):
        """Update the scrollregion when the inner frame resizes."""
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event):
        """Stretch the inner frame to match the canvas width."""
        canvas.itemconfig(window_id, width=event.width)

    inner.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event):
        """Scroll the canvas with the mouse wheel."""
        # Normalize scroll direction for platform differences.
        if event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            canvas.yview_scroll(1, "units")

    def _bind_mousewheel(_event=None):
        """Bind mouse wheel events to the settings window."""
        settings_window.bind_all("<MouseWheel>", _on_mousewheel)
        settings_window.bind_all("<Button-4>", _on_mousewheel)
        settings_window.bind_all("<Button-5>", _on_mousewheel)

    def _unbind_mousewheel(_event=None):
        """Unbind mouse wheel events when focus leaves the window."""
        settings_window.unbind_all("<MouseWheel>")
        settings_window.unbind_all("<Button-4>")
        settings_window.unbind_all("<Button-5>")

    settings_window.bind("<Enter>", _bind_mousewheel)
    settings_window.bind("<Leave>", _unbind_mousewheel)

    labels = []
    entries = []
    entry_vars = []
    resets = []
    entry_by_key = {}

    def _add_setting_row(parent, key, label_text, description):
        """Create a labeled entry row with reset button and description."""
        row = tk.Frame(parent)
        row.pack(fill="x", padx=6, pady=4)

        name_label = tk.Label(row, text=label_text, font=label_font)
        name_label.grid(row=0, column=0, sticky="w")

        var = tk.StringVar(value=settingsDict.get(key, defaultsDict.get(key, "")))
        entry = tk.Entry(row, textvariable=var, width=42)
        entry.grid(row=0, column=1, sticky="e", padx=(6, 4))

        reset_btn = tk.Button(row, text="⟳", command=lambda: var.set(defaultsDict.get(key, "")))
        reset_btn.grid(row=0, column=2, sticky="e")

        if description:
            # Use a muted description line to explain format/values.
            desc = tk.Label(
                row,
                text=description,
                justify="left",
                anchor="w",
                fg="gray25",
                font=desc_font,
                wraplength=700,
            )
            desc.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        row.grid_columnconfigure(0, weight=1)

        entry_vars.append(var)
        entries.append(entry)
        labels.append(name_label)
        resets.append(reset_btn)
        entry_by_key[key] = var

    used_keys = set()
    groups = schemaDict.get("groups") if isinstance(schemaDict, dict) else None

    def _make_group(parent, name, description, collapsed=False):
        """Create a collapsible settings group and return its content frame."""
        container = tk.Frame(parent, bd=1, relief="groove")
        container.pack(fill="x", padx=6, pady=6)

        header = tk.Frame(container)
        header.pack(fill="x", padx=6, pady=(4, 2))

        state = {"open": not collapsed}
        toggle_btn = tk.Button(header, text="▾", width=2)
        toggle_btn.pack(side="left")
        title = tk.Label(header, text=name, font=group_font)
        title.pack(side="left", padx=(6, 0))

        desc_label = None
        if description:
            desc_label = tk.Label(
                container,
                text=description,
                justify="left",
                anchor="w",
                fg="gray25",
                font=desc_font,
                wraplength=720,
            )
            desc_label.pack(fill="x", padx=6, pady=(0, 6))

        content = tk.Frame(container)
        if not collapsed:
            content.pack(fill="x", padx=6, pady=(2, 6))
        else:
            toggle_btn.config(text="▸")

        def _toggle():
            """Expand or collapse the settings group."""
            if state["open"]:
                # Collapse the content region while keeping header/description visible.
                content.pack_forget()
                toggle_btn.config(text="▸")
                state["open"] = False
            else:
                # Expand the content region.
                content.pack(fill="x", padx=6, pady=(2, 6))
                toggle_btn.config(text="▾")
                state["open"] = True

        toggle_btn.config(command=_toggle)
        title.bind("<Button-1>", lambda _e: _toggle())

        return content

    if groups:
        for group in groups:
            group_name = group.get("name") or "Settings"
            group_desc = group.get("description") or ""
            group_frame = _make_group(inner, group_name, group_desc, group.get("collapsed", False))

            for item in group.get("items", []):
                # Skip malformed items without keys.
                key = item.get("key")
                if not key:
                    continue
                used_keys.add(key)
                label_text = item.get("label") or key
                description = item.get("description") or ""
                _add_setting_row(group_frame, key, label_text, description)

    # Add any keys not in schema under "Other"
    missing = [k for k in keys if k not in used_keys]
    if missing:
        other_frame = _make_group(inner, "Other", "Settings not yet categorized.", False)
        for key in missing:
            _add_setting_row(other_frame, key, key, "")

    # End Frame (Apply/Reset/Cancel).
    end_frame = tk.Frame(settings_window)
    end_frame.pack(padx=10, pady=5, anchor="center", fill="x")
    reset_label = tk.Button(end_frame, text="Reset All", command=resetAll)
    reset_label.pack(side="left", fill="x")
    end_label = tk.Button(end_frame, text="Apply", command=apply)
    end_label.pack(side="left", fill="x", expand=True, padx=(8, 4))
    end_button = tk.Button(end_frame, text="Cancel", command=cancel)
    end_button.pack(side="right", fill="x", expand=True)

    # Wait for the window to update its dimensions.
    settings_window.update_idletasks()

    # Get the window width and height.
    window_width = settings_window.winfo_width()
    window_height = settings_window.winfo_height()

    # Keep the window fully visible, reserving space for docks/taskbars.
    margin_x = 40
    margin_y = 120
    usable_width = max(300, screen_width - margin_x)
    usable_height = max(300, screen_height - margin_y)

    if window_width > usable_width or window_height > usable_height:
        window_width = min(window_width, usable_width)
        window_height = min(window_height, usable_height)
        settings_window.geometry(f"{window_width}x{window_height}")
        settings_window.update_idletasks()

    center_x = max(0, int((screen_width - window_width) / 2))
    center_y = max(0, int((usable_height - window_height) / 2))

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
