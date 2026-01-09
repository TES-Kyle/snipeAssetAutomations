#!/usr/bin/env python3
"""
jamf_prestage_remove_and_delete.py

Removes a Jamf computer from all PreStage scope(s) and then deletes the
computer inventory record. Uses Jamf Pro API via jamf_pro_sdk.

Endpoints used:
  - GET  /api/v2/computer-prestages/scope
  - GET  /api/v2/computer-prestages/{id}/scope
  - PUT  /api/v2/computer-prestages/{id}/scope
  - GET  /api/v2/computers-inventory/{id}           (verification)
  - DELETE /api/v2/computers-inventory/{id}
  - (fallback) GET/DELETE /api/v1/computers-inventory/{id}

Behavior:
  1) Find the Jamf computer by Snipe-IT asset tag (via serial).
  2) From the aggregate PreStage scope map, determine candidate PreStage IDs.
  3) For each candidate, remove this serial from scope using the doc-style body:
       {"serialNumbers":[...], "versionLock": <lock>}
     Then re-fetch the scope to verify removal.
  4) Delete the Jamf inventory record. If Jamf returns 500, verify by GET; if
     GET returns 404 we treat it as success.

Safety:
  - STRICT_REMOVAL_GUARD: if not fully removed from all candidate PreStages,
    skip deletion to avoid orphaned PreStage assignments.
  - DELETE_AFTER_REMOVE toggle to test scope updates without deleting.
  - DRY_RUN toggle to preview actions without making changes.

Adds:
  - Retry/Cancel messageboxes for failures (fetch aggregate scopes, per-PreStage
    scope GET, scope PUT, delete) with safe console fallback when headless.
  - Warnings when PreStages are found but not removed, or delete fails after removal.
"""

import json
import logging
import time
from typing import Optional, Tuple, Dict, List, Any

from utilities import Key
from utilities.logging_utils import configure_logging
from utilities.otherApiBits import getAssetInfo

from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider

logger = logging.getLogger(__name__)

# ==============================
# Configuration
# ==============================
JAMF_URL            = Key.jamfURL
JAMF_CLIENT_ID      = Key.jamfClientID
JAMF_CLIENT_SECRET  = Key.jamfClientSecret

VERIFY_SSL           = True
RATE_LIMIT_DELAY     = 0.35
STRICT_REMOVAL_GUARD = True

# ---- Toggle presets ---------------------------------
# No Update Test
# DRY_RUN             = True
# DEBUG_VERBOSE       = True
# DELETE_AFTER_REMOVE = False

# Update-only (no delete)
# DRY_RUN             = False
# DEBUG_VERBOSE       = True
# DELETE_AFTER_REMOVE = False

# Full Test (live)
# DRY_RUN             = False
# DEBUG_VERBOSE       = True
# DELETE_AFTER_REMOVE = True

# Normal operation
DRY_RUN             = False
DEBUG_VERBOSE       = False
DELETE_AFTER_REMOVE = True
# -----------------------------------------------------

# ==============================
# Dialog helpers (messagebox with safe fallback)
# ==============================
try:
    import tkinter as _tk
    from tkinter import messagebox as _mb
    _TK_OK = True
except Exception:
    _tk = None
    _mb = None
    _TK_OK = False

def _ensure_tk_root():
    """Make a hidden Tk root once, if possible."""
    if not _TK_OK:
        return None
    root = getattr(_ensure_tk_root, "_root", None)
    try:
        # Create and cache a hidden root to parent dialogs.
        if root is None or not root.winfo_exists():
            root = _tk.Tk()
            root.withdraw()
            _ensure_tk_root._root = root
        return root
    except Exception:
        return None

def _ask_retry_cancel(title: str, message: str) -> bool:
    """Return True to retry, False to cancel. Falls back to False when headless."""
    try:
        # Prefer a GUI dialog when Tk is available.
        root = _ensure_tk_root()
        if root:
            return bool(_mb.askretrycancel(title, message, parent=root))
    except Exception:
        pass
    # Headless fallback: log and cancel.
    configure_logging()
    logger.warning("Prompt (no GUI): %s: %s -> cancel", title, message)
    return False

