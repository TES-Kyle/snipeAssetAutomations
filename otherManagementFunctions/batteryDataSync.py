#!/usr/bin/env python3
# jamf2snipe - Battery Data Sync (EA-only, minimal + honest values)

import re
import time
from utilities import Key
from requests import Session, adapters
from urllib3.util import Retry

from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider


# ---------------- CONFIG ----------------

JAMF_URL = Key.jamfURL
JAMF_CLIENT_ID = Key.jamfClientID
JAMF_CLIENT_SECRET = Key.jamfClientSecret

SNIPE_URL = Key.API_URL_Base
SNIPE_API_KEY = Key.API_Key

SNIPE_CUSTOM_FIELD_KEY = "_snipeit_batterydata_8"

# Script behavior
DRY_RUN = False
VERIFY_SSL = True
RATE_LIMIT_DELAY = 0.2
TEST_MODE_SERIAL = ""   # e.g. "C02VW123ABCD" → live update only this serial; others dry-run

# EA names (case-insensitive) — these are the only source we trust
EA_NAME_DESIGN = "Battery Design Capacity"
EA_NAME_MAX    = "Battery Maximum Capacity"
EA_NAME_COND   = "batteryCondition"

# --- DEBUG controls ---
DEBUG_VERBOSE = False
DEBUG_ONLY_FIRST_N = None  # 0 or None to process all
DEBUG_SHOW_EA_VALUES = False

# ---------------------------------------

if not SNIPE_URL.startswith(("http://", "https://")):
    SNIPE_URL = f"https://{SNIPE_URL}"
SNIPE_URL = SNIPE_URL.rstrip("/")

