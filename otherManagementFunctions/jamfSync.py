#!/usr/bin/env python3
"""Sync asset tags between Snipe-IT and Jamf Pro.

Pulls asset tags from Snipe-IT and updates Jamf inventory when mismatches
are detected, honoring dry-run and test-mode settings.
"""

# snipe2jamf - Simple Asset Tag Sync (Hybrid SDK Version)
#
# ABOUT:
#   A simplified, single-file script to pull asset tags from Snipe-IT
#   and update assets in Jamf Pro. It uses the modern Jamf Pro SDK for reading
#   and the SDK's classic request method for reliable updates.

import logging
import time

from requests import Session, adapters
from urllib3.util import Retry

from utilities import Key
from utilities.api_user import get_api_headers
from utilities.logging_utils import configure_logging, get_settings

# Import necessary components from the Jamf Pro SDK
from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Your API details are imported from the utilities.Key module.

# Jamf Pro API Details
# IMPORTANT: Key.jamfURL should be the hostname ONLY, without https://
# e.g., "your-instance.jamfcloud.com"
JAMF_URL = Key.jamfURL
JAMF_CLIENT_ID = Key.jamfClientID
JAMF_CLIENT_SECRET = Key.jamfClientSecret

# Snipe-IT API Details
# IMPORTANT: Key.API_URL_Base should be the full base path to the API.
# e.g., "https://your-instance.snipe-it.io/api/v1"
SNIPE_URL = Key.API_URL_Base

# --- URL VALIDATION (for https:// scheme only) ---
if not SNIPE_URL.startswith(('http://', 'https://')):
    SNIPE_URL = f'https://{SNIPE_URL}'
SNIPE_URL = SNIPE_URL.rstrip('/')
# --- END URL VALIDATION ---

# Script Options
SYNC_COMPUTERS = True
SYNC_MOBILES = True
DRY_RUN = False
VERIFY_SSL = True
RATE_LIMIT_DELAY = 0.5

# --- Test Mode ---
TEST_MODE_SERIAL = ""  # Example: "LTY2R3KM7X"

# --- END OF CONFIGURATION ---


# --- API Sessions ---
# Session for Snipe-IT
snipe_session = Session()
snipe_retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
snipe_session.mount('https://', adapters.HTTPAdapter(max_retries=snipe_retries))
def _snipe_headers():
    """Build Snipe-IT headers using the active API user."""
    return get_api_headers(content_type=None, accept="application/json")


# --- API Functions ---
def search_snipe_asset_by_serial(serial):
    """Look up a Snipe-IT asset by serial number.

    Args:
        serial: Device serial number to query in Snipe-IT.

    Returns:
        Asset dict when exactly one match is found; otherwise None.
    """
    if RATE_LIMIT_DELAY > 0:
        time.sleep(RATE_LIMIT_DELAY)
    api_url = f'{SNIPE_URL}/hardware/byserial/{serial}'
    try:
        # Query Snipe-IT for a single serial match.
        response = snipe_session.get(api_url, headers=_snipe_headers(), verify=VERIFY_SSL)
        response.raise_for_status()
        data = response.json()
        if data.get('total') == 1:
            return data['rows'][0]
        elif data.get('total') == 0:
            logger.info("No match found in Snipe-IT for S/N: %s", serial)
        else:
            logger.warning(
                "Multiple (%s) matches in Snipe-IT for S/N: %s. Skipping.",
                data.get("total"),
                serial,
            )
    except Exception as e:
        logger.error("Error searching Snipe-IT for S/N %s: %s", serial, e)
    return None