def _warn(title: str, message: str) -> None:
    """Show a warning dialog (or print headless)."""
    try:
        # Show dialog when possible.
        root = _ensure_tk_root()
        if root:
            _mb.showwarning(title, message, parent=root)
            return
    except Exception:
        pass
    # Headless fallback: log warning.
    configure_logging()
    logger.warning("%s: %s", title, message)

# ==============================
# Small utilities
# ==============================
def _pp(obj: Any, limit: int = 1600) -> str:
    """Pretty-print JSON-ish objects for logs, truncated for readability."""
    try:
        # Try JSON formatting first for structured output.
        s = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        # Fallback to string repr.
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + " …(truncated)…"

# ==============================
# Snipe + Jamf lookups
# ==============================
def _get_serial_from_snipe(asset_tag: str) -> Optional[str]:
    """Load Snipe-IT asset and return its serial (or None)."""
    try:
        # Fetch the asset record by tag.
        _vars, asset = getAssetInfo(asset_tag)
        if DEBUG_VERBOSE:
            logger.debug(
                "Snipe asset: serial=%r, name=%r",
                asset.get("serial"),
                asset.get("name"),
            )
    except Exception as e:
        logger.error("SNIPE: Failed to load asset '%s': %s", asset_tag, e)
        return None
    # Normalize and validate the serial.
    serial = (asset or {}).get("serial") or ""
    serial = serial.strip()
    if not serial:
        logger.error("SNIPE: Asset '%s' has no serial.", asset_tag)
        return None
    return serial

def _find_jamf_computer_by_serial(jamf_client: JamfProClient, serial: str) -> Optional[Dict]:
    """Search Jamf inventory for the given serial and return {'id','name'} or None."""
    logger.info("Searching Jamf inventory for serial...")
    try:
        # Pull a snapshot of inventory and scan for matching serials.
        devices = jamf_client.pro_api.get_computer_inventory_v1(
            sections=["GENERAL", "HARDWARE"],
            page_size=2000
        )
        if DEBUG_VERBOSE:
            logger.debug("Inventory count: %s", len(devices))
    except Exception as e:
        logger.error("JAMF: Failed to query inventory: %s", e)
        return None

    # Iterate through inventory to find a matching serial.
    for d in devices:
        dev_serial = getattr(getattr(d, "hardware", None), "serialNumber", None)
        if dev_serial and dev_serial.strip().upper() == serial.strip().upper():
            dev_id   = getattr(d, "id", None) or getattr(getattr(d, "general", None), "id", None)
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
def _get_prestage_scope_v2(jamf_client: JamfProClient, prestage_id: int) -> Optional[Dict]:
    """
    Return the PreStage scope document for the given ID, or None for 404.
    Supports both shapes Jamf returns:
      A) {"prestageId":..,"assignments":{"serialNumbers":[...],...}, "versionLock":N}
      B) {"prestageId":..,"assignments":[{"serialNumber":...}, ...], "versionLock":N}
    """
    try:
        # Fetch the scope document for this PreStage.
        r = jamf_client.pro_api_request(
            method="GET",
            resource_path=f"v2/computer-prestages/{prestage_id}/scope",
            override_headers={"Accept": "application/json"}
        )
        if DEBUG_VERBOSE:
            logger.debug(
                "GET v2/computer-prestages/%s/scope -> %s",
                prestage_id,
                r.status_code,
            )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        # Parse JSON payload for downstream handling.
        scope = r.json() or {}
    except Exception as e:
        logger.error("JAMF: Get scope for PreStage %s failed: %s", prestage_id, e)
        return None

    if DEBUG_VERBOSE:
        keys = list(scope.keys())
        logger.debug("Scope %s keys: %s", prestage_id, keys)
        a = scope.get("assignments", None)
        if isinstance(a, dict):
            ak = list(a.keys())
            logger.debug("assignments is dict; keys: %s", ak)
            for k in ("serialNumbers", "deviceIds", "jamfProComputerIds", "computerIds"):
                v = a.get(k)
                if isinstance(v, list):
                    logger.debug("assignments %s: %s", k, len(v))
        elif isinstance(a, list):
            logger.debug("assignments is list; len=%s", len(a))
            if a and isinstance(a[0], dict):
                logger.debug("assignments[0] keys: %s", list(a[0].keys()))
        else:
            logger.debug("assignments missing or unrecognized")
    return scope

