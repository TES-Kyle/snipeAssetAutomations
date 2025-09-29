#!/usr/bin/env python3
# snipe2jamf - Simple Asset Tag Sync (Hybrid SDK Version)
#
# ABOUT:
#   A simplified, single-file script to pull asset tags from Snipe-IT
#   and update assets in Jamf Pro. It uses the modern Jamf Pro SDK for reading
#   and the SDK's classic request method for reliable updates.

import time
from Utilities import Key
from requests import Session, adapters
from urllib3.util import Retry

# Import necessary components from the Jamf Pro SDK
from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider

# --- CONFIGURATION ---
# Your API details are imported from the Utilities.Key module.

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
SNIPE_API_KEY = Key.API_Key

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
snipe_headers = {'Authorization': f'Bearer {SNIPE_API_KEY}', 'Accept': 'application/json'}


# --- API Functions ---
def search_snipe_asset_by_serial(serial):
    """Looks up an asset in Snipe-IT by its serial number."""
    if RATE_LIMIT_DELAY > 0:
        time.sleep(RATE_LIMIT_DELAY)
    api_url = f'{SNIPE_URL}/hardware/byserial/{serial}'
    try:
        response = snipe_session.get(api_url, headers=snipe_headers, verify=VERIFY_SSL)
        response.raise_for_status()
        data = response.json()
        if data.get('total') == 1:
            return data['rows'][0]
        elif data.get('total') == 0:
            print(f"  [INFO] No match found in Snipe-IT for S/N: {serial}")
        else:
            print(f"  [WARN] Multiple ({data.get('total')}) matches in Snipe-IT for S/N: {serial}. Skipping.")
    except Exception as e:
        print(f"  [ERROR] Error searching Snipe-IT for S/N {serial}: {e}")
    return None


def update_jamf_asset_tag(jamf_client, device_id, new_asset_tag, endpoint):
    """
    Update an asset tag in Jamf Pro using the Pro API (computers or mobile devices).

    Args:
        jamf_client: Authenticated JamfProClient object.
        device_id (int): Jamf Pro device ID.
        new_asset_tag (str): New asset tag value to set.
        endpoint (str): Either "computers" or "mobiledevices".
    """
    try:
        print(f"  [LIVE UPDATE] Updating Jamf {endpoint[:-1]} ID {device_id} via Pro API...")

        # Pick correct endpoint + payload
        if endpoint == "computers":
            resource_path = f"/v2/computers-inventory-detail/{device_id}"
            payload = {"general": {"assetTag": new_asset_tag}}

        elif endpoint == "mobiledevices":
            resource_path = f"/v2/mobile-devices/{device_id}"
            payload = {"assetTag": new_asset_tag}

        else:
            raise ValueError(f"Unknown endpoint type: {endpoint}")

        # Use pro_api_request to send PATCH
        response = jamf_client.pro_api_request(
            method="PATCH",
            resource_path=resource_path,
            data=payload,
            override_headers={"Accept": "application/json"}
        )
        response.raise_for_status()

        print(f"  [SUCCESS] Asset tag updated to '{new_asset_tag}' for Jamf {endpoint[:-1]} ID {device_id}.")

    except Exception as e:
        print(f"  [ERROR] Failed to update Jamf {endpoint[:-1]} ID {device_id}: {e}")



