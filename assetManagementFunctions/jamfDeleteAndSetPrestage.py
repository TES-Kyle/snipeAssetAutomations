#!/usr/bin/env python3
"""
Remove from other PreStages, add to a selected PreStage, and delete Jamf record.
"""

import logging

from utilities.logging_utils import configure_logging
from utilities.jamfPrestageCommon import (
    _confirm_action,
    _add_serial_to_prestage,
    _find_jamf_computer_by_serial,
    _get_prestage_list,
    _get_serial_from_snipe,
    _prompt_prestage_choice,
    _remove_from_all_prestages,
    _warn,
    create_jamf_client,
    delete_computer_with_retry,
    get_prestage_settings,
)

logger = logging.getLogger(__name__)


def jamf_delete_and_set_prestage(asset_tag: str) -> str:
    """Remove from other PreStages, add to selected PreStage, and delete record.

    Args:
        asset_tag: Snipe-IT asset tag to process.

    Returns:
        Status message string describing the outcome.
    """
    logger.debug("jamf_delete_and_set_prestage: asset_tag=%s", asset_tag)
    if not asset_tag:
        return "[ERROR] No asset tag provided."

    configure_logging()
    settings = get_prestage_settings()
    logger.debug("jamf_delete_and_set_prestage: settings loaded dry_run=%s", settings.get("dry_run"))

    if not _confirm_action(
        "Confirm Jamf Delete",
        "This will update PreStage assignments and delete the Jamf record.\n\nContinue?",
    ):
        logger.info("jamf_delete_and_set_prestage: user cancelled action for %s", asset_tag)
        return "Cancelled."

    logger.info("=== Jamf Delete + Set PreStage ===")
    logger.info("Asset Tag: %s", asset_tag)
    logger.info("Mode: %s", "DRY RUN" if settings["dry_run"] else "LIVE")

    serial = _get_serial_from_snipe(asset_tag)
    if not serial:
        return f"[ERROR] SNIPE: No serial for asset {asset_tag}."
    logger.info("Serial: %s", serial)

    try:
        logger.info("Initializing Jamf Pro client...")
        jamf_client = create_jamf_client(settings)
        logger.info("Jamf client ready.")
    except Exception as e:
        return f"[ERROR] JAMF: Client init failed: {e}"

    logger.debug("jamf_delete_and_set_prestage: fetching prestage list")
    prestages = _get_prestage_list(jamf_client, settings)
    if not prestages:
        logger.error("jamf_delete_and_set_prestage: no prestages returned for %s", asset_tag)
        return "[ERROR] JAMF: No PreStages returned."
    logger.debug("jamf_delete_and_set_prestage: %s prestages available", len(prestages))

    choice = _prompt_prestage_choice(prestages)
    if not choice:
        logger.info("jamf_delete_and_set_prestage: prestage selection cancelled for %s", asset_tag)
        return "PreStage selection cancelled."

    target_id = int(choice["id"])
    target_name = choice.get("name") or f"PreStage {target_id}"
    logger.info("Target PreStage: %s (ID %s)", target_name, target_id)

    logger.debug("jamf_delete_and_set_prestage: searching for Jamf computer by serial=%s", serial)
    comp = _find_jamf_computer_by_serial(jamf_client, serial, settings)
    cid = comp["id"] if comp else None
    cname = comp["name"] if comp else None
    if comp:
        logger.info("Target computer: %s (ID %s)", cname, cid)
    else:
        logger.warning("No Jamf computer inventory record found for serial %s.", serial)

    logger.info("jamf_delete_and_set_prestage: removing serial=%s from all prestages except target_id=%s", serial, target_id)
    seen, modified, candidates = _remove_from_all_prestages(
        jamf_client,
        serial,
        settings,
        skip_ids={target_id},
    )
    logger.info("PreStages seen: %s, modified: %s, candidates: %s", seen, modified, candidates)

    if settings["strict_removal_guard"] and candidates > 0 and modified < candidates:
        msg = (f"Skipped PreStage set: removal incomplete "
               f"({modified}/{candidates}).\n\n"
               "Fix PreStage scope conflicts first, then retry.")
        _warn("PreStage removal incomplete", msg)
        return (f"[SAFEGUARD] Skipped set/delete; PreStage removal incomplete "
                f"({modified}/{candidates} updated).")

    logger.info("jamf_delete_and_set_prestage: adding serial=%s to prestage=%s (ID %s)", serial, target_name, target_id)
    if not _add_serial_to_prestage(jamf_client, target_id, serial, settings):
        logger.error("jamf_delete_and_set_prestage: failed to add serial=%s to prestage ID %s", serial, target_id)
        _warn("PreStage add failed",
              f"Could not add serial to PreStage {target_name} (ID {target_id}).")
        return f"[ERROR] JAMF: Failed to add to PreStage {target_name} (ID {target_id})."

    if cid is None:
        logger.info("jamf_delete_and_set_prestage: no Jamf record to delete for serial=%s", serial)
        return f"Set PreStage to {target_name} (ID {target_id}); no Jamf record to delete."

    if not settings["delete_after_remove"]:
        logger.info("jamf_delete_and_set_prestage: delete_after_remove=False; skipping delete for cid=%s", cid)
        return (f"Set PreStage to {target_name} (ID {target_id}); "
                f"SKIPPED delete (setting).")

    return delete_computer_with_retry(
        jamf_client, cid, cname, settings,
        success_message=(f"Set PreStage to {target_name} (ID {target_id}); "
                          f"deleted Jamf computer-inventory ID {cid}."),
        failure_warn_message=f"PreStage set succeeded, but deletion failed for ID {cid}.",
    )


if __name__ == "__main__":
    TEST_ASSET_TAG = "5703"
    if TEST_ASSET_TAG:
        configure_logging(log_to_console=True)
        logger.info(jamf_delete_and_set_prestage(TEST_ASSET_TAG))
    else:
        configure_logging(log_to_console=True)
        logger.info("Set TEST_ASSET_TAG to try a manual run.")
