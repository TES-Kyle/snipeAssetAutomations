"""Settings UI and persistence helpers.

This module renders the Settings window, loads/saves settings.json,
and applies changes to logging without requiring an app restart.
"""

import json
import logging
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

from utilities.logging_utils import configure_logging

logger = logging.getLogger(__name__)

UTILITIES_DIR = os.path.dirname(os.path.realpath(__file__))
SETTINGS_PATH = os.path.join(UTILITIES_DIR, "settings.json")
DEFAULTS_PATH = os.path.join(UTILITIES_DIR, "defaultSettings.json")

def settingsMenu():
    """Render the settings window with schema-based grouping.

    Loads settings.json + defaultSettings.json, then uses settingsSchema.json
    to build a categorized, scrollable UI with reset/apply controls.
    """
    logger.debug("settingsMenu: opening settings window")

    def _safe_read_json(path):
        """Read a JSON file path and return a dict fallback on failure.

        Args:
            path: Filesystem path to a JSON file.

        Returns:
            Dict parsed from JSON or {} on failure.
        """
        logger.debug("_safe_read_json: reading %s", path)
        try:
            result = json.loads(open(path).read())
            logger.debug("_safe_read_json: loaded %s keys from %s", len(result), path)
            return result
        except Exception:
            logger.debug("_safe_read_json: could not read %s; returning {}", path)
            return {}

    def resetAll():
        """Reset all editable fields to their default values."""
        logger.debug("resetAll: resetting all %s editable keys to defaults", len(keys))
        # Reset every known entry variable to default values.
        for key in keys:
            if key in entry_by_key:
                entry_by_key[key].set(defaultsDict.get(key, ""))
        logger.debug("resetAll: all fields reset to defaults")

    def reset(ind):
        """Reset a single entry by index to its default value.

        Args:
            ind: Index into the keys list identifying which setting to reset.
        """
        logger.debug("reset: resetting key=%s at index=%s", keys[ind] if ind < len(keys) else "?", ind)
        # Reset the entry by index (aligned with keys list).
        entry_vars[ind].set(defaultsDict.get(keys[ind], ""))
        logger.debug("reset: key=%s reset to default=%s", keys[ind], defaultsDict.get(keys[ind], ""))

    def checkUpdate():
        """Check for updates against the repo URL stored in meta.json.

        Uses the embedded meta.json file to discover repo URL and branch,
        then queries the GitHub API for the latest commit.
        """
        logger.debug("checkUpdate: initiating update check")
        import subprocess, sys, datetime
        try:
            app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # …/Resources/app
            meta_path = os.path.join(app_root, ".build", "meta.json")
            logger.debug("checkUpdate: meta_path=%s", meta_path)
            if not os.path.isfile(meta_path):
                logger.debug("checkUpdate: meta.json not found at %s", meta_path)
                messagebox.showerror("Update", "Missing meta.json — please reinstall.")
                return

            meta = json.loads(open(meta_path).read())
            repo_url = meta.get("repo_url", "").strip()
            branch = meta.get("branch", "main").strip()
            installed_sha = meta.get("installed_sha", "unknown").strip()
            logger.debug("checkUpdate: repo_url=%s, branch=%s, installed_sha=%s", repo_url, branch, installed_sha)

            if not repo_url or "github.com" not in repo_url:
                logger.debug("checkUpdate: invalid or missing repo_url=%s", repo_url)
                messagebox.showerror("Update", "Unsupported or missing repo URL in meta.json.")
                return

            # Normalize repo owner/name from URL
            # Examples: https://github.com/owner/repo or .../owner/repo.git
            tail = repo_url.split("github.com/")[-1]
            owner_repo = tail.split(".git")[0].strip("/")
            logger.debug("checkUpdate: owner_repo=%s", owner_repo)

            # Query GitHub API for latest commit on branch (unauthenticated)
            import requests
            api = f"https://api.github.com/repos/{owner_repo}/commits/{branch}"
            logger.info("checkUpdate: querying GitHub API for latest commit: %s", api)
            r = requests.get(api, timeout=15)
            if r.status_code != 200:
                logger.debug("checkUpdate: GitHub API returned status=%s", r.status_code)
                messagebox.showerror("Update", f"Failed to check updates.\nHTTP {r.status_code}")
                return
            latest_sha = r.json().get("sha", "").strip()
            logger.debug("checkUpdate: latest_sha=%s", latest_sha)

            if not latest_sha:
                logger.debug("checkUpdate: could not determine latest SHA")
                messagebox.showerror("Update", "Could not determine the latest commit SHA.")
                return

            if latest_sha == installed_sha:
                logger.info("checkUpdate: already up to date, sha=%s", installed_sha)
                messagebox.showinfo("Update", "You're up to date.")
                # Optionally update last_checked:
                meta["last_checked"] = datetime.datetime.now().isoformat()
                open(meta_path, "w").write(json.dumps(meta))
                return

            logger.info("checkUpdate: update available installed=%s latest=%s", installed_sha, latest_sha)
            # Offer to update
            resp = messagebox.askyesno(
                "Update available",
                "A new version is available.\n\nInstalled:\n"
                f"{installed_sha[:7]}\nLatest:\n{latest_sha[:7]}\n\nUpdate now?"
            )
            if not resp:
                logger.debug("checkUpdate: user declined update")
                return

            # Run the embedded updater (it shows its own progress dialogs)
            updater = os.path.join(app_root, "shellScripts", "update_in_place.command")
            logger.debug("checkUpdate: updater path=%s", updater)
            if not os.path.isfile(updater):
                logger.debug("checkUpdate: updater script not found at %s", updater)
                messagebox.showerror("Update", "Updater script not found.\nPlease reinstall.")
                return

            # Launch updater detached so GUI stays responsive; updater will mutate files then prompt to restart.
            logger.info("checkUpdate: launching updater script %s", updater)
            subprocess.Popen(
                ["bash", "-lc", f"exec {json.dumps(updater)}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
            )

            messagebox.showinfo("Update", "Update started.\n\nOnce complete, please quit and relaunch the app.")
        except Exception as e:
            logger.exception("checkUpdate: unexpected error")
            messagebox.showerror("Update error", str(e))

    def make_installer_usb():
        """Launch the USB installer builder script."""
        logger.debug("make_installer_usb: starting USB installer builder")
        try:
            app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            usb_maker = os.path.join(app_root, "shellScripts", "make_installer_usb.command")
            logger.debug("make_installer_usb: usb_maker path=%s", usb_maker)
            if not os.path.isfile(usb_maker):
                logger.debug("make_installer_usb: script not found at %s", usb_maker)
                messagebox.showerror("USB Installer", "make_installer_usb.command not found.")
                return
            import subprocess
            logger.info("make_installer_usb: launching %s", usb_maker)
            subprocess.Popen(
                ["bash", "-lc", f"exec {json.dumps(usb_maker)}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.debug("make_installer_usb: process launched successfully")
        except Exception as e:
            logger.exception("make_installer_usb: unexpected error")
            messagebox.showerror("USB Installer", str(e))

    def sync_key_usb():
        """Sync Key.py between the local install and a USB drive.

        Opens a file picker (required on macOS to get OS-level permission to
        read removable volumes). Auto-detects USB drives to pre-fill the
        dialog's starting directory. Compares which variables are filled in on
        each side and copies the more complete file in the appropriate
        direction. If both sides have exclusive values the other lacks, no copy
        is made and the user is informed.
        """
        logger.debug("sync_key_usb: starting Key.py sync")
        import importlib.util
        import glob
        import shutil
        from tkinter import filedialog

        local_key = os.path.join(os.path.dirname(os.path.realpath(__file__)), "Key.py")
        logger.debug("sync_key_usb: local_key=%s", local_key)

        # Try to detect a USB drive with Key.py so we can pre-fill the dialog.
        local_volume = os.path.realpath(local_key).split(os.sep)[1]
        candidates = [
            p for p in glob.glob("/Volumes/*/Key.py")
            if os.path.realpath(p).split(os.sep)[2] != local_volume
        ]
        logger.debug("sync_key_usb: found %s USB Key.py candidate(s): %s", len(candidates), candidates)
        if candidates:
            initial_dir = os.path.dirname(candidates[0])
        else:
            initial_dir = "/Volumes"
        logger.debug("sync_key_usb: initial_dir for file dialog=%s", initial_dir)

        # Native file picker — macOS grants read/write access to whatever the
        # user selects, bypassing the Removable Volumes TCC restriction.
        usb_key = filedialog.askopenfilename(
            title="Select Key.py on USB drive",
            initialdir=initial_dir,
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
        )
        if not usb_key:
            logger.debug("sync_key_usb: user cancelled file picker")
            return  # user cancelled
        logger.debug("sync_key_usb: user selected usb_key=%s", usb_key)

        def load_filled_vars(path):
            """Return a dict of non-empty variable names from a Key.py file.

            Args:
                path: Absolute path to a Key.py file to load.

            Returns:
                Dict of {variable_name: value} for all non-empty, non-private vars.
            """
            logger.debug("load_filled_vars: loading %s", path)
            spec = importlib.util.spec_from_file_location("_key_sync_tmp", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = {k: v for k, v in vars(mod).items() if not k.startswith("_") and v}
            logger.debug("load_filled_vars: found %s filled vars in %s", len(result), path)
            return result

        try:
            current_vars = load_filled_vars(local_key)
            logger.debug("sync_key_usb: local Key.py has %s filled vars", len(current_vars))
        except Exception as exc:
            logger.exception("sync_key_usb: could not read local Key.py")
            messagebox.showerror("Sync Key", f"Could not read local Key.py:\n{exc}")
            return

        try:
            usb_vars = load_filled_vars(usb_key)
            logger.debug("sync_key_usb: USB Key.py has %s filled vars", len(usb_vars))
        except Exception as exc:
            logger.exception("sync_key_usb: could not read USB Key.py")
            messagebox.showerror("Sync Key", f"Could not read USB Key.py:\n{exc}")
            return

        only_in_current = sorted(set(current_vars) - set(usb_vars))
        only_in_usb = sorted(set(usb_vars) - set(current_vars))
        logger.debug("sync_key_usb: only_in_current=%s, only_in_usb=%s", only_in_current, only_in_usb)

        if only_in_current and only_in_usb:
            logger.info("sync_key_usb: conflict — both files have exclusive vars; no copy made")
            messagebox.showwarning(
                "Sync Key — Conflict",
                "Both files have credentials the other doesn't. No changes were made.\n\n"
                f"Only in local Key.py:  {', '.join(only_in_current)}\n\n"
                f"Only on USB:           {', '.join(only_in_usb)}\n\n"
                "Resolve the conflict manually, then try again.",
            )
        elif only_in_current:
            logger.info("sync_key_usb: local has more vars; copying local -> USB")
            try:
                shutil.copy2(local_key, usb_key)
                logger.info("sync_key_usb: copied local Key.py to USB successfully")
                messagebox.showinfo(
                    "Sync Key — Updated USB",
                    f"USB Key.py replaced with local Key.py.\n\n"
                    f"Variables the USB was missing:  {', '.join(only_in_current)}",
                )
            except Exception as exc:
                logger.exception("sync_key_usb: could not write to USB")
                messagebox.showerror("Sync Key", f"Could not write to USB:\n{exc}")
        elif only_in_usb:
            logger.info("sync_key_usb: USB has more vars; copying USB -> local")
            try:
                shutil.copy2(usb_key, local_key)
                logger.info("sync_key_usb: copied USB Key.py to local successfully")
                messagebox.showinfo(
                    "Sync Key — Updated Local",
                    f"Local Key.py replaced with USB Key.py.\n\n"
                    f"Variables the local file was missing:  {', '.join(only_in_usb)}",
                )
            except Exception as exc:
                logger.exception("sync_key_usb: could not write local Key.py")
                messagebox.showerror("Sync Key", f"Could not write local Key.py:\n{exc}")
        else:
            logger.info("sync_key_usb: both Key.py files already have the same filled vars; no copy needed")
            messagebox.showinfo(
                "Sync Key",
                "Local Key.py and USB Key.py already have the same filled-in credentials. No changes made.",
            )

    def apply():
        """Persist settings, refresh logging config, and close the window."""
        logger.debug("apply: collecting %s settings keys", len(keys))
        output = dict()
        # Gather all known keys, preserving existing values for non-editable fields.
        for key in keys:
            if key in entry_by_key:
                output[key] = entry_by_key[key].get()
            else:
                output[key] = settingsDict.get(key, defaultsDict.get(key, ""))

        logger.info("apply: saving %s settings to settings.json", len(output))
        # Persist settings and refresh logging without restart.
        open(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json", "w").write(json.dumps(output))
        logger.debug("apply: settings written; reconfiguring logging")
        configure_logging()

        logger.debug("apply: closing settings window")
        settings_window.destroy()

    def cancel():
        """Close the settings window without applying changes."""
        logger.debug("cancel: discarding changes and closing settings window")
        settings_window.destroy()

    logger.debug("settingsMenu: loading settings, defaults, and schema")
    # Load persisted settings, defaults, and schema for UI layout.
    settingsDict = _safe_read_json(str(os.path.dirname(os.path.realpath(__file__))) + "/settings.json")
    defaultsDict = _safe_read_json(str(os.path.dirname(os.path.realpath(__file__))) + "/defaultSettings.json")
    schemaDict = _safe_read_json(str(os.path.dirname(os.path.realpath(__file__))) + "/settingsSchema.json")

    # Merge keys from settings and defaults to ensure all fields render.
    keys = list(settingsDict.keys())
    for key in defaultsDict.keys():
        if key not in keys:
            keys.append(key)
    logger.debug("settingsMenu: merged %s total settings keys", len(keys))

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
    update_button = tk.Button(update_frame, text="⬆", command=checkUpdate)
    update_button.pack(side="left")
    usb_button = tk.Button(update_frame, text="Make Installer USB", command=make_installer_usb)
    usb_button.pack(side="left", padx=(10, 0))
    sync_key_button = tk.Button(update_frame, text="Update Key", command=sync_key_usb)
    sync_key_button.pack(side="left", padx=(10, 0))

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
        logger.debug("_on_inner_configure: updating scrollregion")
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event):
        """Stretch the inner frame to match the canvas width."""
        logger.debug("_on_canvas_configure: canvas width=%s", event.width)
        canvas.itemconfig(window_id, width=event.width)

    inner.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event):
        """Scroll the canvas with the mouse wheel."""
        logger.debug("_on_mousewheel: num=%s, delta=%s", event.num, event.delta)
        # Normalize scroll direction for platform differences.
        if event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            canvas.yview_scroll(1, "units")

    def _bind_mousewheel(_event=None):
        """Bind mouse wheel events to the settings window."""
        logger.debug("_bind_mousewheel: binding mouse wheel events")
        settings_window.bind_all("<MouseWheel>", _on_mousewheel)
        settings_window.bind_all("<Button-4>", _on_mousewheel)
        settings_window.bind_all("<Button-5>", _on_mousewheel)

    def _unbind_mousewheel(_event=None):
        """Unbind mouse wheel events when focus leaves the window."""
        logger.debug("_unbind_mousewheel: unbinding mouse wheel events")
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
        """Create a labeled entry row with reset button and description.

        Args:
            parent: Tk parent frame.
            key: Settings key name.
            label_text: Display label text for the row.
            description: Optional description shown below the entry.
        """
        logger.debug("_add_setting_row: key=%s, label_text=%s", key, label_text)
        row = tk.Frame(parent)
        row.pack(fill="x", padx=6, pady=4)

        name_label = tk.Label(row, text=label_text, font=label_font)
        name_label.grid(row=0, column=0, sticky="w")

        current_val = settingsDict.get(key, defaultsDict.get(key, ""))
        logger.debug("_add_setting_row: key=%s current_value=%s", key, current_val)
        var = tk.StringVar(value=current_val)
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
            logger.debug("_add_setting_row: description added for key=%s", key)

        row.grid_columnconfigure(0, weight=1)

        entry_vars.append(var)
        entries.append(entry)
        labels.append(name_label)
        resets.append(reset_btn)
        entry_by_key[key] = var
        logger.debug("_add_setting_row: row created for key=%s", key)

    used_keys = set()
    groups = schemaDict.get("groups") if isinstance(schemaDict, dict) else None

    def _make_group(parent, name, description, collapsed=False):
        """Create a collapsible settings group and return its content frame.

        Args:
            parent: Tk parent widget.
            name: Group display name.
            description: Optional group description text.
            collapsed: Whether to start in collapsed state.

        Returns:
            Tk Frame for adding child setting rows.
        """
        logger.debug("_make_group: name=%s, collapsed=%s", name, collapsed)
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
            logger.debug("_make_group: description added for group=%s", name)

        content = tk.Frame(container)
        if not collapsed:
            content.pack(fill="x", padx=6, pady=(2, 6))
            logger.debug("_make_group: group=%s starts expanded", name)
        else:
            toggle_btn.config(text="▸")
            logger.debug("_make_group: group=%s starts collapsed", name)

        def _toggle():
            """Expand or collapse the settings group."""
            logger.debug("_toggle: group=%s current open=%s", name, state["open"])
            if state["open"]:
                # Collapse the content region while keeping header/description visible.
                content.pack_forget()
                toggle_btn.config(text="▸")
                state["open"] = False
                logger.debug("_toggle: group=%s collapsed", name)
            else:
                # Expand the content region.
                content.pack(fill="x", padx=6, pady=(2, 6))
                toggle_btn.config(text="▾")
                state["open"] = True
                logger.debug("_toggle: group=%s expanded", name)

        toggle_btn.config(command=_toggle)
        title.bind("<Button-1>", lambda _e: _toggle())

        logger.debug("_make_group: group=%s frame created", name)
        return content

    logger.debug("settingsMenu: building UI groups from schema, groups count=%s", len(groups) if groups else 0)
    if groups:
        for group in groups:
            group_name = group.get("name") or "Settings"
            group_desc = group.get("description") or ""
            logger.debug("settingsMenu: creating group=%s with %s items", group_name, len(group.get("items", [])))
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
    logger.debug("settingsMenu: %s keys not in schema, adding to Other group", len(missing))
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

    logger.debug("settingsMenu: waiting for window dimensions to settle")
    # Wait for the window to update its dimensions.
    settings_window.update_idletasks()

    # Get the window width and height.
    window_width = settings_window.winfo_width()
    window_height = settings_window.winfo_height()
    logger.debug("settingsMenu: initial window size width=%s height=%s", window_width, window_height)

    # Keep the window fully visible, reserving space for docks/taskbars.
    margin_x = 40
    margin_y = 120
    usable_width = max(300, screen_width - margin_x)
    usable_height = max(300, screen_height - margin_y)
    logger.debug("settingsMenu: usable_width=%s usable_height=%s", usable_width, usable_height)

    if window_width > usable_width or window_height > usable_height:
        window_width = min(window_width, usable_width)
        window_height = min(window_height, usable_height)
        logger.debug("settingsMenu: clamping window size to width=%s height=%s", window_width, window_height)
        settings_window.geometry(f"{window_width}x{window_height}")
        settings_window.update_idletasks()

    center_x = max(0, int((screen_width - window_width) / 2))
    center_y = max(0, int((usable_height - window_height) / 2))
    logger.debug("settingsMenu: centering window at x=%s y=%s", center_x, center_y)

    settings_window.geometry(f"+{center_x}+{center_y}")
    logger.info("settingsMenu: settings window displayed")


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
logger.debug("settingsMenu module initialized: %s settings keys", len(settings))
logger.info("Settings initialized on module load")