# --- Main Sync Logic ---
def process_devices(jamf_client, endpoint):
    """Main function to process a list of devices using the Jamf Pro SDK."""
    print(f"\n--- Starting processing for Jamf {endpoint.capitalize()} ---")

    try:
        if endpoint == 'computers':
            print("[INFO] Fetching all computer records from Jamf...")
            all_devices = jamf_client.pro_api.get_computer_inventory_v1(
                sections=["GENERAL", "HARDWARE"],
                page_size=1000
            )
        else:
            print("[INFO] Fetching all mobile device records from Jamf...")
            all_devices = jamf_client.pro_api.get_mobile_device_inventory_v2(
                sections=["GENERAL", "HARDWARE"],
                page_size=1000
            )
    except Exception as e:
        print(f"[ERROR] Failed to fetch {endpoint} from Jamf: {e}")
        return

    if not all_devices:
        print(f"No {endpoint} found in Jamf to process.")
        return

    print(f"Found {len(all_devices)} total {endpoint} in Jamf.")
    for device in all_devices:
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
            print(f"[INFO] Skipping {device_name} (ID: {device_id}): no serial number found.")
            continue

        print(f"-> Processing {device_name} (S/N: {serial})")

        snipe_asset = search_snipe_asset_by_serial(serial)
        if not snipe_asset:
            continue

        snipe_asset_tag = snipe_asset.get('asset_tag')
        if not snipe_asset_tag:
            print(f"  - Snipe-IT asset for S/N {serial} has no asset tag. Skipping.")
            continue

        if snipe_asset_tag != current_jamf_tag:
            print(f"  - MISMATCH: Jamf tag is '{current_jamf_tag}', Snipe-IT is '{snipe_asset_tag}'.")

            is_live_update = False
            if TEST_MODE_SERIAL and serial == TEST_MODE_SERIAL:
                is_live_update = True
                print(f"  [TEST MODE] This device matches the test serial. Performing live update.")
            elif not DRY_RUN and not TEST_MODE_SERIAL:
                is_live_update = True

            if is_live_update:
                update_jamf_asset_tag(jamf_client, device_id, snipe_asset_tag, endpoint)
            else:
                print(f"  [DRY RUN] Would update {endpoint[:-1]} ID {device_id} with asset tag '{snipe_asset_tag}'.")
        else:
            print(f"  - Tags match ('{snipe_asset_tag}'). No update needed.")



def run_snipe_to_jamf_sync():
    """The main callable function to run the entire sync process."""
    if DRY_RUN and not TEST_MODE_SERIAL:
        print("--- SCRIPT IS IN DRY RUN MODE. NO CHANGES WILL BE MADE. ---")
    elif TEST_MODE_SERIAL:
        print(f"--- SCRIPT IS IN TEST MODE. LIVE CHANGES WILL ONLY AFFECT S/N: {TEST_MODE_SERIAL} ---")
    else:
        print("--- SCRIPT IS IN LIVE MODE. CHANGES WILL BE APPLIED. ---")

    try:
        print("[INFO] Initializing Jamf Pro client...")
        jamf_client = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5)
        )
        print("[SUCCESS] Jamf Pro client initialized.")
    except Exception as e:
        print(f"[FATAL] Could not initialize Jamf Pro client: {e}")
        return

    if SYNC_COMPUTERS:
        process_devices(jamf_client, 'computers')
    if SYNC_MOBILES:
        process_devices(jamf_client, 'mobiledevices')

    print("\n--- Sync complete. ---")


def quick_update_test():
    """Initializes a Jamf client and runs a single update for testing."""
    print("--- RUNNING QUICK UPDATE TEST ---")

    # --- DEFINE YOUR TEST DATA HERE ---
    test_device_id = 2955
    test_device_type = "computer"  # Can be "computer" or "mobiledevice"
    test_asset_tag = "6529"
    # ------------------------------------

    # 1. Initialize the client
    try:
        print("[INFO] Initializing Jamf Pro client for test...")
        jamf_client = JamfProClient(
            server=JAMF_URL,
            credentials=ApiClientCredentialsProvider(JAMF_CLIENT_ID, JAMF_CLIENT_SECRET),
            session_config=SessionConfig(ssl_verify=VERIFY_SSL, max_retries=5)
        )
        print("[SUCCESS] Jamf Pro client initialized for test.")
    except Exception as e:
        print(f"[FATAL] Could not initialize Jamf Pro client for test: {e}")
        return

    # 2. Run the update
    endpoint = 'computers' if test_device_type == 'computer' else 'mobiledevices'
    update_jamf_asset_tag(jamf_client, test_device_id, test_asset_tag, endpoint)

    print("\n--- Quick Update Test Complete ---")


# --- Script Execution ---
if __name__ == "__main__":
    # To run a quick test on ONLY the update function, set this to True.
    # To run the full sync script, set this to False.
    RUN_QUICK_TEST = False

    if RUN_QUICK_TEST:
        quick_update_test()
    else:
        run_snipe_to_jamf_sync()