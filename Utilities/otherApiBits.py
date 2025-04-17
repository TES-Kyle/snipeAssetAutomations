from Utilities import Key
import requests
import json


# API Key which can be created in your SnipeIT Account, place it inbetween quotes as one line
# REF: https://snipe-it.readme.io/reference/generating-api-tokens
token = Key.API_Key

# Headers used in the request library to pass the authorization bearer token
headers = {
    "accept": "application/json",
    "Authorization": "Bearer " + token,
    "content-type": "application/json"
}


def getAssetInfo(assetTag):
    """
    Retrieves asset information from the Snipe-IT server based on the provided asset tag.
    Args:
        assetTag (str): The asset tag of the hardware to retrieve information for.
    Returns:
        tuple: A tuple containing:
            - var_list (list): A list of tuples with asset information in the format (key, value).
            - assetData (dict): The raw JSON response from the API containing detailed asset information.
    Notes:
        - The function makes an API request to the Snipe-IT server to retrieve hardware information.
        - The response is parsed and specific fields are extracted and added to var_list.
        - The function checks for the presence of various fields in the response and handles missing fields appropriately.
    """
    # API URL of Snipe-IT Server -- this one includes the specific API call of listing hardware info by asset tag
    url = Key.API_URL_Base + "hardware/bytag/"

    # Makes API request, combines Asset Tag that was passed through the function into the URL -- requires requests header
    response = requests.get(url + assetTag, headers=headers)
    # Loads the response in text format into a readable format -- requires import json header
    assetData = json.loads(response.text)
    # Returns the parsed JSON data back to where the function was called
    var_list = []

    print(f"Asset Data: {assetData}")

    if "asset_tag" in assetData:
        var_list.append(("Asset Tag", assetData["asset_tag"]))
    else:
        var_list.append(("Asset Tag", "null"))
    if "serial" in assetData:
        var_list.append(("Serial Number", assetData["serial"]))
    if "name" in assetData:
        var_list.append(("Asset Name", assetData["name"]))
    if "status_label" in assetData and "name" in assetData["status_label"]:
        var_list.append(("Status", assetData["status_label"]["name"]))
    if (
            "custom_fields" in assetData
            and "hingeWeak" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["hingeWeak"]
            and len(assetData["custom_fields"]["hingeWeak"]["value"]) != 0
    ):
        var_list.append(("Hinge Weak?", assetData["custom_fields"]["hingeWeak"]["value"]))
    if (
            "custom_fields" in assetData
            and "chargerInGoodCondition" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["chargerInGoodCondition"]
            and len(assetData["custom_fields"]["chargerInGoodCondition"]["value"]) != 0
    ):
        var_list.append(("Charger in Good Condition?", assetData["custom_fields"]["chargerInGoodCondition"]["value"]))
    if (
            "custom_fields" in assetData
            and "batteryData" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["batteryData"]
            and len(assetData["custom_fields"]["batteryData"]["value"]) != 0
    ):
        var_list.append(("Battery Stats", assetData["custom_fields"]["batteryData"]["value"]))
    if (
            "custom_fields" in assetData
            and "Box Number" in assetData["custom_fields"]
            and "value" in assetData["custom_fields"]["Box Number"]
            and len(assetData["custom_fields"]["Box Number"]["value"]) != 0
    ):
        var_list.append(("Box Number", assetData["custom_fields"]["Box Number"]["value"]))

    return var_list, assetData

def getAssetInfoSerialAssignedTo(serialNum):
    url = Key.API_URL_Base + "hardware/byserial/"
    response = requests.get(url + serialNum, headers=headers)
    assetData = json.loads(response.text)
    
    # Safely navigate through the nested structure
    rows = assetData.get("rows")
    if rows and len(rows) > 0:
        assigned_to = rows[0].get("assigned_to")
        if assigned_to and "name" in assigned_to:
            return assigned_to["name"]
    
    # If we get here, it means something wasn't present
    return None