def _build_scope_put_payload(scope: Dict, serial: str) -> Tuple[Optional[Dict], str]:
    """
    Build the doc-style PUT body Jamf expects:
      {"serialNumbers":[...], "versionLock": <lock>}
    Removes only this serial. Returns (payload_or_None, debug_message).
    """
    # Validate expected structure.
    if not isinstance(scope, dict):
        return None, "[DEBUG] Bad scope object."

    version_lock = scope.get("versionLock")
    assignments   = scope.get("assignments")

    before = 0
    serials_now: List[str] = []

    # Jamf may return assignments as a dict of arrays.
    if isinstance(assignments, dict):
        cur = assignments.get("serialNumbers") or []
        if not isinstance(cur, list):
            cur = []
        before      = len(cur)
        serials_now = [s for s in cur if s != serial]

    # Or as a list of assignment rows.
    elif isinstance(assignments, list):
        cur = []
        for row in assignments:
            s = (row or {}).get("serialNumber")
            if isinstance(s, str) and s:
                cur.append(s)
        before      = len(cur)
        serials_now = [s for s in cur if s != serial]

    else:
        return None, "[DEBUG] No 'assignments' in scope."

    after = len(serials_now)
    # If the serial is not present, there is nothing to update.
    if after == before:
        return None, "[DEBUG] Serial not present; nothing to PUT."

    # Build the doc-style payload expected by Jamf.
    payload = {"serialNumbers": serials_now, "versionLock": version_lock}
    return payload, f"[DEBUG] Doc-style prune: serialNumbers {before}->{after}"

def _put_prestage_scope_v2(jamf_client: JamfProClient, prestage_id: int, scope_obj: Dict) -> bool:
    """
    PUT /api/v2/computer-prestages/{id}/scope using doc-style payload:
      {"serialNumbers":[...], "versionLock": <lock>}
    On 409 (lock mismatch), refresh versionLock once and retry.
    """
    if DRY_RUN:
        # Dry-run mode logs the intended payload only.
        logger.info(
            "DRY RUN: Would PUT scope for PreStage %s. Payload:\n%s",
            prestage_id,
            _pp(scope_obj),
        )
        return True

    def _do_put(body: Dict):
        """Execute the PreStage scope PUT request."""
        return jamf_client.pro_api_request(
            method="PUT",
            resource_path=f"v2/computer-prestages/{prestage_id}/scope",
            data=body,
            override_headers={"Accept": "application/json", "Content-Type": "application/json"}
        )

    try:
        # Attempt a normal PUT first.
        r = _do_put(scope_obj)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 409:
            # Handle versionLock conflicts by reloading and retrying once.
            logger.warning(
                "PreStage %s versionLock conflict. Refreshing and retrying...",
                prestage_id,
            )
            scope_now = _get_prestage_scope_v2(jamf_client, prestage_id) or {}
            new_lock  = scope_now.get("versionLock")
            alt = {
                "serialNumbers": scope_obj.get("serialNumbers", []),
                "versionLock": new_lock
            }
            r2 = _do_put(alt)
            if r2.status_code in (200, 204):
                return True
            try: detail2 = r2.json()
            except Exception: detail2 = r2.text
            logger.error(
                "JAMF: PUT scope %s failed after lock refresh (%s): %s",
                prestage_id,
                r2.status_code,
                detail2,
            )
            return False
        try: detail = r.json()
        except Exception: detail = r.text
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
            # Retry once on lock conflicts raised as exceptions.
            logger.warning(
                "PreStage %s versionLock conflict (exception). Refreshing and retrying...",
                prestage_id,
            )
            scope_now = _get_prestage_scope_v2(jamf_client, prestage_id) or {}
            new_lock  = scope_now.get("versionLock")
            alt = {
                "serialNumbers": scope_obj.get("serialNumbers", []),
                "versionLock": new_lock
            }
            try:
                r2 = _do_put(alt)
                if r2.status_code in (200, 204):
                    return True
                try: detail2 = r2.json()
                except Exception: detail2 = r2.text
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

