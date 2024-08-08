from Utilities.otherApiBits import *
from Utilities.labelPrinting import createImage


def printSelected(asset_tag, *args):
    if args:
        printVar = args[0]
        print(printVar)
        print(args)
        createImage(printVar)
        return f"Running func3 on {asset_tag}, printing parameters {printVar}"
    else:
        print("No Args")
        junk, genericValues = getAssetInfo(asset_tag)
        printData = list()
        printData.append(genericValues["asset_tag"])
        createImage(printData)
        return f"Running func3 on {asset_tag} with generic args"