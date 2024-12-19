import requests
import json
import os
from datetime import datetime
from Utilities.otherApiBits import getAssetInfoSerialAssignedTo
from Utilities.otherApiBits import getAssetInfo
from jamf_pro_sdk import JamfProClient, SessionConfig
from jamf_pro_sdk.clients.auth import ApiClientCredentialsProvider
from jamf_pro_sdk.clients.pro_api.pagination import FilterField, SortField
from Utilities import Key  # Import credentials from the key.py file

# Configuration - replace these with your own details
JAMF_URL = "https://trinityes.jamfcloud.com"  # No trailing slash
jamfURL = "trinityes.jamfcloud.com"

BEARER_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdXRoZW50aWNhdGVkLWFwcCI6IkdFTkVSSUMiLCJhdXRoZW50aWNhdGlvbi10eXBlIjoiTERBUCIsImdyb3VwcyI6W10sInN1YmplY3QtdHlwZSI6IkpTU19VU0VSX0lEIiwidG9rZW4tdXVpZCI6IjIzNzA4YTc0LWVlZjYtNDE4ZS05MGU2LTIwZWFlMGEyNTM3YiIsImxkYXAtc2VydmVyLWlkIjotMSwic3ViIjoiMTEiLCJleHAiOjE3MzQ1MzQzOTZ9.bWE2u5os8P3FIYYWYn_m8P_xfKTN-4_FoZKFOPHtQMk"  # Ideally, fetch from environment or use a token generation process

# The extension attribute that holds charger serial info
CHARGER_EA_NAME = "chargerSerial"

# The charger serial number we are looking for
#TARGET_CHARGER_SERIAL = "C4H31930BPBLV74AQ"  # Example from your snippet
assetTag = "6245"


def get_computer_inventory_results():
    """
    Fetches a set of computer inventory records from Jamf Pro using the Jamf Pro SDK.
    Adjust pagination parameters if needed.
    """
    jamfClient = JamfProClient(
        server=jamfURL,
        credentials=ApiClientCredentialsProvider(Key.jamfClientID, Key.jamfClientSecret),
        session_config=SessionConfig(
            **{"timeout": 30, "max_retries": 5, "max_concurrency": 25}
        ),
    )

    response = jamfClient.pro_api.get_computer_inventory_v1(
        sections=["HARDWARE"],
        page_size=700,  # Adjust as needed
        sort_expression=SortField("general.name").asc()
    )

    # response.results should now be a list of Computer objects
    return response


def parse_charger_info(values_str):
    entries = []
    lines = values_str.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Split into date/time parts and charger serial
        parts = line.rsplit(maxsplit=1)
        if len(parts) != 2:
            continue
        date_part = parts[0]
        charger_serial = parts[1]

        tokens = date_part.split()
        # If we have 6 tokens, assume the 5th is a timezone and remove it
        if len(tokens) == 6:
            tokens.pop(4)

        # Zero-pad the day if needed
        day = tokens[2]
        if len(day) == 1:
            day = f"0{day}"
            tokens[2] = day

        date_str = " ".join(tokens)
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %Y")

        entries.append((dt, charger_serial))
    return entries


def chargerSerial(assetTag):
    computers = get_computer_inventory_results()

    junk, assetInfo = getAssetInfo(assetTag)
    TARGET_CHARGER_SERIAL = assetInfo["serial"]
    print(f"Charger Serial = {TARGET_CHARGER_SERIAL}")

    charger_matches = []
    for comp in computers:
        hardware = comp.hardware
        #print(f"{hardware}")
        if not hardware:
            continue
        comp_serial = hardware.serialNumber or "UNKNOWN"
        #print(f"{comp_serial}")
        
        # hardware.extension_attributes is a list of ComputerExtensionAttribute objects
        if hardware.extensionAttributes:
            for ea in hardware.extensionAttributes:
                if ea.name == CHARGER_EA_NAME:
                    values = ea.values or []
                    if not values:
                        continue
                    all_values_str = "\n".join(values)
                    entries = parse_charger_info(all_values_str)
                    for (dt, cserial) in entries:
                        if cserial == TARGET_CHARGER_SERIAL:
                            assignedTo = getAssetInfoSerialAssignedTo(comp_serial)
                            charger_matches.append((dt, comp_serial, assignedTo))

    # Sort by datetime descending
    charger_matches.sort(key=lambda x: x[0], reverse=True)

    # Print the 5 most recent matches
    print(f"5 Most Recent Uses of Charger {TARGET_CHARGER_SERIAL}:")
    for dt, dev_serial, assigned in charger_matches[:5]:
        print(f"{dt} - Device Serial: {dev_serial} - Assigned To: {assigned}")
    
    return f"Running Check Charger on {assetTag}"