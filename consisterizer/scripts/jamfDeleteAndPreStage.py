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

import time
import json
from typing import Optional, Tuple, Dict, List, Any

from utilities import Key
from utilities.otherApiBits import getAssetInfo

from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider

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
        root = _ensure_tk_root()
        if root:
            return bool(_mb.askretrycancel(title, message, parent=root))
    except Exception:
        pass
    print(f"[PROMPT] {title}: {message} -> cancel (no GUI)")
    return False

def _warn(title: str, message: str) -> None:
    """Show a warning dialog (or print headless)."""
    try:
        root = _ensure_tk_root()
        if root:
            _mb.showwarning(title, message, parent=root)
            return
    except Exception:
        pass
    print(f"[WARN] {title}: {message}")

# ==============================
# Small utilities
# ==============================
def _pp(obj: Any, limit: int = 1600) -> str:
    """Pretty-print JSON-ish objects for logs, truncated for readability."""
    try:
        s = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + " …(truncated)…"

# ==============================
# Snipe + Jamf lookups
# ==============================
def _get_serial_from_snipe(asset_tag: str) -> Optional[str]:
    """Load Snipe-IT asset and return its serial (or None)."""
    try:
        _vars, asset = getAssetInfo(asset_tag)
        if DEBUG_VERBOSE:
            print(f"[DEBUG] Snipe asset: serial={asset.get('serial')!r}, name={asset.get('name')!r}")
    except Exception as e:
        print(f"[ERROR] SNIPE: Failed to load asset '{asset_tag}': {e}")
        return None
    serial = (asset or {}).get("serial") or ""
    serial = serial.strip()
    if not serial:
        print(f"[ERROR] SNIPE: Asset '{asset_tag}' has no serial.")
        return None
    return serial

