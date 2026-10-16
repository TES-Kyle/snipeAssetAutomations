"""Named, per-machine save states for the Consisterizer window.

A save state is a snapshot of the Consisterizer's inputs -- every Updates
entry/autocomplete, every Reset checkbox, the Batch / Maintain / Bypass
checkboxes, and which on-submit scripts are ticked -- stored under a
user-chosen name so it can be re-applied later without reopening the window.

Pure logic only (no Tk), so it can be unit-tested. Saves live in a
gitignored JSON file next to this module, so each Mac keeps its own and an
in-place update (which only copies git-tracked files) never touches them.

State shape:
    {
      "batch_mode": bool,
      "maintain_defaults": bool,
      "bypass_warnings": bool,
      "scripts": ["<script label>", ...],      # labels, not indexes
      "reset": ["<field key>", ...],           # checked Reset boxes
      "set": {"<field key>": "<Updates text>"}, # only non-empty Updates
      "saved_at": "YYYY-MM-DDTHH:MM:SS"         # added by save_state(); the
                                                # last time this name was saved
    }
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)

SAVES_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "userSaveStates.json")


def _read_all(path: str) -> dict:
    """Return {name: state} from disk, or {} if missing/unreadable/malformed."""
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("saveStates: could not read %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("saveStates: %s is not a JSON object; ignoring", path)
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}


def _write_all(path: str, saves: dict) -> None:
    """Atomically write {name: state} to disk (temp file + rename)."""
    logger.debug("_write_all: writing %s save(s) to %s", len(saves), path)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".saveStates-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(saves, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def normalize_name(name: str) -> str:
    """Trim a user-typed save name (case is preserved)."""
    return (name or "").strip()


SORT_ALPHA = "alpha"
SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"


def list_entries(sort: str = SORT_ALPHA, path: str = SAVES_PATH) -> list[tuple[str, str]]:
    """Return [(name, saved_at)] in the requested order.

    Saves made before timestamps existed have saved_at == "" and count as the
    oldest. Ties (and the alphabetical order itself) are case-insensitive by name.

    Args:
        sort: SORT_ALPHA, SORT_NEWEST or SORT_OLDEST.
    """
    logger.debug("list_entries: sort=%s", sort)
    entries = [(n, str(st.get("saved_at") or "")) for n, st in _read_all(path).items()]
    entries.sort(key=lambda e: e[0].lower())
    if sort == SORT_NEWEST:
        entries.sort(key=lambda e: e[1], reverse=True)  # stable: ties stay alphabetical
    elif sort == SORT_OLDEST:
        entries.sort(key=lambda e: e[1])
    return entries


def list_names(path: str = SAVES_PATH) -> list[str]:
    """Return saved names, alphabetical (case-insensitive)."""
    return [n for n, _ in list_entries(SORT_ALPHA, path)]


def name_exists(name: str, path: str = SAVES_PATH) -> bool:
    """True if a save with this name exists (case-insensitive, after trimming)."""
    wanted = normalize_name(name).lower()
    return any(n.lower() == wanted for n in _read_all(path))


def get_state(name: str, path: str = SAVES_PATH) -> dict | None:
    """Return the saved state for `name`, or None."""
    wanted = normalize_name(name).lower()
    for n, state in _read_all(path).items():
        if n.lower() == wanted:
            return state
    return None


def save_state(name: str, state: dict, path: str = SAVES_PATH) -> str:
    """Create or overwrite a save; returns the stored name.

    Overwriting is case-insensitive and keeps the new spelling, so "loaner"
    replaces "Loaner" instead of living beside it.

    Raises:
        ValueError: if the name is blank.
    """
    clean = normalize_name(name)
    if not clean:
        raise ValueError("Save name cannot be blank.")
    saves = _read_all(path)
    for existing in [n for n in saves if n.lower() == clean.lower()]:
        del saves[existing]
    saves[clean] = {**state, "saved_at": datetime.now().isoformat(timespec="seconds")}
    _write_all(path, saves)
    logger.info("saveStates: saved %r", clean)
    return clean


def delete_state(name: str, path: str = SAVES_PATH) -> bool:
    """Delete a save; returns True if one was removed."""
    wanted = normalize_name(name).lower()
    saves = _read_all(path)
    hits = [n for n in saves if n.lower() == wanted]
    if not hits:
        return False
    for n in hits:
        del saves[n]
    _write_all(path, saves)
    logger.info("saveStates: deleted %r", name)
    return True
