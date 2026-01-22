"""Routing table for asset management functions.

Defines the list of callable asset actions and their display labels
for the main GUI.
"""

from assetManagementFunctions.printSelected import printSelected
from assetManagementFunctions.newRepair import newRepair
from assetManagementFunctions.pantsShipping import pantsShipping
from assetManagementFunctions.backFromApple import backFromApple
from assetManagementFunctions.dropOff import dropOff
from assetManagementFunctions.makeCharger import makeCharger
from assetManagementFunctions.chargerSerial import show_charger_results_tk
from assetManagementFunctions.checkoutTo import checkoutTo
from assetManagementFunctions.checkIn import checkIn
from assetManagementFunctions.jamfDeleteAndUnprestage import jamf_remove_prestage_and_delete
from assetManagementFunctions.jamfDeleteAndSetPrestage import jamf_delete_and_set_prestage

# Consisterizer actions.
from consisterizer.consisterizer import consisterizer
from consisterizer.aliases import bulkCheckIn


# Function callables in display order (must align with labels below).
func_list = [printSelected,
             newRepair,
             pantsShipping,
             backFromApple,
             dropOff,
             makeCharger,
             show_charger_results_tk,
             checkoutTo,
             checkIn,
             consisterizer,
             # Consisterizer alias entry for bulk check-in presets.
             lambda x: consisterizer(x, alias=bulkCheckIn),
             jamf_remove_prestage_and_delete,
             jamf_delete_and_set_prestage,
             ]
# Display names aligned with func_list.
func_listTXT = ["Print Selected",
                "New Repair",
                "Pants Shipping",
                "Back from Apple",
                "Drop-Off",
                "Make Charger",
                "Check Charger History",
                "Checkout",
                "Check In",
                "Consisterizer",
                "Bulk Check-in",
                "Delete & Un-Prestage Jamf",
                "Delete & Set PreStage Jamf",
                ]
