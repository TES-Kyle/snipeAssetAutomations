# Handler
from otherManagementFunctions.scriptSplitOutHandler import handler

# Scripts
from consisterizer.scripts.jamfDeleteAndPreStage import jamf_remove_prestage_and_delete

submit_func_list = [
    jamf_remove_prestage_and_delete
]

submit_func_listTXT = [
    "Remove PreStage and Delete in Jamf"
]