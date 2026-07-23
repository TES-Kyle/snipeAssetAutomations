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
from utilities.settings import get_settings
from utilities.otherApiBits import getAssetInfo
from utilities.tk_geometry import center_window
from utilities.api_retry import ensure_tk_root, ask_retry_cancel

from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider

logger = logging.getLogger(__name__)


# ==============================
# Settings helpers
# ==============================
def _to_bool(value, default: bool) -> bool:
    """Normalize truthy string/int values into a boolean.

    Args:
        value: Raw value to coerce (string, int, or None).
        default: Fallback when value is None or unrecognized.

    Returns:
        Boolean result.
    """
    logger.debug("_to_bool: value=%s, default=%s", value, default)
    if value is None:
        logger.debug("_to_bool: None value, returning default=%s", default)
        return default
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        logger.debug("_to_bool: truthy string %s -> True", s)
        return True
    if s in ("0", "false", "no", "n", "off"):
        logger.debug("_to_bool: falsy string %s -> False", s)
        return False
    logger.debug("_to_bool: unrecognized %s, returning default=%s", s, default)
    return default


def _status_code_of(exc: Exception):
    """Return the HTTP status code from a caught exception's response, or None."""
    return getattr(getattr(exc, "response", None), "status_code", None)


def _to_float(value, default: float) -> float:
    """Coerce a setting into a float, returning default on failure.

    Args:
        value: Raw value to coerce.
        default: Fallback on parse error.

    Returns:
        Float result.
    """
    logger.debug("_to_float: value=%s, default=%s", value, default)
    try:
        result = float(value)
        logger.debug("_to_float: parsed %s -> %s", value, result)
        return result
    except Exception:
        logger.debug("_to_float: could not parse %s, returning default=%s", value, default)
        return default


def get_prestage_settings() -> Dict[str, Any]:
    """Load Jamf PreStage settings from the settings store.

    Returns:
        Dict with parsed prestage config keys.
    """
    logger.debug("get_prestage_settings: loading settings")
    settings = get_settings()
    result = {
        "verify_ssl": _to_bool(settings.get("jamfPrestageVerifySSL", "1"), True),
        "rate_limit_delay": _to_float(settings.get("jamfPrestageRateLimitDelay", "0.35"), 0.35),
        "strict_removal_guard": _to_bool(settings.get("jamfPrestageStrictRemovalGuard", "1"), True),
        "dry_run": _to_bool(settings.get("jamfPrestageDryRun", "0"), False),
        "debug_verbose": _to_bool(settings.get("jamfPrestageDebugVerbose", "0"), False),
        "delete_after_remove": _to_bool(settings.get("jamfPrestageDeleteAfterRemove", "1"), True),
    }
    logger.debug("get_prestage_settings: verify_ssl=%s, dry_run=%s, debug_verbose=%s",
                 result["verify_ssl"], result["dry_run"], result["debug_verbose"])
    return result


def create_jamf_client(settings: Dict[str, Any]) -> JamfProClient:
    """Create a Jamf Pro client using settings-driven SSL verification.

    Args:
        settings: Settings dict from get_prestage_settings().

    Returns:
        Configured JamfProClient instance.
    """
    logger.debug("create_jamf_client: verify_ssl=%s", settings.get("verify_ssl"))
    logger.info("create_jamf_client: creating Jamf Pro client for %s", Key.jamfURL)
    client = JamfProClient(
        server=Key.jamfURL,
        credentials=ApiClientCredentialsProvider(Key.jamfClientID, Key.jamfClientSecret),
        session_config=SessionConfig(ssl_verify=settings["verify_ssl"], max_retries=5),
    )
    logger.debug("create_jamf_client: client created successfully")
    return client


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


def _warn(title: str, message: str) -> None:
    """Show a warning dialog, or log the message when Tk is unavailable.

    Args:
        title: Dialog window title.
        message: Warning text to display.
    """
    try:
        root = ensure_tk_root()
        if root:
            _mb.showwarning(title, message, parent=root)
            return
    except Exception:
        pass
    configure_logging()
    logger.warning("%s: %s", title, message)


