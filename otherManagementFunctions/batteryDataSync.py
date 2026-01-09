#!/usr/bin/env python3
"""Sync Jamf battery EAs into Snipe-IT custom fields.

This script pulls battery-related EAs from Jamf inventory, normalizes
the values, and writes a summarized string to a custom field in Snipe-IT.
"""

# jamf2snipe - Battery Data Sync (EA-only, minimal + honest values)

import logging
import re
import time

from requests import Session, adapters
from urllib3.util import Retry

from utilities import Key
from utilities.api_user import get_api_headers
from utilities.logging_utils import configure_logging, get_settings

from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider

logger = logging.getLogger(__name__)


# ---------------- CONFIG ----------------

JAMF_URL = Key.jamfURL
JAMF_CLIENT_ID = Key.jamfClientID
JAMF_CLIENT_SECRET = Key.jamfClientSecret

SNIPE_URL = Key.API_URL_Base

SNIPE_CUSTOM_FIELD_KEY_DEFAULT = "_snipeit_batterydata_8"
SNIPE_CUSTOM_FIELD_KEY = SNIPE_CUSTOM_FIELD_KEY_DEFAULT

# Script behavior
DRY_RUN = False
VERIFY_SSL = True
RATE_LIMIT_DELAY = 0.2
TEST_MODE_SERIAL = ""   # e.g. "C02VW123ABCD" → live update only this serial; others dry-run

# EA names (case-insensitive) — these are the only source we trust
EA_NAME_DESIGN_DEFAULT = "Battery Design Capacity"
EA_NAME_MAX_DEFAULT = "Battery Maximum Capacity"
EA_NAME_COND_DEFAULT = "batteryCondition"
EA_NAME_DESIGN = EA_NAME_DESIGN_DEFAULT
EA_NAME_MAX = EA_NAME_MAX_DEFAULT
EA_NAME_COND = EA_NAME_COND_DEFAULT

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
def _snipe_headers():
    """Build Snipe-IT headers using the active API user."""
    return get_api_headers()


# -------------- UTILITIES ----------------

def _rate():
    """Sleep to honor the configured rate limit delay."""
    # Apply a simple sleep-based throttle between requests.
    if RATE_LIMIT_DELAY > 0:
        time.sleep(RATE_LIMIT_DELAY)

def _preview(value, max_keys=12):
    """Return a short string preview for logging complex values."""
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
    """Extract a name string from a Jamf EA object or dict."""
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
        """Normalize EA containers to a list of dict-like items."""
        if isinstance(x, list):
            return x
        if isinstance(x, dict):  # {name: value}
            return [{"name": k, "value": v} for k, v in x.items()]
        return []

    for cont in containers:
        # Extract only non-empty EA values and normalize names to lowercase.
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
        logger.debug(
            "EA probe for %s: merged from %s (total %s names)",
            debug_label,
            src_labels,
            len(debug_names),
        )
        if DEBUG_SHOW_EA_VALUES:
            for k in (EA_NAME_DESIGN.lower(), EA_NAME_MAX.lower(), EA_NAME_COND.lower()):
                logger.debug("%s: %s", k, _preview(ea_map.get(k)))

    return ea_map