def update_jamf_asset_tag(jamf_client, device_id, new_asset_tag, endpoint):
    """Update an asset tag in Jamf Pro using the Pro API (computers/mobiles).

    Args:
        jamf_client: Authenticated JamfProClient object.
        device_id: Jamf Pro device ID.
        new_asset_tag: New asset tag value to set.
        endpoint: Either "computers" or "mobiledevices".
    """
    try:
        logger.info("Updating Jamf %s ID %s via Pro API...", endpoint[:-1], device_id)

        # Pick correct endpoint + payload for the device type.
        if endpoint == "computers":
            resource_path = f"/v2/computers-inventory-detail/{device_id}"
            payload = {"general": {"assetTag": new_asset_tag}}

        elif endpoint == "mobiledevices":
            resource_path = f"/v2/mobile-devices/{device_id}"
            payload = {"assetTag": new_asset_tag}

        else:
            raise ValueError(f"Unknown endpoint type: {endpoint}")

        # Use pro_api_request to send PATCH.
        response = jamf_client.pro_api_request(
            method="PATCH",
            resource_path=resource_path,
            data=payload,
            override_headers={"Accept": "application/json"}
        )
        response.raise_for_status()

        logger.info(
            "Asset tag updated to '%s' for Jamf %s ID %s.",
            new_asset_tag,
            endpoint[:-1],
            device_id,
        )

    except Exception as e:
        logger.error("Failed to update Jamf %s ID %s: %s", endpoint[:-1], device_id, e)



# --- Main Sync Logic ---
def process_devices(jamf_client, endpoint):
    """Main function to process a list of devices using the Jamf Pro SDK."""
    logger.info("Starting processing for Jamf %s", endpoint.capitalize())

    try:
        if endpoint == 'computers':
            logger.info("Fetching all computer records from Jamf...")
            all_devices = jamf_client.pro_api.get_computer_inventory_v1(
                sections=["GENERAL", "HARDWARE"],
                page_size=1000
            )
        else:
            logger.info("Fetching all mobile device records from Jamf...")
            all_devices = jamf_client.pro_api.get_mobile_device_inventory_v2(
                sections=["GENERAL", "HARDWARE"],
                page_size=1000
            )
    except Exception as e:
        logger.error("Failed to fetch %s from Jamf: %s", endpoint, e)
        return

    if not all_devices:
        logger.info("No %s found in Jamf to process.", endpoint)
        return

    logger.info("Found %s total %s in Jamf.", len(all_devices), endpoint)
    for device in all_devices:
        # Normalize fields across computer/mobile record types.
        if endpoint == 'computers':
            device_id = device.id
            serial = device.hardware.serialNumber if device.hardware else None
            device_name = device.general.name if device.general else f"ID: {device_id}"
            current_jamf_tag = device.general.assetTag
        else:  # mobiledevices
            device_id = device.mobileDeviceId
            serial = device.hardware.serialNumber if device.hardware else None
            device_name = device.general.displayName if device.general else f"ID: {device_id}"
            current_jamf_tag = device.general.assetTag

        if not serial:
            logger.info("Skipping %s (ID: %s): no serial number found.", device_name, device_id)
            continue

        logger.info("Processing %s (S/N: %s)", device_name, serial)

        # Resolve asset tag in Snipe-IT before deciding on updates.
        snipe_asset = search_snipe_asset_by_serial(serial)
        if not snipe_asset:
            continue

        snipe_asset_tag = snipe_asset.get('asset_tag')
        if not snipe_asset_tag:
            logger.info("Snipe-IT asset for S/N %s has no asset tag. Skipping.", serial)
            continue

        if snipe_asset_tag != current_jamf_tag:
            logger.warning(
                "MISMATCH: Jamf tag is '%s', Snipe-IT is '%s'.",
                current_jamf_tag,
                snipe_asset_tag,
            )

            # Determine if this run is allowed to update Jamf.
            is_live_update = False
            if TEST_MODE_SERIAL and serial == TEST_MODE_SERIAL:
                is_live_update = True
                logger.info("TEST MODE: Device matches test serial. Performing live update.")
            elif not DRY_RUN and not TEST_MODE_SERIAL:
                is_live_update = True

            if is_live_update:
                update_jamf_asset_tag(jamf_client, device_id, snipe_asset_tag, endpoint)
            else:
                logger.info(
                    "DRY RUN: Would update %s ID %s with asset tag '%s'.",
                    endpoint[:-1],
                    device_id,
                    snipe_asset_tag,
                )
        else:
            logger.info("Tags match ('%s'). No update needed.", snipe_asset_tag)