def _confirm_action(title: str, message: str) -> bool:
    """Show a yes/no confirmation dialog and return the user's choice.

    Falls back to False (cancel) when Tk is unavailable or headless.

    Args:
        title: Dialog window title.
        message: Confirmation question text to display.

    Returns:
        True when the user chooses Yes; False on No, cancel, or in headless mode.
    """
    try:
        root = ensure_tk_root()
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
    """Pretty-print JSON-ish objects for logs, truncated for readability.

    Args:
        obj: Any serializable object.
        limit: Max character length before truncation.

    Returns:
        Formatted string representation.
    """
    logger.debug("_pp: serializing object of type=%s", type(obj).__name__)
    try:
        s = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > limit:
        logger.debug("_pp: output truncated from %s to %s chars", len(s), limit)
        return s[:limit] + "...(truncated)..."
    return s


# ==============================
# Snipe + Jamf lookups
# ==============================
def _get_serial_from_snipe(asset_tag: str) -> Optional[str]:
    """Load Snipe-IT asset and return its serial (or None).

    Args:
        asset_tag: Asset tag string to look up in Snipe-IT.

    Returns:
        Serial number string, or None if not found or on error.
    """
    logger.debug("_get_serial_from_snipe: asset_tag=%s", asset_tag)
    try:
        _vars, asset = getAssetInfo(asset_tag)
        logger.debug("_get_serial_from_snipe: asset info retrieved for %s", asset_tag)
    except Exception as e:
        logger.error("SNIPE: Failed to load asset '%s': %s", asset_tag, e)
        return None
    serial = (asset or {}).get("serial") or ""
    serial = serial.strip()
    if not serial:
        logger.error("SNIPE: Asset '%s' has no serial.", asset_tag)
        return None
    logger.debug("_get_serial_from_snipe: found serial=%s for asset_tag=%s", serial, asset_tag)
    return serial


def _find_jamf_computer_by_serial(
    jamf_client: JamfProClient,
    serial: str,
    settings: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Search Jamf inventory for the given serial and return a computer record or None.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        serial: Serial number to look up (comparison is case-insensitive).
        settings: Prestage settings dict from get_prestage_settings().

    Returns:
        Dict with keys 'id' (int) and 'name' (str), or None if not found or on error.
    """
    logger.info("Searching Jamf inventory for serial...")
    try:
        # Request only GENERAL + HARDWARE sections to keep the response lightweight.
        devices = jamf_client.pro_api.get_computer_inventory_v1(
            sections=["GENERAL", "HARDWARE"],
            page_size=2000,
        )
        if settings.get("debug_verbose"):
            logger.debug("Inventory count: %s", len(devices))
    except Exception as e:
        logger.error("JAMF: Failed to query inventory: %s", e)
        return None

    # Iterate all devices looking for a case-insensitive serial match.
    for d in devices:
        dev_serial = getattr(getattr(d, "hardware", None), "serialNumber", None)
        if dev_serial and dev_serial.strip().upper() == serial.strip().upper():
            # Prefer the top-level 'id' attribute; fall back to general.id.
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
    """Return the PreStage scope document for the given ID, or None for 404.

    Supports both shapes Jamf returns:
      A) {"prestageId":..,"assignments":{"serialNumbers":[...],...}, "versionLock":N}
      B) {"prestageId":..,"assignments":[{"serialNumber":...}, ...], "versionLock":N}

    Args:
        jamf_client: Authenticated JamfProClient instance.
        prestage_id: Numeric ID of the PreStage to query.
        settings: Prestage settings dict from get_prestage_settings().

    Returns:
        Scope dict on success, or None when not found or on API error.
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