snipe_session = Session()
snipe_retries = Retry(total=3, backoff_factor=0.8, status_forcelist=[500, 502, 503, 504])
snipe_session.mount("https://", adapters.HTTPAdapter(max_retries=snipe_retries))
snipe_headers = {
    "Authorization": f"Bearer {SNIPE_API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


# -------------- UTILITIES ----------------

def _rate():
    if RATE_LIMIT_DELAY > 0:
        time.sleep(RATE_LIMIT_DELAY)

def _preview(value, max_keys=12):
    try:
        if isinstance(value, dict):
            keys = list(value.keys())
            tail = "" if len(keys) <= max_keys else f"... (+{len(keys)-max_keys})"
            return f"<dict len={len(value)} keys={keys[:max_keys]}{tail}>"
        if isinstance(value, list):
            return f"<list len={len(value)}>"
        return f"<{type(value).__name__}: {str(value)[:120]!r}>"
    except Exception:
        return f"<{type(value).__name__}>"

def _ea_name(e):
    if hasattr(e, "name"):
        try:
            return str(getattr(e, "name")).strip()
        except Exception:
            return None
    if isinstance(e, dict) and "name" in e:
        return str(e["name"]).strip()
    return None

def _ea_value(e):
    """
    Unwrap Jamf EA value variants and normalize empty strings → None.
    """
    # .value (may be dict or SDK wrapper)
    if hasattr(e, "value"):
        v = getattr(e, "value")
        if isinstance(v, dict):
            for k in ("value", "displayValue", "rawValue"):
                if v.get(k) not in (None, ""):
                    return v[k]
            return None
        for attr in ("value", "stringValue", "numberValue", "displayValue", "rawValue"):
            if hasattr(v, attr):
                try:
                    got = getattr(v, attr)
                    if got not in (None, ""):
                        return got
                except Exception:
                    pass
        if v not in (None, "", []):
            return v

    # dict EA
    if isinstance(e, dict):
        if "value" in e:
            v = e["value"]
            if isinstance(v, dict):
                for k in ("value", "displayValue", "rawValue"):
                    if v.get(k) not in (None, ""):
                        return v[k]
                return None
            if v not in (None, "", []):
                return v
        if "values" in e and isinstance(e["values"], list):
            for item in e["values"]:
                if item not in (None, "", []):
                    return item

    # attributes directly on EA entry
    for attr in ("values", "stringValue", "numberValue", "displayValue", "rawValue"):
        if hasattr(e, attr):
            try:
                got = getattr(e, attr)
                if isinstance(got, list):
                    for item in got:
                        if item not in (None, "", []):
                            return item
                elif got not in (None, "", []):
                    return got
            except Exception:
                pass
    return None

def _collect_ea_map(comp, debug_label):
    """
    Build a lowercased {name: value} map from the few EA containers we’ve actually seen:
      - comp.extensionAttributes
      - comp.hardware.extensionAttributes
      - comp.__dict__['extensionAttributes'] (SDK quirk)
    """
    containers = []
    src_labels = []

    c1 = getattr(comp, "extensionAttributes", None)
    if c1: containers.append(c1); src_labels.append("comp.extensionAttributes")

    hw = getattr(comp, "hardware", None)
    if hw is not None:
        h1 = getattr(hw, "extensionAttributes", None)
        if h1: containers.append(h1); src_labels.append("comp.hardware.extensionAttributes")

    if hasattr(comp, "__dict__") and comp.__dict__.get("extensionAttributes"):
        containers.append(comp.__dict__["extensionAttributes"])
        src_labels.append("comp.__dict__['extensionAttributes']")

    ea_map = {}
    debug_names = []

    def coerce_list(x):
        if isinstance(x, list):
            return x
        if isinstance(x, dict):  # {name: value}
            return [{"name": k, "value": v} for k, v in x.items()]
        return []

    for cont in containers:
        for e in coerce_list(cont):
            nm = _ea_name(e)
            if not nm:
                continue
            val = _ea_value(e)
            if isinstance(val, str) and val.strip() == "":
                val = None
            ea_map[nm.lower()] = val
            debug_names.append(nm)

    if DEBUG_VERBOSE:
        print(f"    [DEBUG] EA probe for {debug_label}: merged from {src_labels} (total {len(debug_names)} names)")
        if DEBUG_SHOW_EA_VALUES:
            for k in (EA_NAME_DESIGN.lower(), EA_NAME_MAX.lower(), EA_NAME_COND.lower()):
                print(f"             - {k}: {_preview(ea_map.get(k))}")

    return ea_map

def _extract_number(raw):
    """
    Extract the first numeric token (int or float) from a string like '4562 mAh' or '4,562'.
    No unit conversion is performed.
    """
    if raw is None:
        return None
    s = str(raw)
    # Remove thousands separators/spaces
    s = re.sub(r"[,\s]+", "", s)
    m = re.search(r"(-?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def normalize_condition(cond_raw):
    c = (cond_raw or "").strip()
    if not c:
        return "N/A"
    lc = c.lower()
    mapping = {
        "normal": "Normal",
        "good": "Normal",
        "service recommended": "Service Recommended",
        "replace soon": "Replace Soon",
        "replace now": "Replace Now",
        "fair": "Fair",
        "poor": "Poor",
    }
    return mapping.get(lc, c)

def _format_three_sig_pct(pct_float):
    """
    Render percentage with exactly THREE significant digits (no scientific notation),
    matching examples: 105%, 99.1%, 9.76%, 0.987%, etc.
    """
    p = float(pct_float)
    if p >= 100:
        # 100–999 → 3 digits (no decimals). If >999, we'll still show full digits (rare).
        return f"{p:.0f}"
    elif p >= 10:
        # 10–99.9 → 1 decimal
        return f"{p:.1f}"
    elif p >= 1:
        # 1–9.99 → 2 decimals
        return f"{p:.2f}"
    else:
        # <1 → 3 decimals (still three significant digits for typical values)
        # Avoid scientific notation by forcing fixed-point.
        return f"{p:.3f}".rstrip('0').rstrip('.') if p != 0 else "0"

def build_battery_string(design_raw, max_raw, cond_raw):
    """
    - Never use Jamf's direct percent; compute only from (max/design).
    - If either numeric piece missing → percent 'N/A'.
    - Condition defaults/normalizes; 'N/A' if missing.
    - Return final string + is_valid flag (upload if either percent or condition is present).
    """
    design = _extract_number(design_raw)
    maxcap = _extract_number(max_raw)
    cond = normalize_condition(cond_raw)

    percent_str = "N/A"
    if design and maxcap and design != 0:
        pct = (maxcap / design) * 100.0
        percent_str = f"{_format_three_sig_pct(pct)}%"

    final = f"{percent_str} - {cond}"
    is_valid = (percent_str != "N/A") or (cond != "N/A")
    return final, is_valid


# -------------- SNIPE HELPERS ----------------

def search_snipe_asset_by_serial(serial: str):
    _rate()
    url = f"{SNIPE_URL}/hardware/byserial/{serial}"
    try:
        resp = snipe_session.get(url, headers=snipe_headers, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        if data.get("total") == 1:
            return data["rows"][0]
        elif data.get("total") == 0:
            print(f"  [INFO] No Snipe asset for S/N: {serial}")
        else:
            print(f"  [WARN] {data.get('total')} Snipe matches for S/N {serial}. Skipping.")
    except Exception as e:
        print(f"  [ERROR] Snipe search failed for {serial}: {e}")
    return None

def update_snipe_custom_field(asset_id: int, value: str):
    _rate()
    url = f"{SNIPE_URL}/hardware/{asset_id}"
    payload = {SNIPE_CUSTOM_FIELD_KEY: value}
    try:
        resp = snipe_session.patch(url, headers=snipe_headers, json=payload, verify=VERIFY_SSL)
        resp.raise_for_status()
        print(f"  [SUCCESS] Updated Snipe asset {asset_id} {SNIPE_CUSTOM_FIELD_KEY} = '{value}'")
        return True
    except Exception as e:
        print(f"  [ERROR] Failed updating Snipe asset {asset_id}: {e}")
        return False


# -------------- MAIN ----------------

def run_jamf_battery_sync():
    if DRY_RUN and not TEST_MODE_SERIAL:
        print("--- DRY RUN: No Snipe updates will be made. ---")
    elif TEST_MODE_SERIAL:
        print(f"--- TEST MODE: Only serial '{TEST_MODE_SERIAL}' will be updated live. ---")
    else:
        print("--- LIVE MODE: Snipe updates will be applied. ---")

    # Init Jamf client
    try:
        print("[INFO] Initializing Jamf Pro client...")
        jamf = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5),
        )
        print("[SUCCESS] Jamf client ready.")
    except Exception as e:
        print(f"[FATAL] Could not initialize Jamf client: {e}")
        return

    wanted_sections = ["GENERAL", "HARDWARE", "EXTENSION_ATTRIBUTES"]
    try:
        print(f"[INFO] Fetching Jamf computer inventory (sections={wanted_sections})...")
        computers = jamf.pro_api.get_computer_inventory_v1(
            sections=wanted_sections,
            page_size=1000
        )
        if not computers:
            print("[INFO] No computers found.")
            return
        print(f"[INFO] Retrieved {len(computers)} computers.")
    except Exception as e:
        print(f"[ERROR] Failed to fetch computers from Jamf: {e}")
        return

    processed = 0
    for comp in computers:
        comp_id = getattr(comp, "id", None)
        general = getattr(comp, "general", None)
        hardware = getattr(comp, "hardware", None)

        name = getattr(general, "name", None) if general else None
        serial = getattr(hardware, "serialNumber", None) if hardware else None

        label = name or f"ID:{comp_id}"
        print(f"-> Processing {label} (ID: {comp_id}, S/N: {serial})")

        if not serial:
            print("  [INFO] No serial; skipping.")
            continue

        # EA map (only known, reliable containers)
        ea_map = _collect_ea_map(comp, debug_label=f"{label} / {serial}")

        design_raw = ea_map.get(EA_NAME_DESIGN.lower())
        max_raw    = ea_map.get(EA_NAME_MAX.lower())
        cond_raw   = ea_map.get(EA_NAME_COND.lower())

        if DEBUG_VERBOSE:
            print(f"    [DEBUG] matched EA values: design={_preview(design_raw)}, max={_preview(max_raw)}, condition={_preview(cond_raw)}")

        final_string, is_valid = build_battery_string(design_raw, max_raw, cond_raw)
        print(f"  [DEBUG] final_string → {final_string!r}")

        # Skip only when BOTH are N/A (percent==N/A and condition==N/A)
        if not is_valid:
            print("  [SKIP] Both percent and condition are N/A; not updating Snipe.")
            processed += 1
            if DEBUG_ONLY_FIRST_N and processed >= DEBUG_ONLY_FIRST_N:
                print(f"[DEBUG] Stopping early after {DEBUG_ONLY_FIRST_N} devices (DEBUG_ONLY_FIRST_N).")
                break
            continue

        # Link to Snipe asset
        snipe_asset = search_snipe_asset_by_serial(serial)
        if not snipe_asset:
            processed += 1
            if DEBUG_ONLY_FIRST_N and processed >= DEBUG_ONLY_FIRST_N:
                print(f"[DEBUG] Stopping early after {DEBUG_ONLY_FIRST_N} devices (DEBUG_ONLY_FIRST_N).")
                break
            continue

        asset_id = snipe_asset.get("id")
        current_val = (snipe_asset.get("custom_fields") or {}).get(SNIPE_CUSTOM_FIELD_KEY)
        print(f"  [DEBUG] Snipe asset_id={asset_id}, current {SNIPE_CUSTOM_FIELD_KEY}={current_val!r}")

        # Update or dry-run
        if current_val == final_string:
            print("  [OK] Field already up-to-date.")
        else:
            if DRY_RUN and not TEST_MODE_SERIAL:
                print(f"  [DRY RUN] Would set {SNIPE_CUSTOM_FIELD_KEY}='{final_string}' on asset {asset_id}.")
            else:
                do_live = (serial == TEST_MODE_SERIAL) if TEST_MODE_SERIAL else True
                if do_live:
                    print(f"  [LIVE UPDATE] {SNIPE_CUSTOM_FIELD_KEY} -> '{final_string}'")
                    update_snipe_custom_field(asset_id, final_string)
                else:
                    print("  [SKIP] Not target serial for Test Mode.")

        processed += 1
        if DEBUG_ONLY_FIRST_N and processed >= DEBUG_ONLY_FIRST_N:
            print(f"[DEBUG] Stopping early after {DEBUG_ONLY_FIRST_N} devices (DEBUG_ONLY_FIRST_N).")
            break


if __name__ == "__main__":
    run_jamf_battery_sync()
