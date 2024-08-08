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
    # API URL of Snipe-IT Server -- this one includes the specific API call of listing hardware info by asset tag
    url = Key.API_URL_Base + "hardware/bytag/"

    # Makes API request, combines Asset Tag that was passed through the function into the URL -- requires requests header
    response = requests.get(url + assetTag, headers=headers)
    # Loads the response in text format into a readable format -- requires import json header
    assetData = json.loads(response.text)
    # Returns the parsed JSON data back to where the function was called
    var_list = []

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