def _flatten_scope_serials(scope: Dict) -> Optional[List[str]]:
    """Extract the flat list of serial numbers from either scope shape Jamf returns.

    Shared by _build_scope_put_payload and _build_scope_add_payload, which
    both need to normalize the same two API response shapes before doing
    their own add/remove logic on the flat list:
      A) assignments is a dict with a "serialNumbers" list.
      B) assignments is a list of {"serialNumber": ...} objects.

    Args:
        scope: Scope dict returned by _get_prestage_scope_v2.

    Returns:
        List of serial number strings (non-string entries dropped), or None
        when scope isn't a dict or has no recognizable "assignments" shape.
    """
    if not isinstance(scope, dict):
        return None
    assignments = scope.get("assignments")
    if isinstance(assignments, dict):
        cur = assignments.get("serialNumbers") or []
        if not isinstance(cur, list):
            cur = []
        return [s for s in cur if isinstance(s, str)]
    if isinstance(assignments, list):
        out = []
        for row in assignments:
            s = (row or {}).get("serialNumber")
            if isinstance(s, str) and s:
                out.append(s)
        return out
    return None


def _bad_scope_debug_message(scope: Dict) -> str:
    """Return the appropriate debug message for a scope that yielded no serials.

    Args:
        scope: Scope dict that failed to normalize via _flatten_scope_serials.

    Returns:
        Debug string distinguishing a non-dict scope from a dict with no
        recognizable "assignments" shape.
    """
    if not isinstance(scope, dict):
        return "[DEBUG] Bad scope object."
    return "[DEBUG] No 'assignments' in scope."


def _build_scope_put_payload(scope: Dict, serial: str) -> Tuple[Optional[Dict], str]:
    """Build the doc-style PUT body Jamf expects for a serial removal.

    Constructs {"serialNumbers":[...], "versionLock": <lock>} with only
    the given serial removed from the current scope.

    Args:
        scope: Current scope dict returned by _get_prestage_scope_v2.
        serial: Serial number to remove from the scope.

    Returns:
        (payload, debug_message): payload is None when the serial was not
        present or the scope object is invalid; debug_message describes the
        result.
    """
    serials_now = _flatten_scope_serials(scope)
    if serials_now is None:
        return None, _bad_scope_debug_message(scope)

    before = len(serials_now)
    # Build new list excluding only the target serial.
    serials_now = [s for s in serials_now if s != serial]
    after = len(serials_now)
    # If count is unchanged the serial was never in this scope.
    if after == before:
        return None, "[DEBUG] Serial not present; nothing to PUT."

    payload = {"serialNumbers": serials_now, "versionLock": scope.get("versionLock")}
    return payload, f"[DEBUG] Doc-style prune: serialNumbers {before}->{after}"


def _build_scope_add_payload(scope: Dict, serial: str) -> Tuple[Optional[Dict], str]:
    """Build the doc-style PUT body Jamf expects for adding a serial.

    Constructs {"serialNumbers":[...], "versionLock": <lock>} with the
    given serial appended to the current scope list.

    Args:
        scope: Current scope dict returned by _get_prestage_scope_v2.
        serial: Serial number to add to the scope.

    Returns:
        (payload, debug_message): payload is None when the serial is already
        present or the scope object is invalid; debug_message describes the
        result.
    """
    serials_now = _flatten_scope_serials(scope)
    if serials_now is None:
        return None, _bad_scope_debug_message(scope)

    if serial in serials_now:
        return None, "[DEBUG] Serial already present; nothing to PUT."

    before = len(serials_now)
    serials_now.append(serial)
    after = len(serials_now)

    payload = {"serialNumbers": serials_now, "versionLock": scope.get("versionLock")}
    return payload, f"[DEBUG] Doc-style add: serialNumbers {before}->{after}"


