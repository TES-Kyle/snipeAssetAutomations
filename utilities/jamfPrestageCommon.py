#!/usr/bin/env python3
"""
Shared helpers for Jamf PreStage workflows.

This module provides reusable Jamf + Snipe-IT utilities for:
  - Resolving serials from Snipe-IT assets
  - Listing computer PreStages
  - Removing/adding a serial to PreStage scopes
  - Deleting Jamf inventory records with verification
  - Safe, optional GUI prompts for PreStage selection
"""

import json
import logging
import time
from typing import Optional, Tuple, Dict, List, Any, Set

from utilities import Key
from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings
from utilities.otherApiBits import getAssetInfo

from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider

logger = logging.getLogger(__name__)


# ==============================
# Settings helpers
# ==============================
def _to_bool(value, default: bool) -> bool:
    """Normalize truthy string/int values into a boolean."""
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _to_float(value, default: float) -> float:
    """Coerce a setting into a float, returning default on failure."""
    try:
        return float(value)
    except Exception:
        return default


def get_prestage_settings() -> Dict[str, Any]:
    """Load Jamf PreStage settings from the settings store."""
    settings = get_settings()
    return {
        "verify_ssl": _to_bool(settings.get("jamfPrestageVerifySSL", "1"), True),
        "rate_limit_delay": _to_float(settings.get("jamfPrestageRateLimitDelay", "0.35"), 0.35),
        "strict_removal_guard": _to_bool(settings.get("jamfPrestageStrictRemovalGuard", "1"), True),
        "dry_run": _to_bool(settings.get("jamfPrestageDryRun", "0"), False),
        "debug_verbose": _to_bool(settings.get("jamfPrestageDebugVerbose", "0"), False),
        "delete_after_remove": _to_bool(settings.get("jamfPrestageDeleteAfterRemove", "1"), True),
    }


def create_jamf_client(settings: Dict[str, Any]) -> JamfProClient:
    """Create a Jamf Pro client using settings-driven SSL verification."""
    return JamfProClient(
        server=Key.jamfURL,
        credentials=ApiClientCredentialsProvider(Key.jamfClientID, Key.jamfClientSecret),
        session_config=SessionConfig(ssl_verify=settings["verify_ssl"], max_retries=5),
    )


# ==============================
# Dialog helpers (messagebox with safe fallback)
# ==============================
try:
    import tkinter as _tk
    from tkinter import messagebox as _mb
    from tkinter import ttk as _ttk
    _TK_OK = True
except Exception:
    _tk = None
    _mb = None
    _ttk = None
    _TK_OK = False


def _ensure_tk_root():
    """Return the current Tk root (or a hidden root if none exists)."""
    if not _TK_OK:
        return None
    root = getattr(_ensure_tk_root, "_root", None)
    try:
        if root is None or not root.winfo_exists():
            existing = getattr(_tk, "_default_root", None)
            if existing is not None and existing.winfo_exists():
                root = existing
            else:
                root = _tk.Tk()
                root.withdraw()
            _ensure_tk_root._root = root
        return root
    except Exception:
        return None


def _ask_retry_cancel(title: str, message: str) -> bool:
    """Return True to retry, False to cancel. Falls back to False when headless."""
    try:
        root = _ensure_tk_root()
        if root:
            return bool(_mb.askretrycancel(title, message, parent=root))
    except Exception:
        pass
    configure_logging()
    logger.warning("Prompt (no GUI): %s: %s -> cancel", title, message)
    return False


def _warn(title: str, message: str) -> None:
    """Show a warning dialog (or log when headless)."""
    try:
        root = _ensure_tk_root()
        if root:
            _mb.showwarning(title, message, parent=root)
            return
    except Exception:
        pass
    configure_logging()
    logger.warning("%s: %s", title, message)


