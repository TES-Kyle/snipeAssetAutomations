from assetManagementFunctions.printSelected import printSelected
from assetManagementFunctions.newRepair import newRepair
from assetManagementFunctions.pantsShipping import pantsShipping
from assetManagementFunctions.backFromApple import backFromApple
from assetManagementFunctions.dropOff import dropOff
from assetManagementFunctions.makeCharger import makeCharger
from assetManagementFunctions.chargerSerial import show_charger_results_tk
from assetManagementFunctions.checkoutTo import checkoutTo
from assetManagementFunctions.checkIn import checkIn
from consisterizer.consisterizer import consisterizer
from consisterizer.aliases import bulkCheckIn



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
             lambda x: consisterizer(x, alias=bulkCheckIn)
             ]
func_listTXT = ["Print Selected",
                "New Repair",
                "Pants Shipping",
                "Back from Apple",
                "Drop-Off",
                "Make charger",
                "Check Charger History",
                "Checkout",
                "Check In",
                "Consisterizer",
                "Bulk Check-in"
                ]
