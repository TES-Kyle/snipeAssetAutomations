from utilities import Key
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

    # Asset Tag
    var_list.append(("Asset Tag", assetData.get("asset_tag", "null")))

    # Serial Number
    if assetData.get("serial"):
        var_list.append(("Serial Number", assetData["serial"]))

    # Asset Name
    if assetData.get("name"):
        var_list.append(("Asset Name", assetData["name"]))

    # Status
    status_label = assetData.get("status_label", {})
    if status_label.get("name"):
        var_list.append(("Status", status_label["name"]))

    # Assigned To
    assigned_to = assetData.get("assigned_to") or {}
    if assigned_to.get("name"):
        var_list.append(("Assigned to User", assigned_to["name"]))
    if assigned_to.get("email"):
        var_list.append(("Assigned to Email", assigned_to["email"]))

    # Custom Fields
    custom_fields = assetData.get("custom_fields", {})

    hinge_weak = custom_fields.get("hingeWeak", {}).get("value")
    if hinge_weak:
        var_list.append(("Hinge Weak?", hinge_weak))

    charger_good = custom_fields.get("chargerInGoodCondition", {}).get("value")
    if charger_good:
        var_list.append(("Charger in Good Condition?", charger_good))

    battery_data = custom_fields.get("batteryData", {}).get("value")
    if battery_data:
        var_list.append(("Battery Stats", battery_data))

    box_number = custom_fields.get("Box Number", {}).get("value")
    if box_number:
        var_list.append(("Box Number", box_number))

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

def getLatestCheckinName(asset_id, email=False, username=False):
    activity_url = Key.API_URL_Base + f'reports/activity?limit=1&offset=0&item_type=asset&item_id={asset_id}&action_type=checkin%20from&order=desc&sort=created_at'
    activity_response = requests.get(activity_url, headers=headers)
    activity_data = activity_response.json()
    try:
        if email:
            user_url = Key.API_URL_Base + f"users/{activity_data['rows'][0]['target']['id']}"
            user_response = requests.get(user_url, headers=headers)
            user_data = user_response.json()
            return user_data['email']
        elif username:
            user_url = Key.API_URL_Base + f"users/{activity_data['rows'][0]['target']['id']}"
            user_response = requests.get(user_url, headers=headers)
            user_data = user_response.json()
            return user_data['username']
        else:
            return activity_data['rows'][0]['target']['name']
    except (KeyError, IndexError):
        return None


def _get_paged(url: str, headers: dict, limit: int = 500, extra_params: str = ""):
    """Yield all rows from a paginated Snipe-IT endpoint."""
    base = Key.API_URL_Base.rstrip("/")
    offset = 0
    rows_all = []
    while True:
        try:
            sep = "&" if "?" in url else "?"
            page_url = f"{base}{url}{sep}limit={limit}&offset={offset}"
            if extra_params:
                page_url += f"&{extra_params.lstrip('&')}"
            r = requests.get(page_url, headers=headers, timeout=20)
            data = r.json()
            rows = data.get("rows") or data.get("data") or []
        except Exception:
            break
        rows_all.extend(rows)
        if len(rows) < limit:
            break
        offset += limit
    return rows_all

def getAllStatusOptions():
    """
    All asset status labels as:
      {"label": <status name>, "id": <status id>, "meta": {...}}
    """
    # /api/v1/statuslabels?type=asset is the endpoint
    rows = _get_paged("/statuslabels", headers, extra_params="type=asset")
    out = []
    for st in rows:
        out.append({
            "label": (st.get("name") or "").strip(),
            "id": st.get("id"),
            "meta": st,
        })
    # unique & sorted
    seen, uniq = set(), []
    for o in out:
        if o["id"] in seen:
            continue
        seen.add(o["id"])
        uniq.append(o)
    return sorted(uniq, key=lambda o: o["label"].lower())

def getAllAssigneeOptions():
    """
    Unified list of users + locations:
      {"label": str, "id": int, "type": "user"|"location",
       "username": str, "email": str, "meta": dict}
    """
    users = _get_paged("/users", headers)
    locs  = _get_paged("/locations", headers)

    out = []
    for u in users:
        label = (u.get("name") or u.get("username") or "").strip()
        out.append({
            "label": label,
            "id": u.get("id"),
            "type": "user",
            "username": (u.get("username") or "").strip(),
            "email": (u.get("email") or "").strip(),
            "meta": u,
        })
    for l in locs:
        out.append({
            "label": (l.get("name") or "").strip(),
            "id": l.get("id"),
            "type": "location",
            "username": "",
            "email": "",
            "meta": l,
        })

    # unique by (type,id) & sorted
    seen, uniq = set(), []
    for o in out:
        k = (o["type"], o["id"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    return sorted(uniq, key=lambda o: o["label"].lower())

def getAllModelOptions():
    """
    All asset models as:
      {"label": <model name>, "id": <model id>, "meta": {...}}
    """
    rows = _get_paged("/models", headers)
    out = []
    for m in rows:
        out.append({
            "label": (m.get("name") or "").strip(),
            "id": m.get("id"),
            "meta": m,
        })
    # unique by id & sorted by label
    seen, uniq = set(), []
    for o in out:
        if o["id"] in seen:
            continue
        seen.add(o["id"])
        uniq.append(o)
    return sorted(uniq, key=lambda o: o["label"].lower())