def run_snipe_to_jamf_sync():
    """Run the full Snipe-to-Jamf sync process.

    Loads settings, initializes API clients, iterates Jamf inventory,
    and updates asset tags when mismatches are found.
    """
    configure_logging()
    settings = get_settings()
    global SYNC_COMPUTERS, SYNC_MOBILES, DRY_RUN, VERIFY_SSL, RATE_LIMIT_DELAY, TEST_MODE_SERIAL

    def _to_bool(val, default=False):
        """Convert common truthy/falsy values to bool with a default."""
        raw = str(val if val is not None else "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
        return default

    # Apply runtime settings overrides.
    SYNC_COMPUTERS = _to_bool(settings.get("jamfSyncSyncComputers", SYNC_COMPUTERS), SYNC_COMPUTERS)
    SYNC_MOBILES = _to_bool(settings.get("jamfSyncSyncMobiles", SYNC_MOBILES), SYNC_MOBILES)
    DRY_RUN = _to_bool(settings.get("jamfSyncDryRun", DRY_RUN), DRY_RUN)
    VERIFY_SSL = _to_bool(settings.get("jamfSyncVerifySSL", VERIFY_SSL), VERIFY_SSL)
    try:
        RATE_LIMIT_DELAY = float(settings.get("jamfSyncRateLimitDelay", RATE_LIMIT_DELAY))
    except Exception:
        RATE_LIMIT_DELAY = RATE_LIMIT_DELAY
    TEST_MODE_SERIAL = (settings.get("jamfSyncTestSerial", TEST_MODE_SERIAL) or "").strip()

    logger.info(
        "Jamf sync settings: dry_run=%s verify_ssl=%s rate_limit=%s sync_computers=%s sync_mobiles=%s test_serial=%s",
        DRY_RUN,
        VERIFY_SSL,
        RATE_LIMIT_DELAY,
        SYNC_COMPUTERS,
        SYNC_MOBILES,
        TEST_MODE_SERIAL,
    )
    if DRY_RUN and not TEST_MODE_SERIAL:
        logger.info("SCRIPT IS IN DRY RUN MODE. NO CHANGES WILL BE MADE.")
    elif TEST_MODE_SERIAL:
        logger.info(
            "SCRIPT IS IN TEST MODE. LIVE CHANGES WILL ONLY AFFECT S/N: %s",
            TEST_MODE_SERIAL,
        )
    else:
        logger.info("SCRIPT IS IN LIVE MODE. CHANGES WILL BE APPLIED.")

    try:
        # Initialize the Jamf client using the configured credentials.
        logger.info("Initializing Jamf Pro client...")
        jamf_client = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5)
        )
        logger.info("Jamf Pro client initialized.")
    except Exception as e:
        logger.error("Could not initialize Jamf Pro client: %s", e)
        return

    if SYNC_COMPUTERS:
        process_devices(jamf_client, 'computers')
    if SYNC_MOBILES:
        process_devices(jamf_client, 'mobiledevices')

    logger.info("Sync complete.")


def quick_update_test():
    """Initializes a Jamf client and runs a single update for testing."""
    configure_logging()
    logger.info("RUNNING QUICK UPDATE TEST")

    # --- DEFINE YOUR TEST DATA HERE ---
    test_device_id = 2955
    test_device_type = "computer"  # Can be "computer" or "mobiledevice"
    test_asset_tag = "6529"
    # ------------------------------------

    # 1. Initialize the client
    try:
        logger.info("Initializing Jamf Pro client for test...")
        jamf_client = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5)
        )
        logger.info("Jamf Pro client initialized for test.")
    except Exception as e:
        logger.error("Could not initialize Jamf Pro client for test: %s", e)
        return

    # 2. Run the update
    endpoint = 'computers' if test_device_type == 'computer' else 'mobiledevices'
    update_jamf_asset_tag(jamf_client, test_device_id, test_asset_tag, endpoint)

    logger.info("Quick Update Test Complete.")


# --- Script Execution ---
if __name__ == "__main__":
    # To run a quick test on ONLY the update function, set this to True.
    # To run the full sync script, set this to False.
    RUN_QUICK_TEST = False

    if RUN_QUICK_TEST:
        configure_logging(log_to_console=True)
        quick_update_test()
    else:
        configure_logging(log_to_console=True)
        run_snipe_to_jamf_sync()
