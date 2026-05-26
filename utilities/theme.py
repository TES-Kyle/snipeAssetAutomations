"""OS theme detection and adaptive colour palette for the GUI.

Detects whether macOS is running in Dark Mode at runtime and returns a
consistent colour dictionary used by every Tkinter window.  All hardcoded
widget colours in the project should be sourced from here so that a single
change propagates everywhere.

Usage::

    from utilities.theme import get_ui_colors

    _theme = get_ui_colors()
    label = tk.Label(win, bg=_theme["row_bg_1"], fg=_theme["fg"])
"""

import logging
import platform
import subprocess

logger = logging.getLogger(__name__)


def is_dark_mode() -> bool:
    """Return True when macOS is currently running in Dark Mode.

    Reads the global AppleInterfaceStyle default via the ``defaults`` CLI.
    Returns False on non-macOS platforms or if the query fails.

    Returns:
        True if the OS is in Dark Mode, False otherwise.
    """
    # Only macOS supports this detection mechanism.
    if platform.system() != "Darwin":
        logger.debug("is_dark_mode: non-macOS platform, returning False")
        return False
    try:
        # `defaults read -g AppleInterfaceStyle` prints "Dark" in dark mode
        # and exits non-zero (raising CalledProcessError) in light mode.
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        dark = result.stdout.strip().lower() == "dark"
        logger.debug("is_dark_mode: stdout=%r dark=%s", result.stdout.strip(), dark)
        return dark
    except Exception as exc:
        # Any failure (timeout, missing binary, etc.) falls back to light mode.
        logger.debug("is_dark_mode: detection failed (%s), defaulting to light", exc)
        return False


def get_ui_colors() -> dict:
    """Return a theme-appropriate colour palette for the current OS mode.

    Call this once per window open (not at import time) so that if the user
    switches themes between sessions the next window uses the correct colours.

    Returns:
        Dict with the following string keys:

        - ``bg``             — window/frame background
        - ``fg``             — primary text colour
        - ``tab_active_bg``  — active tab button background
        - ``tab_inactive_bg``— inactive tab button background
        - ``tab_fg``         — tab button text colour
        - ``row_bg_1``       — odd data-row background
        - ``row_bg_2``       — even data-row background
        - ``header_bg``      — table header background
        - ``header_fg``      — table header text colour
        - ``separator``      — thin horizontal rule colour
        - ``entry_bg``       — text-input background
        - ``entry_fg``       — text-input foreground
        - ``desc_fg``        — muted description/caption text
        - ``muted_fg``       — secondary muted text
        - ``error_bg``       — error/mismatch cell background
        - ``error_fg``       — error/mismatch text or border colour
    """
    dark = is_dark_mode()
    logger.debug("get_ui_colors: dark=%s", dark)

    if dark:
        # Dark-mode palette: medium-dark backgrounds, light text.
        return {
            "bg":              "#1e1e1e",
            "fg":              "#e0e0e0",
            "tab_active_bg":   "#505060",
            "tab_inactive_bg": "#383838",
            "tab_fg":          "#e8e8e8",
            "row_bg_1":        "#2b2b2b",
            "row_bg_2":        "#333340",
            "header_bg":       "#3c3d4a",
            "header_fg":       "#d0d0e0",
            "separator":       "#555566",
            "entry_bg":        "#3c3c3c",
            "entry_fg":        "#e0e0e0",
            "desc_fg":         "#a0a0a0",
            "muted_fg":        "#909090",
            "error_bg":        "#4a1a1a",
            "error_fg":        "#ff8080",
        }

    # Light-mode palette: matches the original hardcoded colours exactly so
    # existing light-mode users see no visual change.
    return {
        "bg":              "#f0f0f0",
        "fg":              "#000000",
        "tab_active_bg":   "#d9d9d9",
        "tab_inactive_bg": "#f0f0f0",
        "tab_fg":          "#000000",
        "row_bg_1":        "#ffffff",
        "row_bg_2":        "#f6f8fb",
        "header_bg":       "#e9edf3",
        "header_fg":       "#000000",
        "separator":       "#d6dce5",
        "entry_bg":        "#ffffff",
        "entry_fg":        "#000000",
        "desc_fg":         "#404040",
        "muted_fg":        "#555555",
        "error_bg":        "#fff1f1",
        "error_fg":        "#b22222",
    }