def _confirm_action(title: str, message: str) -> bool:
    """Show a yes/no confirmation dialog (safe-cancel when headless)."""
    try:
        root = _ensure_tk_root()
        if root:
            return bool(_mb.askyesno(title, message, parent=root))
    except Exception:
        pass
    configure_logging()
    logger.warning("Confirm (no GUI): %s: %s -> cancel", title, message)
    return False


# ==============================
# Small utilities
# ==============================
def _pp(obj: Any, limit: int = 1600) -> str:
    """Pretty-print JSON-ish objects for logs, truncated for readability."""
    try:
        s = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "...(truncated)..."


# ==============================
# Snipe + Jamf lookups
# ==============================
def _get_serial_from_snipe(asset_tag: str) -> Optional[str]:
    """Load Snipe-IT asset and return its serial (or None)."""
    try:
        _vars, asset = getAssetInfo(asset_tag)
    except Exception as e:
        logger.error("SNIPE: Failed to load asset '%s': %s", asset_tag, e)
        return None
    serial = (asset or {}).get("serial") or ""
    serial = serial.strip()
    if not serial:
        logger.error("SNIPE: Asset '%s' has no serial.", asset_tag)
        return None
    return serial


def _find_jamf_computer_by_serial(
    jamf_client: JamfProClient,
    serial: str,
    settings: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Search Jamf inventory for the given serial and return {'id','name'} or None."""
    logger.info("Searching Jamf inventory for serial...")
    try:
        devices = jamf_client.pro_api.get_computer_inventory_v1(
            sections=["GENERAL", "HARDWARE"],
            page_size=2000,
        )
        if settings.get("debug_verbose"):
            logger.debug("Inventory count: %s", len(devices))
    except Exception as e:
        logger.error("JAMF: Failed to query inventory: %s", e)
        return None

    for d in devices:
        dev_serial = getattr(getattr(d, "hardware", None), "serialNumber", None)
        if dev_serial and dev_serial.strip().upper() == serial.strip().upper():
            dev_id = getattr(d, "id", None) or getattr(getattr(d, "general", None), "id", None)
            dev_name = getattr(getattr(d, "general", None), "name", None) or f"ID {dev_id}"
            if dev_id is None:
                continue
            logger.info("Match: %s (ID %s)", dev_name, dev_id)
            return {"id": int(dev_id), "name": dev_name}
    logger.warning("No Jamf computer found with serial %s.", serial)
    return None


# ==============================
# PreStage scope helpers
# ==============================
def _get_prestage_scope_v2(
    jamf_client: JamfProClient,
    prestage_id: int,
    settings: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Return the PreStage scope document for the given ID, or None for 404.
    Supports both shapes Jamf returns:
      A) {"prestageId":..,"assignments":{"serialNumbers":[...],...}, "versionLock":N}
      B) {"prestageId":..,"assignments":[{"serialNumber":...}, ...], "versionLock":N}
    """
    try:
        r = jamf_client.pro_api_request(
            method="GET",
            resource_path=f"v2/computer-prestages/{prestage_id}/scope",
            override_headers={"Accept": "application/json"},
        )
        if settings.get("debug_verbose"):
            logger.debug(
                "GET v2/computer-prestages/%s/scope -> %s",
                prestage_id,
                r.status_code,
            )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        scope = r.json() or {}
    except Exception as e:
        logger.error("JAMF: Get scope for PreStage %s failed: %s", prestage_id, e)
        return None

    if settings.get("debug_verbose"):
        keys = list(scope.keys())
        logger.debug("Scope %s keys: %s", prestage_id, keys)
        a = scope.get("assignments", None)
        if isinstance(a, dict):
            logger.debug("assignments is dict; keys: %s", list(a.keys()))
        elif isinstance(a, list):
            logger.debug("assignments is list; len=%s", len(a))
        else:
            logger.debug("assignments missing or unrecognized")
    return scope


def _build_scope_put_payload(scope: Dict, serial: str) -> Tuple[Optional[Dict], str]:
    """
    Build the doc-style PUT body Jamf expects:
      {"serialNumbers":[...], "versionLock": <lock>}
    Removes only this serial. Returns (payload_or_None, debug_message).
    """
    if not isinstance(scope, dict):
        return None, "[DEBUG] Bad scope object."

    version_lock = scope.get("versionLock")
    assignments = scope.get("assignments")

    before = 0
    serials_now: List[str] = []

    if isinstance(assignments, dict):
        cur = assignments.get("serialNumbers") or []
        if not isinstance(cur, list):
            cur = []
        before = len(cur)
        serials_now = [s for s in cur if s != serial]
    elif isinstance(assignments, list):
        cur = []
        for row in assignments:
            s = (row or {}).get("serialNumber")
            if isinstance(s, str) and s:
                cur.append(s)
        before = len(cur)
        serials_now = [s for s in cur if s != serial]
    else:
        return None, "[DEBUG] No 'assignments' in scope."

    after = len(serials_now)
    if after == before:
        return None, "[DEBUG] Serial not present; nothing to PUT."

    payload = {"serialNumbers": serials_now, "versionLock": version_lock}
    return payload, f"[DEBUG] Doc-style prune: serialNumbers {before}->{after}"


def _build_scope_add_payload(scope: Dict, serial: str) -> Tuple[Optional[Dict], str]:
    """
    Build the doc-style PUT body Jamf expects:
      {"serialNumbers":[...], "versionLock": <lock>}
    Adds only this serial. Returns (payload_or_None, debug_message).
    """
    if not isinstance(scope, dict):
        return None, "[DEBUG] Bad scope object."

    version_lock = scope.get("versionLock")
    assignments = scope.get("assignments")

    serials_now: List[str] = []

    if isinstance(assignments, dict):
        cur = assignments.get("serialNumbers") or []
        if not isinstance(cur, list):
            cur = []
        serials_now = [s for s in cur if isinstance(s, str)]
    elif isinstance(assignments, list):
        for row in assignments:
            s = (row or {}).get("serialNumber")
            if isinstance(s, str) and s:
                serials_now.append(s)
    else:
        return None, "[DEBUG] No 'assignments' in scope."

    if serial in serials_now:
        return None, "[DEBUG] Serial already present; nothing to PUT."

    before = len(serials_now)
    serials_now.append(serial)
    after = len(serials_now)

    payload = {"serialNumbers": serials_now, "versionLock": version_lock}
    return payload, f"[DEBUG] Doc-style add: serialNumbers {before}->{after}"


def _put_prestage_scope_v2(
    jamf_client: JamfProClient,
    prestage_id: int,
    scope_obj: Dict,
    settings: Dict[str, Any],
) -> bool:
    """
    PUT /api/v2/computer-prestages/{id}/scope using doc-style payload:
      {"serialNumbers":[...], "versionLock": <lock>}
    On 409 (lock mismatch), refresh versionLock once and retry.
    """
    if settings.get("dry_run"):
        logger.info(
            "DRY RUN: Would PUT scope for PreStage %s. Payload:\n%s",
            prestage_id,
            _pp(scope_obj),
        )
        return True

    def _do_put(body: Dict):
        return jamf_client.pro_api_request(
            method="PUT",
            resource_path=f"v2/computer-prestages/{prestage_id}/scope",
            data=body,
            override_headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    try:
        r = _do_put(scope_obj)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 409:
            logger.warning(
                "PreStage %s versionLock conflict. Refreshing and retrying...",
                prestage_id,
            )
            scope_now = _get_prestage_scope_v2(jamf_client, prestage_id, settings) or {}
            new_lock = scope_now.get("versionLock")
            alt = {
                "serialNumbers": scope_obj.get("serialNumbers", []),
                "versionLock": new_lock,
            }
            r2 = _do_put(alt)
            if r2.status_code in (200, 204):
                return True
            try:
                detail2 = r2.json()
            except Exception:
                detail2 = r2.text
            logger.error(
                "JAMF: PUT scope %s failed after lock refresh (%s): %s",
                prestage_id,
                r2.status_code,
                detail2,
            )
            return False
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        logger.error(
            "JAMF: PUT scope %s failed (%s): %s",
            prestage_id,
            r.status_code,
            detail,
        )
        return False
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 409:
            logger.warning(
                "PreStage %s versionLock conflict (exception). Refreshing and retrying...",
                prestage_id,
            )
            scope_now = _get_prestage_scope_v2(jamf_client, prestage_id, settings) or {}
            new_lock = scope_now.get("versionLock")
            alt = {
                "serialNumbers": scope_obj.get("serialNumbers", []),
                "versionLock": new_lock,
            }
            try:
                r2 = _do_put(alt)
                if r2.status_code in (200, 204):
                    return True
                try:
                    detail2 = r2.json()
                except Exception:
                    detail2 = r2.text
                logger.error(
                    "JAMF: PUT scope %s failed after lock refresh (%s): %s",
                    prestage_id,
                    r2.status_code,
                    detail2,
                )
                return False
            except Exception as e2:
                logger.error("JAMF: PUT scope %s retry failed: %s", prestage_id, e2)
                return False

        logger.error("JAMF: PUT scope %s failed: %s", prestage_id, e)
        return False


def _remove_from_all_prestages(
    jamf_client: JamfProClient,
    serial: str,
    settings: Dict[str, Any],
    skip_ids: Optional[Set[int]] = None,
) -> Tuple[int, int, int]:
    """
    Determine candidate PreStages for this serial, remove the serial from each,
    and verify removal. Returns (seen, modified, candidate_count).
    """
    skip_ids = skip_ids or set()
    agg = {}
    while True:
        try:
            r = jamf_client.pro_api_request(
                method="GET",
                resource_path="v2/computer-prestages/scope",
                override_headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            agg = r.json() or {}
            if settings.get("debug_verbose"):
                logger.debug("GET v2/computer-prestages/scope -> %s", r.status_code)
            break
        except Exception as e:
            if not _ask_retry_cancel("Jamf PreStage scopes",
                                     f"Failed to fetch aggregate scopes.\n\n{e}\n\nRetry?"):
                logger.error("JAMF: Could not fetch aggregate PreStage scopes: %s", e)
                agg = {}
                break

    candidate_ids: List[int] = []
    if isinstance(agg, dict) and "serialsByPrestageId" in agg:
        mapping = agg["serialsByPrestageId"]
        v = mapping.get(serial) or mapping.get(serial.upper()) or mapping.get(serial.lower())
        if isinstance(v, list):
            for x in v:
                try:
                    candidate_ids.append(int(x))
                except Exception:
                    pass
        elif v is not None:
            try:
                candidate_ids.append(int(v))
            except Exception:
                pass

    if skip_ids:
        candidate_ids = [pid for pid in candidate_ids if pid not in skip_ids]
        if settings.get("debug_verbose"):
            logger.debug("Skipping PreStages: %s", ", ".join(map(str, skip_ids)))

    if not candidate_ids:
        logger.info("No candidate PreStages for this serial.")
        return (0, 0, 0)

    logger.info("Candidate PreStages: %s", ", ".join(map(str, candidate_ids)))

    seen = 0
    changed = 0
    touched: List[int] = []

    for pid in candidate_ids:
        scope = None
        while True:
            scope = _get_prestage_scope_v2(jamf_client, pid, settings)
            if scope is not None:
                break
            if not _ask_retry_cancel("Jamf PreStage scope",
                                     f"Failed to load scope for PreStage {pid}.\n\n"
                                     f"Retry to refetch, or Cancel to skip this PreStage?"):
                logger.warning("Skipping PreStage %s (scope not available).", pid)
                break
        if scope is None:
            continue

        seen += 1

        payload, dbg = _build_scope_put_payload(scope, serial)
        if settings.get("debug_verbose"):
            logger.debug(dbg)
        if not payload:
            if settings.get("rate_limit_delay"):
                time.sleep(settings["rate_limit_delay"])
            continue

        if settings.get("dry_run"):
            logger.info(
                "DRY RUN: Would update PreStage %s with: %s",
                pid,
                _pp(payload),
            )
            changed += 1
            touched.append(pid)
        else:
            while True:
                ok = _put_prestage_scope_v2(jamf_client, pid, payload, settings)
                if ok:
                    verify_ok = True
                    try:
                        scope_after = _get_prestage_scope_v2(jamf_client, pid, settings)
                        if isinstance(scope_after, dict):
                            a2 = scope_after.get("assignments")
                            if isinstance(a2, dict) and (serial in (a2.get("serialNumbers") or [])):
                                verify_ok = False
                            elif isinstance(a2, list) and any((row or {}).get("serialNumber") == serial for row in a2):
                                verify_ok = False
                    except Exception as ve:
                        if _ask_retry_cancel("Verify removal",
                                             f"Could not verify PreStage {pid} removal.\n\n{ve}\n\nRetry verify?"):
                            continue
                        verify_ok = False

                    if verify_ok:
                        changed += 1
                        touched.append(pid)
                        logger.info("Removed from PreStage %s.", pid)
                        break
                    else:
                        if _ask_retry_cancel("Removal not verified",
                                             f"Serial still appears in PreStage {pid} after update.\n\nRetry update?"):
                            continue
                        logger.warning(
                            "Serial still present after PUT in PreStage %s; not counting as modified.",
                            pid,
                        )
                        break
                else:
                    if _ask_retry_cancel("Update PreStage scope failed",
                                         f"Could not update PreStage {pid} scope.\n\nRetry?"):
                        continue
                    logger.warning("Skipped updating PreStage %s.", pid)
                    break

        if settings.get("rate_limit_delay"):
            time.sleep(settings["rate_limit_delay"])

    if touched:
        logger.info("Updated PreStages: %s", ", ".join(map(str, touched)))
    else:
        logger.info("No scope updates were necessary.")

    if candidate_ids and changed == 0:
        _warn("PreStage removal",
              "Jamf reported candidate PreStages for this device, but I could not "
              "remove it from any of them.\n\n"
              "You may wish to retry updates, or inspect the PreStages manually.")

    return (seen, changed, len(candidate_ids))


def _get_prestage_list(
    jamf_client: JamfProClient,
    settings: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Fetch available computer PreStages (id + name) for selection."""
    def _extract_rows(data_obj):
        if isinstance(data_obj, dict):
            for key in ("results", "prestages", "prestageList", "computerPrestageList", "items", "value"):
                if isinstance(data_obj.get(key), list):
                    return data_obj.get(key) or []
        if isinstance(data_obj, list):
            return data_obj
        return []

    rows: List[Dict[str, Any]] = []
    page = 0
    page_size = 100
    while True:
        try:
            resource_path = (
                "v3/computer-prestages"
                f"?page={page}&page-size={page_size}&sort=id%3Adesc"
            )
            logger.info("Fetching PreStage list (page %s)...", page)
            r = jamf_client.pro_api_request(
                method="GET",
                resource_path=resource_path,
                override_headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json() or {}
            logger.debug("PreStage list response page %s: %s", page, _pp(data))
            batch = _extract_rows(data)
            rows.extend(batch)

            total = data.get("totalCount") if isinstance(data, dict) else None
            size = data.get("pageSize") if isinstance(data, dict) else None
            if size:
                page_size = int(size)

            if total is not None:
                if (page + 1) * page_size >= int(total):
                    break
            else:
                if len(batch) < page_size:
                    break

            page += 1
        except Exception as e:
            if page == 0 and _ask_retry_cancel(
                "Jamf PreStage list",
                f"Failed to load PreStage list.\n\n{e}\n\nRetry?"
            ):
                continue
            logger.error("JAMF: Could not fetch PreStage list: %s", e)
            break

    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = row.get("id") or row.get("prestageId") or row.get("prestage_id")
        if pid is None:
            continue
        try:
            pid = int(pid)
        except Exception:
            continue
        name = (row.get("displayName") or row.get("name") or row.get("prestageName") or "").strip()
        if not name:
            name = f"PreStage {pid}"
        out.append({"id": pid, "name": name})

    out = sorted(out, key=lambda r: (r.get("name") or "").lower())
    logger.info("PreStage list ready: %s item(s)", len(out))
    if logger.isEnabledFor(logging.DEBUG) and out:
        preview = ", ".join(f"{p['name']} (ID {p['id']})" for p in out[:5])
        logger.debug("PreStage list preview: %s%s", preview, " ..." if len(out) > 5 else "")
    return out


def _prompt_prestage_choice(prestages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Prompt the user to choose a PreStage from a dropdown."""
    if not _TK_OK:
        logger.error("Tk not available; cannot prompt for PreStage selection.")
        return None
    root = _ensure_tk_root()
    if not root:
        logger.error("Tk root unavailable; cannot prompt for PreStage selection.")
        return None
    if not prestages:
        _warn("PreStage selection", "No PreStages were returned from Jamf.")
        return None

    win = _tk.Toplevel(root)
    win.title("Select PreStage")
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()

    _tk.Label(win, text="Select target PreStage:").pack(anchor="w", padx=10, pady=(10, 4))

    display_map = {}
    display_values = []
    for p in prestages:
        label = f"{p.get('name', '').strip()} (ID {p.get('id')})"
        display_map[label] = p
        display_values.append(label)

    selection_var = _tk.StringVar(value=display_values[0] if display_values else "")
    combo = _ttk.Combobox(win, textvariable=selection_var, values=display_values, state="readonly", width=50)
    combo.pack(fill="x", padx=10, pady=4)

    result = {"choice": None}

    def _confirm():
        label = selection_var.get().strip()
        result["choice"] = display_map.get(label)
        win.destroy()

    def _cancel():
        win.destroy()

    btn_row = _tk.Frame(win)
    btn_row.pack(fill="x", padx=10, pady=(4, 10))
    _tk.Button(btn_row, text="Cancel", command=_cancel).pack(side="right")
    _tk.Button(btn_row, text="OK", command=_confirm).pack(side="right", padx=(0, 8))

    win.update_idletasks()
    try:
        win.lift()
        win.focus_force()
        win.wait_visibility()
    except Exception:
        pass
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = int((sw / 2) - (win.winfo_width() / 2))
    y = int((sh / 2) - (win.winfo_height() / 2))
    win.geometry(f"+{x}+{y}")
    win.wait_window()
    return result["choice"]


def _add_serial_to_prestage(
    jamf_client: JamfProClient,
    prestage_id: int,
    serial: str,
    settings: Dict[str, Any],
) -> bool:
    """Add a serial number to a PreStage scope (with verification + retry prompts)."""
    while True:
        scope = _get_prestage_scope_v2(jamf_client, prestage_id, settings)
        if scope is None:
            if not _ask_retry_cancel("Jamf PreStage scope",
                                     f"Failed to load scope for PreStage {prestage_id}.\n\nRetry?"):
                return False
            continue

        payload, dbg = _build_scope_add_payload(scope, serial)
        if settings.get("debug_verbose"):
            logger.debug(dbg)

        if not payload:
            logger.info("Serial already present in PreStage %s.", prestage_id)
            return True

        if settings.get("dry_run"):
            logger.info(
                "DRY RUN: Would add serial to PreStage %s with: %s",
                prestage_id,
                _pp(payload),
            )
            return True

        ok = _put_prestage_scope_v2(jamf_client, prestage_id, payload, settings)
        if not ok:
            if _ask_retry_cancel("Update PreStage scope failed",
                                 f"Could not update PreStage {prestage_id} scope.\n\nRetry?"):
                continue
            return False

        try:
            scope_after = _get_prestage_scope_v2(jamf_client, prestage_id, settings)
            if isinstance(scope_after, dict):
                a2 = scope_after.get("assignments")
                if isinstance(a2, dict) and (serial in (a2.get("serialNumbers") or [])):
                    return True
                if isinstance(a2, list) and any((row or {}).get("serialNumber") == serial for row in a2):
                    return True
        except Exception as ve:
            if _ask_retry_cancel("Verify PreStage add",
                                 f"Could not verify PreStage {prestage_id} add.\n\n{ve}\n\nRetry?"):
                continue
        if _ask_retry_cancel("Add not verified",
                             f"Serial not present in PreStage {prestage_id} after update.\n\nRetry?"):
            continue
        return False


# ==============================
# Delete + verification
# ==============================
def _verify_inventory_gone(jamf_client: JamfProClient, computer_id: int) -> bool:
    """Return True if the computer no longer exists (404) on either v2 or v1 GET."""
    for path in (f"v2/computers-inventory/{computer_id}", f"v1/computers-inventory/{computer_id}"):
        try:
            r = jamf_client.pro_api_request(
                method="GET",
                resource_path=path,
                override_headers={"Accept": "application/json"},
            )
            if r.status_code == 404:
                return True
            if r.status_code == 200:
                return False
        except Exception as e:
            sc = getattr(getattr(e, "response", None), "status_code", None)
            if sc == 404:
                return True
    return False


def _delete_computer_pro(
    jamf_client: JamfProClient,
    computer_id: int,
    settings: Dict[str, Any],
) -> bool:
    """
    DELETE the Jamf computer via Pro API v2:
      DELETE /api/v2/computers-inventory/{id}

    Success: 204/200
    404: treat as already deleted
    409/423/500: verify after a short delay; if 404 on GET, treat as success.
    Fallback: one-shot v1 delete if still present.
    """
    if settings.get("dry_run"):
        logger.info(
            "DRY RUN: Would DELETE Jamf computer-inventory ID %s (v2).",
            computer_id,
        )
        return True

    def _do_del(path: str):
        return jamf_client.pro_api_request(
            method="DELETE",
            resource_path=path,
            override_headers={"Accept": "application/json"},
        )

    path_v2 = f"v2/computers-inventory/{computer_id}"

    try:
        r = _do_del(path_v2)
        if r.status_code in (200, 204):
            logger.info("Deleted Jamf computer-inventory ID %s (v2).", computer_id)
            return True
        if r.status_code == 404:
            logger.info("Computer %s not found on v2; treating as already deleted.", computer_id)
            return True
        logger.warning("v2 delete returned %s; verifying...", r.status_code)
    except Exception as e:
        sc = getattr(getattr(e, "response", None), "status_code", None)
        logger.warning("v2 delete raised %s; verifying...", sc or "exception")

    time.sleep(0.75)
    if _verify_inventory_gone(jamf_client, computer_id):
        logger.info("Computer %s is gone (verified after error).", computer_id)
        return True

    try:
        logger.info("Falling back to v1 delete once...")
        r2 = _do_del(f"v1/computers-inventory/{computer_id}")
        if r2.status_code in (200, 204, 404):
            logger.info("Deleted (or already gone) ID %s via v1.", computer_id)
            return True
        try:
            detail = r2.json()
        except Exception:
            detail = r2.text
        logger.error("JAMF: v1 delete failed (%s): %s", r2.status_code, detail)
    except Exception as e:
        sc = getattr(getattr(e, "response", None), "status_code", None)
        if sc == 404:
            logger.info("Already gone on v1 (404) for ID %s.", computer_id)
            return True
        logger.error("JAMF: v1 delete request failed: %s", e)

    return False