# ==============================
# Remove from all PreStages
# ==============================
def _remove_from_all_prestages(jamf_client: JamfProClient, serial: str, computer_id: int) -> Tuple[int, int, int]:
    """
    Determine candidate PreStages for this serial, remove the serial from each,
    and verify removal. Returns (seen, modified, candidate_count).
    """
    # Step 1: Fetch aggregate scope map with retry dialog.
    agg = {}
    while True:
        try:
            r = jamf_client.pro_api_request(
                method="GET",
                resource_path="v2/computer-prestages/scope",
                override_headers={"Accept": "application/json"}
            )
            r.raise_for_status()
            agg = r.json() or {}
            if DEBUG_VERBOSE:
                logger.debug(
                    "GET v2/computer-prestages/scope -> %s",
                    r.status_code,
                )
            break
        except Exception as e:
            if not _ask_retry_cancel("Jamf PreStage scopes",
                                     f"Failed to fetch aggregate scopes.\n\n{e}\n\nRetry?"):
                logger.error("JAMF: Could not fetch aggregate PreStage scopes: %s", e)
                agg = {}
                break

    # Step 2: Determine candidate PreStage IDs for this serial.
    candidate_ids: List[int] = []
    if isinstance(agg, dict) and "serialsByPrestageId" in agg:
        mapping = agg["serialsByPrestageId"]
        v = mapping.get(serial) or mapping.get(serial.upper()) or mapping.get(serial.lower())
        if isinstance(v, list):
            for x in v:
                try: candidate_ids.append(int(x))
                except Exception: pass
        elif v is not None:
            try: candidate_ids.append(int(v))
            except Exception: pass

    if not candidate_ids:
        logger.info("No candidate PreStages for this serial.")
        return (0, 0, 0)

    logger.info("Candidate PreStages: %s", ", ".join(map(str, candidate_ids)))

    seen = 0
    changed = 0
    touched: List[int] = []

    # Step 3: For each candidate PreStage, remove the serial.
    for pid in candidate_ids:
        # --- GET scope (retryable) ---
        scope = None
        while True:
            scope = _get_prestage_scope_v2(jamf_client, pid)
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

        # Build the update payload and skip if no change needed.
        payload, dbg = _build_scope_put_payload(scope, serial)
        if DEBUG_VERBOSE:
            logger.debug(dbg)
        if not payload:
            # serial not found in this scope; nothing to do
            if RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY)
            continue

        if DRY_RUN:
            # Dry-run: log intended change and mark as modified.
            logger.info(
                "DRY RUN: Would update PreStage %s with: %s",
                pid,
                _pp(payload),
            )
            changed += 1
            touched.append(pid)
        else:
            # --- PUT scope (retryable once per prompt loop) ---
            while True:
                ok = _put_prestage_scope_v2(jamf_client, pid, payload)
                if ok:
                    # Verify removal by reloading the scope.
                    verify_ok = True
                    try:
                        scope_after = _get_prestage_scope_v2(jamf_client, pid)
                        if isinstance(scope_after, dict):
                            a2 = scope_after.get("assignments")
                            if isinstance(a2, dict) and (serial in (a2.get("serialNumbers") or [])):
                                verify_ok = False
                            elif isinstance(a2, list) and any((row or {}).get("serialNumber") == serial for row in a2):
                                verify_ok = False
                    except Exception as ve:
                        if _ask_retry_cancel("Verify removal",
                                             f"Could not verify PreStage {pid} removal.\n\n{ve}\n\nRetry verify?"):
                            continue  # retry verify (re-enters loop; ok to re-PUT)
                        verify_ok = False

                    if verify_ok:
                        changed += 1
                        touched.append(pid)
                        logger.info("Removed from PreStage %s.", pid)
                        break  # next PreStage
                    else:
                        # If verification fails, optionally retry the update.
                        if _ask_retry_cancel("Removal not verified",
                                             f"Serial still appears in PreStage {pid} after update.\n\nRetry update?"):
                            continue
                        logger.warning(
                            "Serial still present after PUT in PreStage %s; not counting as modified.",
                            pid,
                        )
                        break
                else:
                    # Update failed; prompt for retry or skip.
                    if _ask_retry_cancel("Update PreStage scope failed",
                                         f"Could not update PreStage {pid} scope.\n\nRetry?"):
                        continue
                    logger.warning("Skipped updating PreStage %s.", pid)
                    break

        # Throttle between PreStage updates.
        if RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY)

    if touched:
        logger.info("Updated PreStages: %s", ", ".join(map(str, touched)))
    else:
        logger.info("No scope updates were necessary.")

    # If candidates existed but we didn’t modify any, warn the operator.
    if candidate_ids and changed == 0:
        _warn("PreStage removal",
              "Jamf reported candidate PreStages for this device, but I could not "
              "remove it from any of them.\n\n"
              "You may wish to retry updates, or inspect the PreStages manually.")

    return (seen, changed, len(candidate_ids))

