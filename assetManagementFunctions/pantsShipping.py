from Utilities.otherApiBits import *


def pantsShipping(asset_tag, *args):
    junk, genericValues = getAssetInfo(asset_tag)

    putURL = Key.API_URL_Base + "hardware/" + str(genericValues["id"])
    print(putURL)
    payload1 = {
        "status_id": genericValues["status_label"]["id"]
    }
    payload2 = {
        "asset_tag": asset_tag,
        "model_id": genericValues["model"]["id"],
        "status_id": 9,
    }
    response = requests.post(putURL + "/checkin", json=payload1, headers=headers)
    print(response.text)
    response2 = requests.put(putURL, json=payload2, headers=headers)
    print(response2.text)
    junk, genericValues = getAssetInfo(asset_tag)
    # printData = [genericValues["asset_tag"], genericValues["status_label"]["name"], genericValues["name"]]

    # createImage(printData)

    return f"Running func5 on {asset_tag}"