def _extract_number(raw):
    """
    Extract the first numeric token (int or float) from a string like '4562 mAh' or '4,562'.
    No unit conversion is performed.
    """
    if raw is None:
        return None
    s = str(raw)
    # Remove thousands separators/spaces.
    s = re.sub(r"[,\s]+", "", s)
    m = re.search(r"(-?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def normalize_condition(cond_raw):
    """Normalize battery condition strings to standard labels."""
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
    """Lookup a single Snipe-IT asset by serial number."""
    _rate()
    url = f"{SNIPE_URL}/hardware/byserial/{serial}"
    try:
        # Query Snipe-IT for an exact serial match.
        resp = snipe_session.get(url, headers=_snipe_headers(), verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        if data.get("total") == 1:
            return data["rows"][0]
        elif data.get("total") == 0:
            logger.info("No Snipe asset for S/N: %s", serial)
        else:
            logger.warning(
                "%s Snipe matches for S/N %s. Skipping.",
                data.get("total"),
                serial,
            )
    except Exception as e:
        logger.error("Snipe search failed for %s: %s", serial, e)
    return None

def update_snipe_custom_field(asset_id: int, value: str):
    """Patch the Snipe-IT battery field for an asset."""
    _rate()
    url = f"{SNIPE_URL}/hardware/{asset_id}"
    payload = {SNIPE_CUSTOM_FIELD_KEY: value}
    try:
        # Patch the custom field value on the asset record.
        resp = snipe_session.patch(url, headers=_snipe_headers(), json=payload, verify=VERIFY_SSL)
        resp.raise_for_status()
        logger.info(
            "Updated Snipe asset %s %s = '%s'",
            asset_id,
            SNIPE_CUSTOM_FIELD_KEY,
            value,
        )
        return True
    except Exception as e:
        logger.error("Failed updating Snipe asset %s: %s", asset_id, e)
        return False


# -------------- MAIN ----------------

def run_jamf_battery_sync():
    """Execute the full Jamf-to-Snipe battery sync workflow."""
    configure_logging()
    settings = get_settings()
    global SNIPE_CUSTOM_FIELD_KEY, EA_NAME_DESIGN, EA_NAME_MAX, EA_NAME_COND
    global DRY_RUN, VERIFY_SSL, RATE_LIMIT_DELAY, TEST_MODE_SERIAL
    global DEBUG_VERBOSE, DEBUG_ONLY_FIRST_N, DEBUG_SHOW_EA_VALUES

    def _to_bool(val, default=False):
        """Convert common truthy/falsy values to bool with a default."""
        raw = str(val if val is not None else "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
        return default

    # Apply settings overrides for runtime behavior and debug flags.
    DRY_RUN = _to_bool(settings.get("batterySyncDryRun", DRY_RUN), DRY_RUN)
    VERIFY_SSL = _to_bool(settings.get("batterySyncVerifySSL", VERIFY_SSL), VERIFY_SSL)
    try:
        RATE_LIMIT_DELAY = float(settings.get("batterySyncRateLimitDelay", RATE_LIMIT_DELAY))
    except Exception:
        RATE_LIMIT_DELAY = RATE_LIMIT_DELAY
    TEST_MODE_SERIAL = (settings.get("batterySyncTestSerial", TEST_MODE_SERIAL) or "").strip()
    DEBUG_VERBOSE = _to_bool(settings.get("batterySyncDebugVerbose", DEBUG_VERBOSE), DEBUG_VERBOSE)
    DEBUG_SHOW_EA_VALUES = _to_bool(
        settings.get("batterySyncDebugShowEaValues", DEBUG_SHOW_EA_VALUES),
        DEBUG_SHOW_EA_VALUES,
    )
    raw_debug_first = str(settings.get("batterySyncDebugOnlyFirstN", "")).strip()
    if raw_debug_first:
        try:
            DEBUG_ONLY_FIRST_N = int(raw_debug_first)
        except Exception:
            DEBUG_ONLY_FIRST_N = None
    else:
        DEBUG_ONLY_FIRST_N = None
    SNIPE_CUSTOM_FIELD_KEY = settings.get("batteryDataFieldKey", SNIPE_CUSTOM_FIELD_KEY_DEFAULT)
    EA_NAME_DESIGN = settings.get("batteryEaNameDesign", EA_NAME_DESIGN_DEFAULT)
    EA_NAME_MAX = settings.get("batteryEaNameMax", EA_NAME_MAX_DEFAULT)
    EA_NAME_COND = settings.get("batteryEaNameCond", EA_NAME_COND_DEFAULT)
    logger.info(
        "Battery sync settings: dry_run=%s verify_ssl=%s rate_limit=%s test_serial=%s debug_verbose=%s debug_only_first_n=%s",
        DRY_RUN,
        VERIFY_SSL,
        RATE_LIMIT_DELAY,
        TEST_MODE_SERIAL,
        DEBUG_VERBOSE,
        DEBUG_ONLY_FIRST_N,
    )
    logger.info("Battery sync using field key: %s", SNIPE_CUSTOM_FIELD_KEY)
    if DRY_RUN and not TEST_MODE_SERIAL:
        logger.info("DRY RUN: No Snipe updates will be made.")
    elif TEST_MODE_SERIAL:
        logger.info("TEST MODE: Only serial '%s' will be updated live.", TEST_MODE_SERIAL)
    else:
        logger.info("LIVE MODE: Snipe updates will be applied.")

    # Init Jamf client.
    try:
        logger.info("Initializing Jamf Pro client...")
        jamf = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5),
        )
        logger.info("Jamf client ready.")
    except Exception as e:
        logger.error("Could not initialize Jamf client: %s", e)
        return

    # Fetch Jamf inventory with the sections required for EAs.
    wanted_sections = ["GENERAL", "HARDWARE", "EXTENSION_ATTRIBUTES"]
    try:
        logger.info("Fetching Jamf computer inventory (sections=%s)...", wanted_sections)
        computers = jamf.pro_api.get_computer_inventory_v1(
            sections=wanted_sections,
            page_size=1000
        )
        if not computers:
            logger.info("No computers found.")
            return
        logger.info("Retrieved %s computers.", len(computers))
    except Exception as e:
        logger.error("Failed to fetch computers from Jamf: %s", e)
        return

    processed = 0
    for comp in computers:
        # Extract identifying metadata for logs and lookups.
        comp_id = getattr(comp, "id", None)
        general = getattr(comp, "general", None)
        hardware = getattr(comp, "hardware", None)

        name = getattr(general, "name", None) if general else None
        serial = getattr(hardware, "serialNumber", None) if hardware else None

        label = name or f"ID:{comp_id}"
        logger.info("Processing %s (ID: %s, S/N: %s)", label, comp_id, serial)

        if not serial:
            logger.info("No serial; skipping.")
            continue

        # EA map (only known, reliable containers).
        ea_map = _collect_ea_map(comp, debug_label=f"{label} / {serial}")

        design_raw = ea_map.get(EA_NAME_DESIGN.lower())
        max_raw    = ea_map.get(EA_NAME_MAX.lower())
        cond_raw   = ea_map.get(EA_NAME_COND.lower())

        if DEBUG_VERBOSE:
            logger.debug(
                "matched EA values: design=%s, max=%s, condition=%s",
                _preview(design_raw),
                _preview(max_raw),
                _preview(cond_raw),
            )

        final_string, is_valid = build_battery_string(design_raw, max_raw, cond_raw)
        logger.debug("final_string -> %r", final_string)

        # Skip only when BOTH are N/A (percent==N/A and condition==N/A).
        if not is_valid:
            logger.info("Both percent and condition are N/A; not updating Snipe.")
            processed += 1
            if DEBUG_ONLY_FIRST_N and processed >= DEBUG_ONLY_FIRST_N:
                logger.debug(
                    "Stopping early after %s devices (DEBUG_ONLY_FIRST_N).",
                    DEBUG_ONLY_FIRST_N,
                )
                break
            continue

        # Link to Snipe asset.
        snipe_asset = search_snipe_asset_by_serial(serial)
        if not snipe_asset:
            processed += 1
            if DEBUG_ONLY_FIRST_N and processed >= DEBUG_ONLY_FIRST_N:
                logger.debug(
                    "Stopping early after %s devices (DEBUG_ONLY_FIRST_N).",
                    DEBUG_ONLY_FIRST_N,
                )
                break
            continue

        asset_id = snipe_asset.get("id")
        current_val = (snipe_asset.get("custom_fields") or {}).get(SNIPE_CUSTOM_FIELD_KEY)
        logger.debug(
            "Snipe asset_id=%s, current %s=%r",
            asset_id,
            SNIPE_CUSTOM_FIELD_KEY,
            current_val,
        )

        # Update or dry-run based on current settings.
        if current_val == final_string:
            logger.info("Field already up-to-date.")
        else:
            if DRY_RUN and not TEST_MODE_SERIAL:
                logger.info(
                    "DRY RUN: Would set %s='%s' on asset %s.",
                    SNIPE_CUSTOM_FIELD_KEY,
                    final_string,
                    asset_id,
                )
            else:
                do_live = (serial == TEST_MODE_SERIAL) if TEST_MODE_SERIAL else True
                if do_live:
                    logger.info(
                        "LIVE UPDATE: %s -> '%s'",
                        SNIPE_CUSTOM_FIELD_KEY,
                        final_string,
                    )
                    update_snipe_custom_field(asset_id, final_string)
                else:
                    logger.info("Not target serial for Test Mode.")

        processed += 1
        if DEBUG_ONLY_FIRST_N and processed >= DEBUG_ONLY_FIRST_N:
            logger.debug(
                "Stopping early after %s devices (DEBUG_ONLY_FIRST_N).",
                DEBUG_ONLY_FIRST_N,
            )
            break


if __name__ == "__main__":
    configure_logging(log_to_console=True)
    run_jamf_battery_sync()
