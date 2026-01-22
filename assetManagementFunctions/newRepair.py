"""Create a new repair workflow in Snipe-IT and notify users."""

import json
import logging
from datetime import date

import tkinter as tk
from tkinter import messagebox

from utilities.labelPrinting import createImage
from utilities.logging_utils import configure_logging, get_settings
from utilities.messaging import *
from utilities.otherApiBits import *

logger = logging.getLogger(__name__)

def newRepair(asset_tag):
    """Run the new repair workflow for an asset tag.

    Args:
        asset_tag: Asset tag to open a repair for.

    Returns:
        Status message string for the main UI.
    """
    configure_logging()
    logger.info("Starting new repair workflow for %s", asset_tag)
    # -------- helper: ask/retry wrappers --------
    def _resp_json(resp):
        """Safely parse JSON from a requests response."""
        try:
            return resp.json()
        except Exception:
            # Fall back to raw for display
            return {"raw": resp.text}

    def _is_success(resp):
        """Return True when the response is HTTP OK and not a Snipe error."""
        # HTTP OK and either no 'status' key or status != 'error'
        if not (200 <= resp.status_code < 300):
            return False
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("status") == "error":
                return False
        except Exception:
            # If not JSON but HTTP OK, treat as success
            pass
        return True

    def _do_with_retry(op_name, fn):
        """
        fn() should return a 'requests.Response' (or raise).
        On failure we show askretrycancel and loop if 'Retry'.
        Return the successful response JSON (or None if Cancel).
        """
        while True:
            try:
                # Execute the operation callable.
                resp = fn()
            except Exception as e:
                logger.exception("%s raised an exception", op_name)
                retry = messagebox.askretrycancel(
                    title=f"{op_name} failed",
                    message=f"{op_name} raised an exception:\n{type(e).__name__}: {e}\n\nRetry?"
                )
                if retry:
                    continue
                return None

            # Return on success; otherwise prompt for retry/cancel.
            if _is_success(resp):
                logger.info("%s succeeded", op_name)
                return _resp_json(resp)

            detail = _resp_json(resp)
            pretty = json.dumps(detail, indent=2, ensure_ascii=False)
            logger.error("%s failed (HTTP %s): %s", op_name, resp.status_code, detail)
            retry = messagebox.askretrycancel(
                title=f"{op_name} failed",
                message=(
                    f"HTTP {resp.status_code}\n"
                    f"Response:\n{pretty}\n\nRetry?"
                )
            )
            if retry:
                continue
            return None


    def _do_with_retry_or_skip(op_name, fn):
        """
        Like _do_with_retry, but on failure uses Yes/No/Cancel:
          Yes   -> Retry
          No    -> Skip this step (return {"__skipped__": True})
          Cancel-> Abort the whole flow (return None)
        """
        while True:
            try:
                # Execute the operation callable.
                resp = fn()
            except Exception as e:
                logger.exception("%s raised an exception", op_name)
                choice = messagebox.askyesnocancel(
                    title=f"{op_name} failed",
                    message=f"{op_name} raised {type(e).__name__}: {e}\n\nYes = Retry, No = Skip, Cancel = Abort"
                )
                if choice is True:  # Retry
                    continue
                elif choice is False:  # Skip
                    logger.warning("%s skipped by user", op_name)
                    return {"__skipped__": True}
                else:  # Cancel
                    return None

            # success?
            ok = (200 <= resp.status_code < 300)
            if ok:
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("status") == "error":
                        ok = False
                except Exception:
                    pass

            if ok:
                try:
                    return resp.json()
                except Exception:
                    return {"raw": resp.text}

            # not ok -> let user choose
            try:
                detail = resp.json()
            except Exception:
                detail = {"raw": resp.text}
            pretty = json.dumps(detail, indent=2, ensure_ascii=False)
            logger.error("%s failed (HTTP %s): %s", op_name, resp.status_code, detail)
            choice = messagebox.askyesnocancel(
                title=f"{op_name} failed (HTTP {resp.status_code})",
                message=f"Response:\n{pretty}\n\nYes = Retry, No = Skip, Cancel = Abort"
            )
            if choice is True:
                continue
            elif choice is False:
                logger.warning("%s skipped by user", op_name)
                return {"__skipped__": True}
            else:
                return None


    # ------------------ UI setup ------------------
    def submit_response():
        """Collect UI inputs and submit the repair workflow."""
        # Capture current values (so retries always use these).
        _title = title_entry.get().strip()
        _at_fault = 'Yes' if at_fault_var.get() == 1 else 'No'
        _issue = issue_entry.get("1.0", tk.END).strip()

        # Run the submission workflow; only close on full success.
        success = submitMaintenance(asset_tag, _at_fault, _issue, _title)
        if success:
            issue_window.destroy()

    def on_enter_pressed_in_issue_entry(event):
        """Handle Enter/Shift+Enter in the issue text box."""
        if event.state & 0x0001:  # Shift+Enter for newline
            issue_entry.insert(tk.INSERT, "\n")
        else:
            submit_response()

    def on_enter_pressed(event):
        """Move focus to the fault radio buttons."""
        at_fault_yes.focus_set()

    issue_window = tk.Toplevel()

    # Info Frame (current asset details).
    var_list, assetData = getAssetInfo(asset_tag)
    info_frame, _check_vars = build_asset_info_frame(
        issue_window, var_list, include_checkboxes=False, padx=5, pady=5
    )
    info_frame.grid(row=0, column=0, sticky='nsew')

    # Entry Frame (repair fields).
    entry_frame = tk.Frame(issue_window)
    entry_frame.grid(row=0, column=1, sticky='nsew')

    # Title input.
    title_frame = tk.Frame(entry_frame)
    title_frame.pack(fill='x', padx=10, pady=5)
    title_label = tk.Label(title_frame, text="Title:")
    title_label.pack(side='left')
    title_entry = tk.Entry(title_frame, width=50)
    title_entry.pack(side='left', expand=True, fill='x')
    title_entry.bind('<Return>', on_enter_pressed)
    title_entry.focus_set()

    # Fault selection.
    fault_frame = tk.Frame(entry_frame)
    fault_frame.pack(fill='x', padx=10, pady=5)
    at_fault_label = tk.Label(fault_frame, text="Is the user at fault?")
    at_fault_label.pack(side='left')
    at_fault_var = tk.IntVar(value=-1)
    at_fault_yes = tk.Radiobutton(fault_frame, text="Yes", variable=at_fault_var, value=1)
    at_fault_yes.pack(side='left')
    at_fault_no = tk.Radiobutton(fault_frame, text="No", variable=at_fault_var, value=0)
    at_fault_no.pack(side='left')

    # Email/text notification toggles.
    email_frame = tk.Frame(entry_frame)
    email_frame.pack(fill='x', padx=10, pady=5)
    email_label = tk.Label(email_frame, text="Send Emails")
    email_label.pack(side='left')
    email_var = tk.BooleanVar(value=False)
    email = tk.Checkbutton(email_frame, variable=email_var)
    email.pack(side='left')
    text_label = tk.Label(email_frame, text="Also Text Student?")
    text_label.pack(side='left')
    text_var = tk.BooleanVar(value=False)
    text = tk.Checkbutton(email_frame, variable=text_var)
    text.pack(side='left')
    parent_label = tk.Label(email_frame, text="Also Email Parents?")
    parent_label.pack(side='left')
    parent_var = tk.BooleanVar(value=True)
    parent = tk.Checkbutton(email_frame, variable=parent_var)
    parent.pack(side='left')

    # Issue description field.
    issue_frame = tk.Frame(entry_frame)
    issue_frame.pack(fill='x', padx=10, pady=5)
    issue_label = tk.Label(issue_frame, text="Please describe the issue:")
    issue_label.pack(side='left')
    issue_entry = tk.Text(issue_frame, height=5, width=40)
    issue_entry.pack(side='left', expand=True, fill='x')
    issue_entry.bind('<Return>', on_enter_pressed_in_issue_entry)

    # Submit button.
    submit_button = tk.Button(entry_frame, text="Submit", command=submit_response)
    submit_button.pack(pady=10)

    # Center window on screen.
    issue_window.update_idletasks()
    screen_width = issue_window.winfo_screenwidth()
    screen_height = issue_window.winfo_screenheight()
    window_width = issue_window.winfo_width()
    window_height = issue_window.winfo_height()
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))
    issue_window.geometry(f"+{center_x}+{center_y}")

    # ---------------- core submission flow ----------------
    def submitMaintenance(asset_tag, at_fault, issue_description, title):
        """Execute the repair workflow in Snipe-IT and messaging services."""
        junk, assetData = getAssetInfo(asset_tag)
        url = "https://trinityes.snipe-it.io/api/v1"

        # Decide effective email behavior up front (handles "no current assignee" case).
        want_email = bool(email_var.get())
        recipient_email = None
        full_name = None

        # Try the current assignee first.
        if want_email:
            assigned = assetData.get("assigned_to") or {}
            current_email = assigned.get("email")
            full_name = assigned.get("name")

            if current_email and is_email(current_email):
                recipient_email = current_email
            else:
                # No current assignee / invalid email → ask to use last user or turn off.
                last_email = getLatestCheckinName(assetData["id"], email=True)
                last_name  = getLatestCheckinName(assetData["id"])  # name for templates

                if last_email and is_email(last_email):
                    use_last = messagebox.askyesno(
                        title="No current assignee",
                        message=(
                            "This asset is not currently checked out (or has no valid email).\n\n"
                            f"Send the notice to the last user on record?\n\n"
                            f"Last user: {last_name or '(unknown)'}\n"
                            f"Email: {last_email}\n\n"
                            "Yes = Send to last user\nNo = Turn emailing OFF"
                        )
                    )
                    if use_last:
                        recipient_email = last_email
                        full_name = last_name or full_name
                    else:
                        want_email = False
                        email_var.set(False)  # reflect the choice in UI/notes
                else:
                    # No usable email; disable sending to avoid misdirected notices.
                    messagebox.showinfo(
                        title="No email available",
                        message=(
                            "Asset is not currently checked out and no previous user email was found.\n"
                            "Emailing will be turned OFF for this repair."
                        )
                    )
                    want_email = False
                    email_var.set(False)

        # Build notes cleanly using the effective email decision.
        issue_notes = (
            f"{issue_description} "
            f"At Fault: {at_fault} "
            f"Send Emails: {want_email} "
            f"Text Student: {text_var.get()} "
            f"Email Parent: {parent_var.get()}"
        )

        # Optional email/text notifications (best-effort; surfaced if fail).
        if want_email:
            # Choose template and handle "remove fine" flag based on the effective recipient
            if recipient_email and remove_fine_warning(recipient_email):
                content = repair_notice_no_fine(full_name or "")
                issue_notes += " Remove Charge: True"
            else:
                content = repair_notice(full_name or "")

            subject = "Repair Notice"
            recipient = recipient_email if recipient_email and is_email(recipient_email) else support_email
            if recipient is support_email:
                if not full_name:
                    subject = "Error name not found: " + subject
                if not (recipient_email and is_email(recipient_email)):
                    subject = "Error email not valid/missing: " + subject

            def _send_msg():
                """Send repair notice through the messaging utility."""
                # wrap in callable so failures hit the same retry UI
                message(content, recipient,
                        subject=subject,
                        text_student_recipient=text_var.get(),
                        email_parent=parent_var.get())
                # mimic a 'success' Response-like object
                class _Fake:
                    """Simple response stub for retry wrapper."""
                    status_code = 200
                    def json(self_inner):
                        """Return a success payload for retry wrapper."""
                        return {"status": "success"}
                return _Fake()

            # Let user retry if messaging pipeline throws
            _ = _do_with_retry("Send repair notice", _send_msg)
            if _ is None:
                # User canceled messaging; continue with Snipe-IT anyway
                pass

        today = str(date.today())

        # 1) Check-in (skip if already Pending Repair).
        settings = get_settings()
        try:
            pending_repair_id = int(settings.get("repairPendingStatusId", 17))
        except Exception:
            pending_repair_id = 17
        current_status_id = assetData["status_label"]["id"]

        if current_status_id == pending_repair_id:
            # Already in Pending Repair — skip check-in quietly
            checkin_result = {"__skipped__": True}
        else:
            payload1 = {"status_id": current_status_id}

            def _checkin():
                """POST a check-in to unassign the asset."""
                return requests.post(f"{url}/hardware/{assetData['id']}/checkin",
                                     json=payload1, headers=get_headers())

            checkin_result = _do_with_retry_or_skip("Check-in asset", _checkin)

        if checkin_result is None:
            # User chose Cancel
            logger.warning("Check-in canceled by user for %s", asset_tag)
            return False
        # if skipped, just proceed

        # 2) Update status to Pending Repair (17).
        payload2 = {
            "asset_tag": asset_tag,
            "model_id": assetData["model"]["id"],
            "status_id": pending_repair_id
        }
        def _update_status():
            """PUT an updated status on the asset."""
            return requests.put(f"{url}/hardware/{assetData['id']}",
                                json=payload2, headers=get_headers())
        logger.info(
            "Repair status update for %s to status_id=%s",
            asset_tag,
            pending_repair_id,
        )
        if _do_with_retry("Update asset status", _update_status) is None:
            logger.error("Update asset status canceled or failed for %s", asset_tag)
            return False

        # 3) Create maintenance record.
        try:
            supplier_id = int(settings.get("repairMaintenanceSupplierId", 1))
        except Exception:
            supplier_id = 1

        maintenance_type = settings.get("repairMaintenanceType", "Repair")
        payload3 = {
            "asset_maintenance_type": maintenance_type,
            "start_date": today,
            "name": title or f"Repair: {asset_tag} ({today})",
            "asset_id": assetData["id"],
            "supplier_id": supplier_id,
            "notes": issue_notes
        }
        def _create_maint():
            """POST a new maintenance record for the repair."""
            return requests.post(f"{url}/maintenances", json=payload3, headers=get_headers())
        logger.info(
            "Creating maintenance for %s (supplier_id=%s type=%s)",
            asset_tag,
            supplier_id,
            maintenance_type,
        )
        if _do_with_retry("Create maintenance", _create_maint) is None:
            logger.error("Create maintenance canceled or failed for %s", asset_tag)
            return False

        # Refresh asset data for label fields.
        junk, assetData = getAssetInfo(asset_tag)

        # 4) Print label (Retry / Skip / Cancel).
        def _print_label():
            """Render and print the repair label."""
            printData = [
                assetData["asset_tag"],
                assetData["status_label"]["name"],
                assetData["name"],
                title or ""
            ]
            createImage(printData)
            class _Fake:
                """Simple response stub for print flow."""
                status_code = 200
                def json(self_inner):
                    """Return a success payload for print flow."""
                    return {"status": "success"}
            return _Fake()

        while True:
            try:
                _print_label()
                logger.info("Repair label printed for %s", asset_tag)
                break
            except Exception as e:
                logger.exception("Label print failed for %s", asset_tag)
                choice = messagebox.askyesnocancel(
                    title="Label print failed",
                    message=f"{type(e).__name__}: {e}\n\nYes = Retry, No = Skip, Cancel = Abort"
                )
                if choice is True:   # Retry
                    continue
                elif choice is False: # Skip
                    break
                else:                 # Cancel
                    logger.warning("Label print canceled by user for %s", asset_tag)
                    return False

        return True

    return f"New repair window opened for {asset_tag}. Submit to complete."