def _find_jamf_computer_by_serial(jamf_client: JamfProClient, serial: str) -> Optional[Dict]:
    """Search Jamf inventory for the given serial and return {'id','name'} or None."""
    print("[INFO] Searching Jamf inventory for serial…")
    try:
        devices = jamf_client.pro_api.get_computer_inventory_v1(
            sections=["GENERAL", "HARDWARE"],
            page_size=2000
        )
        if DEBUG_VERBOSE:
            print(f"[DEBUG] Inventory count: {len(devices)}")
    except Exception as e:
        print(f"[ERROR] JAMF: Failed to query inventory: {e}")
        return None

    for d in devices:
        dev_serial = getattr(getattr(d, "hardware", None), "serialNumber", None)
        if dev_serial and dev_serial.strip().upper() == serial.strip().upper():
            dev_id   = getattr(d, "id", None) or getattr(getattr(d, "general", None), "id", None)
            dev_name = getattr(getattr(d, "general", None), "name", None) or f"ID {dev_id}"
            if dev_id is None:
                continue
            print(f"[INFO] Match: {dev_name} (ID {dev_id})")
            return {"id": int(dev_id), "name": dev_name}
    print(f"[WARN] No Jamf computer found with serial {serial}.")
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
        r = jamf_client.pro_api_request(
            method="GET",
            resource_path=f"v2/computer-prestages/{prestage_id}/scope",
            override_headers={"Accept": "application/json"}
        )
        if DEBUG_VERBOSE:
            print(f"[DEBUG] GET v2/computer-prestages/{prestage_id}/scope -> {r.status_code}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        scope = r.json() or {}
    except Exception as e:
        print(f"[ERROR] JAMF: Get scope for PreStage {prestage_id} failed: {e}")
        return None

    if DEBUG_VERBOSE:
        keys = list(scope.keys())
        print(f"[DEBUG] Scope {prestage_id} keys: {keys}")
        a = scope.get("assignments", None)
        if isinstance(a, dict):
            ak = list(a.keys())
            print(f"[DEBUG]  assignments is dict; keys: {ak}")
            for k in ("serialNumbers", "deviceIds", "jamfProComputerIds", "computerIds"):
                v = a.get(k)
                if isinstance(v, list):
                    print(f"[DEBUG]   - {k}: {len(v)}")
        elif isinstance(a, list):
            print(f"[DEBUG]  assignments is list; len={len(a)}")
            if a and isinstance(a[0], dict):
                print(f"[DEBUG]   assignments[0] keys: {list(a[0].keys())}")
        else:
            print("[DEBUG]  assignments missing or unrecognized")
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
    assignments   = scope.get("assignments")

    before = 0
    serials_now: List[str] = []

    if isinstance(assignments, dict):
        cur = assignments.get("serialNumbers") or []
        if not isinstance(cur, list):
            cur = []
        before      = len(cur)
        serials_now = [s for s in cur if s != serial]

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
    if after == before:
        return None, "[DEBUG] Serial not present; nothing to PUT."

    payload = {"serialNumbers": serials_now, "versionLock": version_lock}
    return payload, f"[DEBUG] Doc-style prune: serialNumbers {before}->{after}"

def _put_prestage_scope_v2(jamf_client: JamfProClient, prestage_id: int, scope_obj: Dict) -> bool:
    """
    PUT /api/v2/computer-prestages/{id}/scope using doc-style payload:
      {"serialNumbers":[...], "versionLock": <lock>}
    On 409 (lock mismatch), refresh versionLock once and retry.
    """
    if DRY_RUN:
        print(f"[DRY RUN] Would PUT scope for PreStage {prestage_id}. Payload:\n{_pp(scope_obj)}")
        return True

    def _do_put(body: Dict):
        return jamf_client.pro_api_request(
            method="PUT",
            resource_path=f"v2/computer-prestages/{prestage_id}/scope",
            data=body,
            override_headers={"Accept": "application/json", "Content-Type": "application/json"}
        )

    try:
        r = _do_put(scope_obj)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 409:
            print(f"[WARN] PreStage {prestage_id} versionLock conflict. Refreshing and retrying…")
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
            print(f"[ERROR] JAMF: PUT scope {prestage_id} failed after lock refresh ({r2.status_code}): {detail2}")
            return False
        try: detail = r.json()
        except Exception: detail = r.text
        print(f"[ERROR] JAMF: PUT scope {prestage_id} failed ({r.status_code}): {detail}")
        return False
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 409:
            print(f"[WARN] PreStage {prestage_id} versionLock conflict (exception). Refreshing and retrying…")
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
                print(f"[ERROR] JAMF: PUT scope {prestage_id} failed after lock refresh ({r2.status_code}): {detail2}")
                return False
            except Exception as e2:
                print(f"[ERROR] JAMF: PUT scope {prestage_id} retry failed: {e2}")
                return False

        print(f"[ERROR] JAMF: PUT scope {prestage_id} failed: {e}")
        return False

# ==============================
# Remove from all PreStages
# ==============================
def _remove_from_all_prestages(jamf_client: JamfProClient, serial: str, computer_id: int) -> Tuple[int, int, int]:
    """
    Determine candidate PreStages for this serial, remove the serial from each,
    and verify removal. Returns (seen, modified, candidate_count).
    """
    # Aggregate: serial -> prestageId(s)  (with retry dialog)
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
                print(f"[DEBUG] GET v2/computer-prestages/scope -> {r.status_code}")
            break
        except Exception as e:
            if not _ask_retry_cancel("Jamf PreStage scopes",
                                     f"Failed to fetch aggregate scopes.\n\n{e}\n\nRetry?"):
                print(f"[ERROR] JAMF: Could not fetch aggregate PreStage scopes: {e}")
                agg = {}
                break

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
        print("[INFO] No candidate PreStages for this serial.")
        return (0, 0, 0)

    print(f"[INFO] Candidate PreStages: {', '.join(map(str, candidate_ids))}")

    seen = 0
    changed = 0
    touched: List[int] = []

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
                print(f"[WARN] Skipping PreStage {pid} (scope not available).")
                break
        if scope is None:
            continue

        seen += 1

        payload, dbg = _build_scope_put_payload(scope, serial)
        if DEBUG_VERBOSE:
            print(dbg)
        if not payload:
            # serial not found in this scope; nothing to do
            if RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY)
            continue

        if DRY_RUN:
            print(f"[DRY RUN] Would update PreStage {pid} with: {_pp(payload)}")
            changed += 1
            touched.append(pid)
        else:
            # --- PUT scope (retryable once per prompt loop) ---
            while True:
                ok = _put_prestage_scope_v2(jamf_client, pid, payload)
                if ok:
                    # verify removal
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
                        print(f"[SUCCESS] Removed from PreStage {pid}.")
                        break  # next PreStage
                    else:
                        if _ask_retry_cancel("Removal not verified",
                                             f"Serial still appears in PreStage {pid} after update.\n\nRetry update?"):
                            continue
                        print(f"[WARN] Serial still present after PUT in PreStage {pid}; not counting as modified.")
                        break
                else:
                    if _ask_retry_cancel("Update PreStage scope failed",
                                         f"Could not update PreStage {pid} scope.\n\nRetry?"):
                        continue
                    print(f"[WARN] Skipped updating PreStage {pid}.")
                    break

        if RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY)

    if touched:
        print(f"[INFO] Updated PreStages: {', '.join(map(str, touched))}")
    else:
        print("[INFO] No scope updates were necessary.")

    # If candidates existed but we didn’t modify any, warn the operator
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
        print(f"[DRY RUN] Would DELETE Jamf computer-inventory ID {computer_id} (v2).")
        return True

    def _do_del(path: str):
        return jamf_client.pro_api_request(
            method="DELETE",
            resource_path=path,
            override_headers={"Accept": "application/json"}
        )

    path_v2 = f"v2/computers-inventory/{computer_id}"

    # Try v2 first
    try:
        r = _do_del(path_v2)
        if r.status_code in (200, 204):
            print(f"[SUCCESS] Deleted Jamf computer-inventory ID {computer_id} (v2).")
            return True
        if r.status_code == 404:
            print(f"[INFO] Computer {computer_id} not found on v2; treating as already deleted.")
            return True
        print(f"[WARN] v2 delete returned {r.status_code}; verifying…")
    except Exception as e:
        sc = getattr(getattr(e, "response", None), "status_code", None)
        print(f"[WARN] v2 delete raised {sc or 'exception'}; verifying…")

    # Verify state after error/exception (handles “500 but actually deleted”)
    time.sleep(0.75)
    if _verify_inventory_gone(jamf_client, computer_id):
        print(f"[SUCCESS] Computer {computer_id} is gone (verified after error).")
        return True

    # Optional v1 fallback
    try:
        print("[INFO] Falling back to v1 delete once…")
        r2 = _do_del(f"v1/computers-inventory/{computer_id}")
        if r2.status_code in (200, 204, 404):
            print(f"[SUCCESS] Deleted (or already gone) ID {computer_id} via v1.")
            return True
        try: detail = r2.json()
        except Exception: detail = r2.text
        print(f"[ERROR] JAMF: v1 delete failed ({r2.status_code}): {detail}")
    except Exception as e:
        sc = getattr(getattr(e, "response", None), "status_code", None)
        if sc == 404:
            print(f"[SUCCESS] Already gone on v1 (404) for ID {computer_id}.")
            return True
        print(f"[ERROR] JAMF: v1 delete request failed: {e}")

    return False