# ==============================
# Delete + verification
# ==============================
def _verify_inventory_gone(jamf_client: JamfProClient, computer_id: int) -> bool:
    """
    Return True if the computer no longer exists (404) on either v2 or v1 GET.
    """
    # Probe both v2 and v1 endpoints to confirm deletion.
    for path in (f"v2/computers-inventory/{computer_id}", f"v1/computers-inventory/{computer_id}"):
        try:
            r = jamf_client.pro_api_request(
                method="GET",
                resource_path=path,
                override_headers={"Accept": "application/json"}
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

def _delete_computer_pro(jamf_client: JamfProClient, computer_id: int) -> bool:
    """
    DELETE the Jamf computer via Pro API v2:
      DELETE /api/v2/computers-inventory/{id}

    Success: 204/200
    404: treat as already deleted
    409/423/500: verify after a short delay; if 404 on GET, treat as success.
    Fallback: one-shot v1 delete if still present.
    """
    if DRY_RUN:
        # Dry-run mode: do not delete, just log intent.
        logger.info(
            "DRY RUN: Would DELETE Jamf computer-inventory ID %s (v2).",
            computer_id,
        )
        return True

    def _do_del(path: str):
        """Execute a Jamf Pro API DELETE request."""
        return jamf_client.pro_api_request(
            method="DELETE",
            resource_path=path,
            override_headers={"Accept": "application/json"}
        )

    path_v2 = f"v2/computers-inventory/{computer_id}"

    # Step 1: Try v2 delete first.
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

    # Step 2: Verify state after error/exception (handles “500 but actually deleted”).
    time.sleep(0.75)
    if _verify_inventory_gone(jamf_client, computer_id):
        logger.info("Computer %s is gone (verified after error).", computer_id)
        return True

    # Step 3: Optional v1 fallback if v2 did not confirm deletion.
    try:
        logger.info("Falling back to v1 delete once...")
        r2 = _do_del(f"v1/computers-inventory/{computer_id}")
        if r2.status_code in (200, 204, 404):
            logger.info("Deleted (or already gone) ID %s via v1.", computer_id)
            return True
        try: detail = r2.json()
        except Exception: detail = r2.text
        logger.error("JAMF: v1 delete failed (%s): %s", r2.status_code, detail)
    except Exception as e:
        sc = getattr(getattr(e, "response", None), "status_code", None)
        if sc == 404:
            logger.info("Already gone on v1 (404) for ID %s.", computer_id)
            return True
        logger.error("JAMF: v1 delete request failed: %s", e)

    return False

# ==============================
# Entry point for Consisterizer
# ==============================
def jamf_remove_prestage_and_delete(asset_tag: str) -> str:
    """Remove a device from PreStage scopes and delete its Jamf inventory record.

    High-level workflow:
      - Resolve serial from Snipe-IT.
      - Initialize Jamf client.
      - Locate Jamf computer by serial.
      - Remove from all candidate PreStages (with verification).
      - Optionally delete (with post-error verification and fallback).

    Args:
        asset_tag: Snipe-IT asset tag to resolve.

    Returns:
        Status string suitable for the GUI result label.
    """
    # Step 0: Validate input early.
    if not asset_tag:
        return "[ERROR] No asset tag provided."

    configure_logging()
    logger.info("=== Jamf Remove-from-PreStage + Delete ===")
    logger.info("Asset Tag: %s", asset_tag)
    logger.info("Mode: %s", "DRY RUN" if DRY_RUN else "LIVE")

    # Step 1: Resolve serial number via Snipe-IT.
    serial = _get_serial_from_snipe(asset_tag)
    if not serial:
        return f"[ERROR] SNIPE: No serial for asset {asset_tag}."
    logger.info("Serial: %s", serial)

    try:
        # Step 2: Initialize Jamf client.
        logger.info("Initializing Jamf Pro client...")
        jamf_client = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5),
        )
        logger.info("Jamf client ready.")
    except Exception as e:
        return f"[ERROR] JAMF: Client init failed: {e}"

    comp = _find_jamf_computer_by_serial(jamf_client, serial)
    if not comp:
        return f"[ERROR] JAMF: No computer with serial {serial}."
    # Capture ID/name for logs and downstream delete calls.
    cid, cname = comp["id"], comp["name"]
    logger.info("Target: %s (ID %s)", cname, cid)

    # Step 3: Remove serial from all candidate PreStages.
    seen, modified, candidates = _remove_from_all_prestages(jamf_client, serial, cid)
    logger.info("PreStages seen: %s, modified: %s, candidates: %s", seen, modified, candidates)

    if not DELETE_AFTER_REMOVE:
        # Step 4: Respect the delete toggle (update-only mode).
        return (f"{'[DRY RUN] ' if DRY_RUN else ''}"
                f"Removed {serial} from {modified}/{seen} PreStage(s)"
                f"{'' if candidates == seen else f' (candidates={candidates})'}; "
                f"SKIPPED delete (toggle).")

    if STRICT_REMOVAL_GUARD and candidates > 0 and modified < candidates:
        # Step 5: Guard deletion when removal is incomplete.
        msg = (f"Skipped delete: PreStage removal incomplete "
               f"({modified}/{candidates}).\n\n"
               "Delete is guarded to prevent orphaned PreStage assignments.")
        _warn("Deletion skipped (safe-guard)", msg)
        return (f"[SAFEGUARD] Skipped delete; PreStage removal incomplete "
                f"({modified}/{candidates} updated).")

    # Step 6: Delete the Jamf inventory record with retry prompt.
    while True:
        deleted_ok = _delete_computer_pro(jamf_client, cid)
        if deleted_ok:
            return f"Deleted Jamf computer-inventory ID {cid}."
        if _ask_retry_cancel("Jamf delete failed",
                             f"Could not delete Jamf computer ID {cid}.\n\nRetry?"):
            continue
        _warn("Jamf delete failed",
              f"Removal from PreStages may have succeeded, but deletion failed for ID {cid}.")
        return f"[ERROR] JAMF: Delete failed for {cname} (ID {cid})."

if __name__ == "__main__":
    """
    Set TEST_ASSET_TAG to try a manual run.
    Choose your toggle preset in the configuration section above.
    """
    TEST_ASSET_TAG = "5703"
    if TEST_ASSET_TAG:
        configure_logging(log_to_console=True)
        logger.info(jamf_remove_prestage_and_delete(TEST_ASSET_TAG))
    else:
        configure_logging(log_to_console=True)
        logger.info("Set TEST_ASSET_TAG to try a manual run.")