def _put_prestage_scope_v2(
    jamf_client: JamfProClient,
    prestage_id: int,
    scope_obj: Dict,
    settings: Dict[str, Any],
) -> bool:
    """PUT the scope payload to Jamf, retrying once on a 409 version-lock conflict.

    Sends PUT /api/v2/computer-prestages/{id}/scope with a doc-style body:
      {"serialNumbers":[...], "versionLock": <lock>}
    On 409 (lock mismatch), refreshes versionLock from a fresh GET and retries.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        prestage_id: Numeric ID of the target PreStage.
        scope_obj: Payload dict with 'serialNumbers' and 'versionLock'.
        settings: Prestage settings dict (dry_run flag is respected).

    Returns:
        True on success or dry-run; False when the PUT fails after retries.
    """
    if settings.get("dry_run"):
        logger.info(
            "DRY RUN: Would PUT scope for PreStage %s. Payload:\n%s",
            prestage_id,
            _pp(scope_obj),
        )
        return True

    def _do_put(body: Dict):
        """PUT the scope payload to the Jamf PreStage scope endpoint.

        Args:
            body: Scope payload dict to send.

        Returns:
            Response object from the Jamf Pro API request.
        """
        logger.debug("_do_put: PUT v2/computer-prestages/%s/scope, serialNumbers count=%s",
                     prestage_id, len(body.get("serialNumbers", [])))
        return jamf_client.pro_api_request(
            method="PUT",
            resource_path=f"v2/computer-prestages/{prestage_id}/scope",
            data=body,
            override_headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def _retry_after_lock_conflict(*, via_exception: bool = False) -> bool:
        """Refresh versionLock and retry the PUT once after a 409 conflict.

        Args:
            via_exception: True when called from the except-clause path
                (matches the prior "(exception)" log text for that path).

        Returns:
            True if the retried PUT succeeded (200/204), False otherwise.

        Raises:
            Exception: Propagates whatever _do_put(alt) raises, same as the
                original inline code in the 409-status-code branch.
        """
        logger.warning(
            "PreStage %s versionLock conflict%s. Refreshing and retrying...",
            prestage_id,
            " (exception)" if via_exception else "",
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
        r = _do_put(scope_obj)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 409:
            return _retry_after_lock_conflict()
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
        status = _status_code_of(e)
        if status == 409:
            try:
                return _retry_after_lock_conflict(via_exception=True)
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
    """Remove a serial from every PreStage it belongs to, with retry prompts.

    Fetches the aggregate scope map to determine candidate PreStages, then
    removes the serial from each and verifies the change. Presents retry/cancel
    dialogs on transient failures.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        serial: Serial number to remove from all matching PreStage scopes.
        settings: Prestage settings dict from get_prestage_settings().
        skip_ids: Optional set of PreStage IDs to exclude from consideration.

    Returns:
        Tuple of (seen, modified, candidate_count) where seen is the number of
        PreStages whose scopes were read, modified is those successfully updated,
        and candidate_count is the total number of candidates reported by Jamf.
    """
    skip_ids = skip_ids or set()
    # Fetch the aggregate scope map: serial -> list of prestage IDs.
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
            if not ask_retry_cancel("Jamf PreStage scopes",
                                     f"Failed to fetch aggregate scopes.\n\n{e}\n\nRetry?"):
                logger.error("JAMF: Could not fetch aggregate PreStage scopes: %s", e)
                agg = {}
                break

    # Extract candidate PreStage IDs from the aggregate map.
    candidate_ids: List[int] = []
    if isinstance(agg, dict) and "serialsByPrestageId" in agg:
        mapping = agg["serialsByPrestageId"]
        # Try all case variants since Jamf can return the key in any case.
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

    # Remove any IDs the caller asked us to skip (e.g., the target PreStage).
    if skip_ids:
        candidate_ids = [pid for pid in candidate_ids if pid not in skip_ids]
        if settings.get("debug_verbose"):
            logger.debug("Skipping PreStages: %s", ", ".join(map(str, skip_ids)))

    if not candidate_ids:
        logger.info("No candidate PreStages for this serial.")
        return (0, 0, 0)

    logger.info("Candidate PreStages: %s", ", ".join(map(str, candidate_ids)))

    # Track how many scopes were read and how many were actually modified.
    seen = 0
    changed = 0
    touched: List[int] = []

    for pid in candidate_ids:
        # Fetch the scope for this PreStage; retry on transient failure.
        scope = None
        while True:
            scope = _get_prestage_scope_v2(jamf_client, pid, settings)
            if scope is not None:
                break
            if not ask_retry_cancel("Jamf PreStage scope",
                                     f"Failed to load scope for PreStage {pid}.\n\n"
                                     f"Retry to refetch, or Cancel to skip this PreStage?"):
                logger.warning("Skipping PreStage %s (scope not available).", pid)
                break
        if scope is None:
            continue

        seen += 1

        # Build the removal payload; skip if serial is not in this scope.
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
            # Attempt the PUT with post-write verification, retrying on failures.
            while True:
                ok = _put_prestage_scope_v2(jamf_client, pid, payload, settings)
                if ok:
                    # Default to verified; check the scope to confirm removal.
                    verify_ok = True
                    try:
                        scope_after = _get_prestage_scope_v2(jamf_client, pid, settings)
                        if serial in (_flatten_scope_serials(scope_after) or []):
                            verify_ok = False
                    except Exception as ve:
                        if ask_retry_cancel("Verify removal",
                                             f"Could not verify PreStage {pid} removal.\n\n{ve}\n\nRetry verify?"):
                            continue
                        verify_ok = False

                    if verify_ok:
                        changed += 1
                        touched.append(pid)
                        logger.info("Removed from PreStage %s.", pid)
                        break
                    else:
                        # Serial still present — offer to retry the update.
                        if ask_retry_cancel("Removal not verified",
                                             f"Serial still appears in PreStage {pid} after update.\n\nRetry update?"):
                            continue
                        logger.warning(
                            "Serial still present after PUT in PreStage %s; not counting as modified.",
                            pid,
                        )
                        break
                else:
                    # PUT failed — offer to retry or skip this PreStage.
                    if ask_retry_cancel("Update PreStage scope failed",
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
    """Fetch all available computer PreStages and return them as id+name dicts.

    Pages through the v3/computer-prestages endpoint and normalizes each row
    into a simple {'id': int, 'name': str} record for use in selection UIs.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        settings: Prestage settings dict from get_prestage_settings().

    Returns:
        List of {'id': int, 'name': str} dicts sorted alphabetically by name.
    """
    def _extract_rows(data_obj):
        """Extract a list of row dicts from a Jamf paginated response.

        Args:
            data_obj: API response (dict or list).

        Returns:
            List of row dicts, or empty list if none found.
        """
        logger.debug("_extract_rows: data_obj type=%s", type(data_obj).__name__)
        if isinstance(data_obj, dict):
            for key in ("results", "prestages", "prestageList", "computerPrestageList", "items", "value"):
                if isinstance(data_obj.get(key), list):
                    rows = data_obj.get(key) or []
                    logger.debug("_extract_rows: found rows under key=%s, count=%s", key, len(rows))
                    return rows
        if isinstance(data_obj, list):
            logger.debug("_extract_rows: data_obj is list with %s items", len(data_obj))
            return data_obj
        logger.debug("_extract_rows: no rows found, returning []")
        return []

    rows: List[Dict[str, Any]] = []
    page = 0
    page_size = 100
    # Page through the v3 prestages endpoint until all results are collected.
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

            # Sync page_size from the server's reported value when available.
            total = data.get("totalCount") if isinstance(data, dict) else None
            size = data.get("pageSize") if isinstance(data, dict) else None
            if size:
                page_size = int(size)

            # Stop when we've fetched enough rows or the batch is short.
            if total is not None:
                if (page + 1) * page_size >= int(total):
                    break
            else:
                if len(batch) < page_size:
                    break

            page += 1
        except Exception as e:
            # Only offer retry on the first page; subsequent failures abort silently.
            if page == 0 and ask_retry_cancel(
                "Jamf PreStage list",
                f"Failed to load PreStage list.\n\n{e}\n\nRetry?"
            ):
                continue
            logger.error("JAMF: Could not fetch PreStage list: %s", e)
            break

    # Normalize raw rows into simple {id, name} dicts, skipping malformed entries.
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Try multiple key names Jamf has used across API versions.
        pid = row.get("id") or row.get("prestageId") or row.get("prestage_id")
        if pid is None:
            continue
        try:
            pid = int(pid)
        except Exception:
            continue
        # Similarly try multiple name keys; fall back to a synthetic label.
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
    """Show a modal dialog for the user to choose a PreStage from a dropdown.

    Args:
        prestages: List of {'id': int, 'name': str} dicts to populate the combo.

    Returns:
        The selected prestage dict, or None if the user cancels or Tk is unavailable.
    """
    if not _TK_OK:
        logger.error("Tk not available; cannot prompt for PreStage selection.")
        return None
    root = ensure_tk_root()
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
        """Capture the selected PreStage and close the dialog."""
        label = selection_var.get().strip()
        logger.debug("_confirm: selected label=%s", label)
        result["choice"] = display_map.get(label)
        logger.debug("_confirm: resolved choice id=%s", (result["choice"] or {}).get("id"))
        win.destroy()

    def _cancel():
        """Close the PreStage selection dialog without making a choice."""
        logger.debug("_cancel: user cancelled PreStage selection dialog")
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
    center_window(win)
    win.wait_window()
    return result["choice"]


def _add_serial_to_prestage(
    jamf_client: JamfProClient,
    prestage_id: int,
    serial: str,
    settings: Dict[str, Any],
) -> bool:
    """Add a serial number to a PreStage scope with verification and retry prompts.

    Fetches the current scope, builds the add payload, PUTs the update, and
    verifies the serial appears in the scope after the write. Presents
    retry/cancel dialogs on transient failures.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        prestage_id: Numeric ID of the target PreStage.
        serial: Serial number to add.
        settings: Prestage settings dict from get_prestage_settings().

    Returns:
        True when the serial is confirmed present in the scope; False otherwise.
    """
    while True:
        # Fetch the current scope to base our add payload on.
        scope = _get_prestage_scope_v2(jamf_client, prestage_id, settings)
        if scope is None:
            if not ask_retry_cancel("Jamf PreStage scope",
                                     f"Failed to load scope for PreStage {prestage_id}.\n\nRetry?"):
                return False
            continue

        # Build the payload that adds the serial; None means it's already there.
        payload, dbg = _build_scope_add_payload(scope, serial)
        if settings.get("debug_verbose"):
            logger.debug(dbg)

        if not payload:
            # Serial was already in scope — nothing to do.
            logger.info("Serial already present in PreStage %s.", prestage_id)
            return True

        if settings.get("dry_run"):
            logger.info(
                "DRY RUN: Would add serial to PreStage %s with: %s",
                prestage_id,
                _pp(payload),
            )
            return True

        # Attempt the PUT and offer retry if it fails.
        ok = _put_prestage_scope_v2(jamf_client, prestage_id, payload, settings)
        if not ok:
            if ask_retry_cancel("Update PreStage scope failed",
                                 f"Could not update PreStage {prestage_id} scope.\n\nRetry?"):
                continue
            return False

        # Verify the serial now appears in the scope after the write.
        try:
            scope_after = _get_prestage_scope_v2(jamf_client, prestage_id, settings)
            if serial in (_flatten_scope_serials(scope_after) or []):
                return True
        except Exception as ve:
            if ask_retry_cancel("Verify PreStage add",
                                 f"Could not verify PreStage {prestage_id} add.\n\n{ve}\n\nRetry?"):
                continue
        if ask_retry_cancel("Add not verified",
                             f"Serial not present in PreStage {prestage_id} after update.\n\nRetry?"):
            continue
        return False


# ==============================
# Delete + verification
# ==============================
def _verify_inventory_gone(jamf_client: JamfProClient, computer_id: int) -> bool:
    """Return True if the computer no longer exists in Jamf inventory.

    Checks both the v2 and v1 computer-inventory endpoints; a 404 on
    either confirms the record is gone.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        computer_id: Numeric Jamf computer ID to verify.

    Returns:
        True when the record is confirmed deleted (404); False if still present
        or if the status cannot be determined.
    """
    # Try v2 first, then v1 as a fallback; stop on the first conclusive answer.
    for path in (f"v2/computers-inventory/{computer_id}", f"v1/computers-inventory/{computer_id}"):
        try:
            r = jamf_client.pro_api_request(
                method="GET",
                resource_path=path,
                override_headers={"Accept": "application/json"},
            )
            # 404 confirms deletion; 200 confirms the record still exists.
            if r.status_code == 404:
                return True
            if r.status_code == 200:
                return False
        except Exception as e:
            # Some SDK versions raise instead of returning a 404 response.
            sc = _status_code_of(e)
            if sc == 404:
                return True
    # Could not determine state from either endpoint.
    return False


def _delete_computer_pro(
    jamf_client: JamfProClient,
    computer_id: int,
    settings: Dict[str, Any],
) -> bool:
    """Delete a Jamf computer inventory record via Pro API v2, with v1 fallback.

    Sends DELETE /api/v2/computers-inventory/{id}. On success (200/204) or
    already-deleted (404) returns True immediately. On ambiguous error codes
    (409/423/500) waits briefly and verifies via GET; if the record is gone
    treats that as success. Falls back to a one-shot v1 delete if v2 fails
    and the record still exists.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        computer_id: Numeric Jamf computer ID to delete.
        settings: Prestage settings dict (dry_run flag is respected).

    Returns:
        True when the record is confirmed deleted or already absent; False on
        unrecoverable failure.
    """
    if settings.get("dry_run"):
        logger.info(
            "DRY RUN: Would DELETE Jamf computer-inventory ID %s (v2).",
            computer_id,
        )
        return True

    def _do_del(path: str):
        """DELETE a Jamf computer inventory record at the given path.

        Args:
            path: API resource path for the delete operation.

        Returns:
            Response object from the Jamf Pro API request.
        """
        logger.debug("_do_del: DELETE %s", path)
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
        sc = _status_code_of(e)
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
        sc = _status_code_of(e)
        if sc == 404:
            logger.info("Already gone on v1 (404) for ID %s.", computer_id)
            return True
        logger.error("JAMF: v1 delete request failed: %s", e)

    return False


def delete_computer_with_retry(jamf_client, cid, cname, settings, success_message, failure_warn_message):
    """Delete a Jamf computer with a retry/cancel dialog on failure.

    Shared by jamf_remove_prestage_and_delete and jamf_delete_and_set_prestage,
    which differ only in their success/failure message wording.

    Args:
        jamf_client: Authenticated JamfProClient instance.
        cid: Numeric Jamf computer ID to delete.
        cname: Display name for the computer, used in the failure return message.
        settings: Prestage settings dict (dry_run flag respected by _delete_computer_pro).
        success_message: Message to return when deletion succeeds.
        failure_warn_message: Message shown via _warn() when the user gives up retrying.

    Returns:
        success_message on success, or "[ERROR] JAMF: Delete failed for {cname}
        (ID {cid})." if the user cancels after repeated failures.
    """
    while True:
        logger.info("delete_computer_with_retry: attempting to delete Jamf computer ID %s", cid)
        deleted_ok = _delete_computer_pro(jamf_client, cid, settings)
        if deleted_ok:
            logger.info("delete_computer_with_retry: successfully deleted Jamf computer ID %s", cid)
            return success_message
        logger.error("delete_computer_with_retry: delete failed for Jamf computer ID %s", cid)
        if ask_retry_cancel("Jamf delete failed",
                             f"Could not delete Jamf computer ID {cid}.\n\nRetry?"):
            logger.debug("delete_computer_with_retry: user chose retry for delete of ID %s", cid)
            continue
        _warn("Jamf delete failed", failure_warn_message)
        return f"[ERROR] JAMF: Delete failed for {cname} (ID {cid})."