# ==============================
# Entry point for Consisterizer
# ==============================
def jamf_remove_prestage_and_delete(asset_tag: str) -> str:
    """
    High-level workflow:
      - Resolve serial from Snipe-IT.
      - Initialize Jamf client.
      - Locate Jamf computer by serial.
      - Remove from all candidate PreStages (with verification).
      - Optionally delete (with post-error verification and fallback).
    """
    if not asset_tag:
        return "[ERROR] No asset tag provided."

    print(f"\n=== Jamf Remove-from-PreStage + Delete ===")
    print(f"Asset Tag: {asset_tag}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")

    serial = _get_serial_from_snipe(asset_tag)
    if not serial:
        return f"[ERROR] SNIPE: No serial for asset {asset_tag}."
    print(f"[INFO] Serial: {serial}")

    try:
        print("[INFO] Initializing Jamf Pro client…")
        jamf_client = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5),
        )
        print("[SUCCESS] Jamf client ready.")
    except Exception as e:
        return f"[ERROR] JAMF: Client init failed: {e}"

    comp = _find_jamf_computer_by_serial(jamf_client, serial)
    if not comp:
        return f"[ERROR] JAMF: No computer with serial {serial}."
    cid, cname = comp["id"], comp["name"]
    print(f"[INFO] Target: {cname} (ID {cid})")

    seen, modified, candidates = _remove_from_all_prestages(jamf_client, serial, cid)
    print(f"[INFO] PreStages seen: {seen}, modified: {modified}, candidates: {candidates}")

    if not DELETE_AFTER_REMOVE:
        return (f"{'[DRY RUN] ' if DRY_RUN else ''}"
                f"Removed {serial} from {modified}/{seen} PreStage(s)"
                f"{'' if candidates == seen else f' (candidates={candidates})'}; "
                f"SKIPPED delete (toggle).")

    if STRICT_REMOVAL_GUARD and candidates > 0 and modified < candidates:
        msg = (f"Skipped delete: PreStage removal incomplete "
               f"({modified}/{candidates}).\n\n"
               "Delete is guarded to prevent orphaned PreStage assignments.")
        _warn("Deletion skipped (safe-guard)", msg)
        return (f"[SAFEGUARD] Skipped delete; PreStage removal incomplete "
                f"({modified}/{candidates} updated).")

    # Deletion with retry prompt
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
        print(jamf_remove_prestage_and_delete(TEST_ASSET_TAG))
    else:
        print("[INFO] Set TEST_ASSET_TAG to try a manual run.")
