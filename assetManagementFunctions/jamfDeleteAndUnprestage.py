#!/usr/bin/env python3
"""
Delete a Jamf computer record after removing it from all PreStages.
"""

import logging

from utilities.logging_utils import configure_logging
from utilities.jamfPrestageCommon import (
    _confirm_action,
    _ask_retry_cancel,
    _delete_computer_pro,
    _find_jamf_computer_by_serial,
    _get_serial_from_snipe,
    _remove_from_all_prestages,
    _warn,
    create_jamf_client,
    get_prestage_settings,
)

logger = logging.getLogger(__name__)


def jamf_remove_prestage_and_delete(asset_tag: str) -> str:
    """Remove a device from all PreStage scopes and delete its Jamf record.

    Args:
        asset_tag: Snipe-IT asset tag to process.

    Returns:
        Status message string describing the outcome.
    """
    logger.debug("jamf_remove_prestage_and_delete: asset_tag=%s", asset_tag)
    if not asset_tag:
        return "[ERROR] No asset tag provided."

    configure_logging()
    settings = get_prestage_settings()
    logger.debug("jamf_remove_prestage_and_delete: settings loaded dry_run=%s delete_after_remove=%s", settings.get("dry_run"), settings.get("delete_after_remove"))

    if not _confirm_action(
        "Confirm Jamf Delete",
        "This will remove the device from all Jamf PreStages and delete its Jamf record.\n\nContinue?",
    ):
        logger.info("jamf_remove_prestage_and_delete: user cancelled for %s", asset_tag)
        return "Cancelled."

    logger.info("=== Jamf Remove-from-PreStage + Delete ===")
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
        logger.exception("jamf_remove_prestage_and_delete: Jamf client init failed for %s", asset_tag)
        return f"[ERROR] JAMF: Client init failed: {e}"

    logger.debug("jamf_remove_prestage_and_delete: searching for Jamf computer by serial=%s", serial)
    comp = _find_jamf_computer_by_serial(jamf_client, serial, settings)
    cid = comp["id"] if comp else None
    cname = comp["name"] if comp else None
    if comp:
        logger.info("Target: %s (ID %s)", cname, cid)
    else:
        logger.warning("No Jamf computer inventory record found for serial %s.", serial)

    logger.info("jamf_remove_prestage_and_delete: removing serial=%s from all prestages", serial)
    seen, modified, candidates = _remove_from_all_prestages(jamf_client, serial, settings)
    logger.info("PreStages seen: %s, modified: %s, candidates: %s", seen, modified, candidates)

    if not settings["delete_after_remove"]:
        logger.info("jamf_remove_prestage_and_delete: delete_after_remove=False; skipping delete")
        return (f"{'[DRY RUN] ' if settings['dry_run'] else ''}"
                f"Removed {serial} from {modified}/{seen} PreStage(s)"
                f"{'' if candidates == seen else f' (candidates={candidates})'}; "
                f"SKIPPED delete (setting).")

    if settings["strict_removal_guard"] and candidates > 0 and modified < candidates:
        logger.warning("jamf_remove_prestage_and_delete: removal incomplete (%s/%s); safeguard skipping delete", modified, candidates)
        msg = (f"Skipped delete: PreStage removal incomplete "
               f"({modified}/{candidates}).\n\n"
               "Delete is guarded to prevent orphaned PreStage assignments.")
        _warn("Deletion skipped (safe-guard)", msg)
        return (f"[SAFEGUARD] Skipped delete; PreStage removal incomplete "
                f"({modified}/{candidates} updated).")

    if cid is None:
        logger.info("jamf_remove_prestage_and_delete: no Jamf record to delete for serial=%s", serial)
        return (f"Removed {serial} from {modified}/{seen} PreStage(s); "
                "no Jamf record to delete.")

    while True:
        logger.info("jamf_remove_prestage_and_delete: attempting to delete Jamf computer ID %s", cid)
        deleted_ok = _delete_computer_pro(jamf_client, cid, settings)
        if deleted_ok:
            logger.info("jamf_remove_prestage_and_delete: successfully deleted Jamf computer ID %s", cid)
            return f"Deleted Jamf computer-inventory ID {cid}."
        logger.error("jamf_remove_prestage_and_delete: delete failed for Jamf computer ID %s", cid)
        if _ask_retry_cancel("Jamf delete failed",
                             f"Could not delete Jamf computer ID {cid}.\n\nRetry?"):
            logger.debug("jamf_remove_prestage_and_delete: user chose retry for delete of ID %s", cid)
            continue
        _warn("Jamf delete failed",
              f"Removal from PreStages may have succeeded, but deletion failed for ID {cid}.")
        return f"[ERROR] JAMF: Delete failed for {cname} (ID {cid})."


if __name__ == "__main__":
    TEST_ASSET_TAG = "5703"
    if TEST_ASSET_TAG:
        configure_logging(log_to_console=True)
        logger.info(jamf_remove_prestage_and_delete(TEST_ASSET_TAG))
    else:
        configure_logging(log_to_console=True)
        logger.info("Set TEST_ASSET_TAG to try a manual run.")
