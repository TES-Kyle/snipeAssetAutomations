"""Back-from-Apple workflow for repair completion and messaging."""

import logging
import re  # added for flag normalization
from datetime import date, datetime, timedelta

import tkinter as tk
from tkinter import messagebox

from utilities.logging_utils import configure_logging
from utilities.settings import  get_settings
from utilities.otherApiBits import *
from utilities.Key import *
from utilities.messaging import *

logger = logging.getLogger(__name__)


def _parse_date_value(value):
    """Parse a date-like value into a date object.

    Args:
        value: Date value from Snipe-IT (string, dict, datetime, or date).

    Returns:
        datetime.date or None when parsing fails.
    """
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, dict):
        # Prefer ISO-friendly keys before formatted strings.
        value = value.get("date") or value.get("datetime") or value.get("formatted")
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    if " " in s:
        s = s.split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _extract_checkout_date(asset_row: dict) -> date | None:
    """Extract a loaner checkout date from a user asset row."""
    if not isinstance(asset_row, dict):
        return None
    for key in (
        "checkout_at",
        "last_checkout",
        "last_checkout_at",
        "last_checkout_date",
        "assigned_at",
        "checked_out_at",
        "checkout_date",
    ):
        if asset_row.get(key):
            return _parse_date_value(asset_row.get(key))
    assigned = asset_row.get("assigned_to") or {}
    if isinstance(assigned, dict):
        return _parse_date_value(assigned.get("checkout_at") or assigned.get("assigned_at"))
    return None


def sendFineEmail(name, charge, assetTag, divert=False):
    """Send a fine email or divert to support when data is incomplete.

    Args:
        name: Student name for the fine notice (may be None).
        charge: Fine amount in dollars.
        assetTag: Asset tag for context in failure emails.
        divert: If True, send to support instead of the student/ops.
    """
    configure_logging()
    # Compose and route fine notification email.
    if name is not None and divert is False:
        content = f"The following Student needs to be charged ${charge} for breaking their laptop:\n" + name
        message(content, operations_email, subject='Laptop Repair Fine')
    else:
        content = f"Failed to find name for fine email.\nCharge: {charge}\nAsset Tag: {assetTag}"
        message(content, support_email, subject='Laptop Repair Fine Email Failed')
        logger.warning("Fine email diverted or missing name for %s", assetTag)


def set_loan_checkin(username, maintenance_start_date: date | None = None):
    """Update the loaner check-in date for the specified username.

    Args:
        username: Username used to locate the loaner asset.
        maintenance_start_date: Start date of the associated maintenance record.

    Returns:
        True when the check-in date is updated, False otherwise.
    """
    configure_logging()
    settings = get_settings()
    try:
        window_days = int(settings.get("loanerCheckinWindowDays", 2))
    except Exception:
        window_days = 2
    if window_days < 0:
        window_days = 0
    # Fetch the user's loaner record and update the check-in date.
    if username:
        if maintenance_start_date is None:
            logger.warning("Loaner check-in skipped: maintenance start date missing")
            return False
        user_data = requests.get(
            Key.API_URL_Base + f"users?username= {username}",
            headers=get_headers(),
        ).json()

        if user_data['total'] == 1:  # fix this
            user_assets = requests.get(
                Key.API_URL_Base + f"users/{user_data['rows'][0]['id']}/assets",
                headers=get_headers(),
            ).json()
            asset_id = []
            for row in user_assets['rows']:
                if row['category']['id'] == 24 and row['status_label']['id'] == 31:
                    checkout_date = _extract_checkout_date(row)
                    if checkout_date is None:
                        logger.warning("Loaner asset missing checkout date: %s", row.get("id"))
                        continue
                    delta_days = abs((checkout_date - maintenance_start_date).days)
                    if delta_days <= window_days:
                        asset_id.append(row['id'])

            if len(asset_id) == 1:
                payload = {
                    "expected_checkin": (date.today() + timedelta(days=1)).isoformat()
                }
                _ = requests.patch(
                    Key.API_URL_Base + f"hardware/{asset_id[0]}",
                    json=payload,
                    headers=get_headers(),
                ).json()
                return True
            elif len(asset_id) == 0:
                logger.info(
                    "Skipping loaner check-in: no loaner checkout within %s day(s) of %s",
                    window_days,
                    maintenance_start_date,
                )
                return False
            else:
                return False
        else:
            return False
    else:
        return False


def backFromApple(asset_tag):
    """Run the GUI flow for closing out Apple repairs.

    Args:
        asset_tag: Asset tag being processed.

    Returns:
        Status message string for the main UI.
    """
    configure_logging()
    # Build the UI and wire callbacks for repair completion.
    def submit_repair_info(event=None):
        """Validate inputs and submit repair updates/notifications."""
        # Collect input values from the UI.
        d_number = d_number_entry.get()
        repair_notes = repair_notes_entry.get("1.0", tk.END).strip()

        # Validate numeric charge entry before proceeding.
        if charge_entry.get().strip().isnumeric():
            logger.debug("Repair D number: %s", d_number)
            logger.debug("Repair notes entered for %s", asset_tag)
            # Update maintenance record and status.
            updateMaintenance(asset_tag, d_number, repair_notes, fault.get())

            # Gather last known user info for notifications and fines.
            name = getLatestCheckinName(assetData["id"])
            email = getLatestCheckinName(assetData["id"], email=True)
            username = getLatestCheckinName(assetData["id"], username=True)
            charge = int(charge_entry.get().strip())

            # Apply fine logic when student is at fault.
            if fault.get() and charge > 0:
                if remove_fine_warning(email):
                    charge = 0
                else:
                    sendFineEmail(name, charge, asset_tag, divert=divert.get())

            # Use UI checkbox decisions for messaging
            # Send completion email/text messages based on toggles.
            if email_var.get():
                subject = "Computer Ready for Pickup"

                if fault.get() and (charge > 0):
                    content = ready_fine(name, charge)
                else:
                    content = ready_no_fine(name)

                if name is not None and divert.get() is False and is_email(email):
                    recipient = email
                else:
                    recipient = support_email
                    if name is None:
                        subject = "Error name not found: " + subject
                    if divert.get():
                        subject = "Error email diverted: " + subject
                    if not is_email(email):
                        subject = "Error email not valid: " + subject

                message(
                    content,
                    recipient,
                    subject=subject,
                    text_student_recipient=text_var.get(),
                    email_parent=parent_var.get()
                )

            # Attempt to update loaner check-in date.
            loan_checkin = set_loan_checkin(username, maintenance_start_date)
            if loan_checkin is False:
                messagebox.showinfo("Warning", "Loan computer check-in date not set.")

            repair_window.destroy()
        else:
            messagebox.showerror("Error", "Dumb dumb, only numbers")

    def on_enter_pressed(event):
        """Handle Enter key in the D number field."""
        repair_notes_entry.focus_set()

    def on_enter_pressed_in_repair_notes(event):
        """Insert a newline in the repair notes field."""
        repair_notes_entry.insert(tk.INSERT, "\n")

    # Create a new top-level window.
    repair_window = tk.Toplevel()

    # Asset info panel (helps validate the correct asset tag).
    var_list, assetData = getAssetInfo(asset_tag)
    info_frame, _check_vars = build_asset_info_frame(
        repair_window, var_list, include_checkboxes=False, padx=5, pady=2
    )
    info_frame.pack(fill='x', padx=10, pady=5)

    # Frame for the "D Number" question.
    d_number_frame = tk.Frame(repair_window)
    d_number_frame.pack(fill='x', padx=10, pady=5)
    d_number_label = tk.Label(d_number_frame, text="D Number:")
    d_number_label.pack(side='left')
    d_number_entry = tk.Entry(d_number_frame, width=50)  # Text entry for D Number
    d_number_entry.pack(side='left', expand=True, fill='x')
    d_number_entry.bind('<Return>', on_enter_pressed)  # Bind Enter key to shift focus
    d_number_entry.focus_set()  # Set focus to the D number entry box

    # Frame for Charge/Fault/Divert.
    res = requests.get(
        Key.API_URL_Base + "maintenances?limit=1&offset=0&sort=created_at&order=desc&asset_id="
        + str(assetData["id"]), headers=get_headers()).json()
    try:
        notes = res["rows"][0]["notes"]
    except (KeyError, IndexError):
        notes = ""

    maintenance_start_date = None
    try:
        row0 = res.get("rows", [])[0] if isinstance(res, dict) else None
        maintenance_start_date = _parse_date_value((row0 or {}).get("start_date"))
        if maintenance_start_date:
            logger.debug("Maintenance start date for %s: %s", asset_tag, maintenance_start_date)
        else:
            logger.warning("Maintenance start date missing for %s", asset_tag)
    except Exception:
        logger.exception("Failed to parse maintenance start date for %s", asset_tag)
        maintenance_start_date = None

    default_fault = "At Fault: Yes" in (notes or "")
    default_send_emails = "Send Emails: True" in (notes or "")
    default_text_student = "Text Student: True" in (notes or "")
    default_email_parent = "Email Parent: True" in (notes or "")

    charge_frame = tk.Frame(repair_window)
    charge_frame.pack(fill='x', padx=10, pady=5)

    fault_label = tk.Label(charge_frame, text="Student at Fault?:")
    fault_label.pack(side='left')
    fault = tk.BooleanVar(value=default_fault)
    yes = tk.Radiobutton(charge_frame, text="Yes", variable=fault, value=True)
    yes.pack(side='left')
    no = tk.Radiobutton(charge_frame, text="No  |", variable=fault, value=False)
    no.pack(side='left')

    charge_label = tk.Label(charge_frame, text="Charge: $")
    charge_label.pack(side='left')
    charge_entry = tk.Entry(charge_frame, width=10)  # Text entry for charge
    charge_entry.insert(0, "100" if "Remove Charge: True" not in (notes or "") else "0")
    charge_entry.pack(side='left', expand=True, fill='x')
    charge_entry.bind('<Return>', on_enter_pressed)  # Bind Enter key to shift focus

    divert_label = tk.Label(charge_frame, text="Divert email?")
    divert_label.pack(side='left')
    divert = tk.BooleanVar(value=False)
    divert.set(False)
    d_yes = tk.Radiobutton(charge_frame, text="Yes", variable=divert, value=True)
    d_yes.pack(side='left')
    d_no = tk.Radiobutton(charge_frame, text="No", variable=divert, value=False)
    d_no.pack(side='left')

    # Messaging Options (defaults from latest note)
    msg_frame = tk.Frame(repair_window)
    msg_frame.pack(fill='x', padx=10, pady=5)

    email_label = tk.Label(msg_frame, text="Send Emails")
    email_label.pack(side='left')
    email_var = tk.BooleanVar(value=default_send_emails)
    email_chk = tk.Checkbutton(msg_frame, variable=email_var)
    email_chk.pack(side='left')

    text_label = tk.Label(msg_frame, text="Also Text Student?")
    text_label.pack(side='left')
    text_var = tk.BooleanVar(value=default_text_student)
    text_chk = tk.Checkbutton(msg_frame, variable=text_var)
    text_chk.pack(side='left')

    parent_label = tk.Label(msg_frame, text="Also Email Parents?")
    parent_label.pack(side='left')
    parent_var = tk.BooleanVar(value=default_email_parent)
    parent_chk = tk.Checkbutton(msg_frame, variable=parent_var)
    parent_chk.pack(side='left')

    # Live "primary email" readout
    name_for_label = getLatestCheckinName(assetData["id"])
    email_for_label = getLatestCheckinName(assetData["id"], email=True)

    primary_email_var = tk.StringVar(value="")

    def _refresh_primary_label(*_args):
        """Update the primary email label based on toggle state."""
        # Compute which address would be used as primary, and why
        if name_for_label is not None and (not divert.get()) and is_email(email_for_label):
            chosen = email_for_label
            reason = "student"
        elif divert.get():
            chosen = support_email
            reason = "divert on"
        else:
            chosen = support_email
            reason = "invalid student email"

        if email_var.get():
            primary_email_var.set(f"Primary email → {chosen}  ({reason})")
        else:
            primary_email_var.set(f"Emails OFF — intended primary would be {chosen}  ({reason})")

    # Primary email label
    primary_email_frame = tk.Frame(repair_window)
    primary_email_frame.pack(fill='x', padx=10, pady=2)
    primary_email_label = tk.Label(primary_email_frame, textvariable=primary_email_var, anchor='w', fg="gray20", justify='left')
    primary_email_label.pack(side='left')

    # Hook updates when toggles change
    email_var.trace_add("write", _refresh_primary_label)
    d_yes.config(command=_refresh_primary_label)
    d_no.config(command=_refresh_primary_label)

    # Initial compute
    _refresh_primary_label()

    # Frame for the "Repair Notes" question.
    repair_notes_frame = tk.Frame(repair_window)
    repair_notes_frame.pack(fill='x', padx=10, pady=5)
    repair_notes_label = tk.Label(repair_notes_frame, text="Repair Notes:")
    repair_notes_label.pack(side='left')
    repair_notes_entry = tk.Text(repair_notes_frame, height=10, width=40)  # Text widget for multiline input
    repair_notes_entry.pack(side='left', expand=True, fill='x')
    repair_notes_entry.bind('<Return>', on_enter_pressed_in_repair_notes)

    # Submit button.
    submit_button = tk.Button(repair_window, text="Submit", command=submit_repair_info)
    submit_button.pack(pady=10)

    # Error text label.
    error_text = tk.StringVar(value="")
    error_label = tk.Label(repair_window, textvariable=error_text)
    error_label.pack(pady=10)

    # Centering.
    repair_window.update_idletasks()
    screen_width = repair_window.winfo_screenwidth()
    screen_height = repair_window.winfo_screenheight()
    window_width = repair_window.winfo_width()
    window_height = repair_window.winfo_height()
    center_x = int((screen_width / 2) - (window_width / 2))
    center_y = int((screen_height / 2) - (window_height / 2))
    repair_window.geometry(f"+{center_x}+{center_y}")

    def updateMaintenance(asset_tag, d_number, repair_notes, atFault):
        """Patch the latest maintenance record and close out the repair.

        Args:
            asset_tag: Asset tag being updated.
            d_number: Repair ticket/number.
            repair_notes: Freeform repair notes from the UI.
            atFault: Boolean indicating student fault status.
        """
        # Build maintenance update payload.
        today = str(date.today())
        url = Key.API_URL_Base + "maintenances?limit=1&offset=0&sort=created_at&order=desc&asset_id=" + str(
            assetData["id"])
        response = requests.get(url, headers=get_headers())
        parsedRes = response.json()

        # Append D-number to the repair notes.
        repair_notes = " D Num: ".join([repair_notes, d_number])

        try:
            notes_local = parsedRes["rows"][0]["notes"] if parsedRes["rows"][0]["notes"] is not None else ""
        except LookupError as err:
            err.add_note("No maintenance found")
            error_text.set("No maintenance found")
            raise err

        # Normalize "At Fault" flag in existing notes text.
        if atFault is True and "At Fault: No" in notes_local:
            notes_local = notes_local.replace("At Fault: No", "At Fault: Yes")
        elif atFault is False and "At Fault: Yes" in notes_local:
            notes_local = notes_local.replace("At Fault: Yes", "At Fault: No")

        # Ensure the three messaging flags are accurate in the maintenance note.
        def _set_bool_flag(text, key, val_bool):
            """Ensure a boolean flag is present and normalized in notes text."""
            val = "True" if val_bool else "False"
            pattern = rf"({re.escape(key)}:\s*)(True|False)"
            if re.search(pattern, text):
                return re.sub(pattern, rf"\1{val}", text)
            else:
                return f"{text} {key}: {val}"

        notes_local = _set_bool_flag(notes_local, "Send Emails", email_var.get())
        notes_local = _set_bool_flag(notes_local, "Text Student", text_var.get())
        notes_local = _set_bool_flag(notes_local, "Email Parent", parent_var.get())

        # Append the repair notes block after normalized header flags.
        repair_notes = " Repair Notes: ".join([notes_local, repair_notes])

        payload = {
            "asset_maintenance_type": "Repair",
            "completion_date": today,
            "notes": repair_notes
        }

        # Update the maintenance record via PATCH.
        maintenance_response = requests.patch(
            Key.API_URL_Base + "maintenances/" + str(parsedRes["rows"][0]["id"]), json=payload,
            headers=get_headers())
        if maintenance_response.status_code >= 400:
            logger.error("Maintenance update failed for %s: %s", asset_tag, maintenance_response.text)
            messagebox.showerror(
                "Maintenance Update Failed",
                f"Failed to update maintenance record for {asset_tag}.\n\n{maintenance_response.text}",
            )
            return

        settings = get_settings()
        try:
            completed_status_id = int(settings.get("repairCompletedStatusId", 2))
        except Exception:
            completed_status_id = 2

        # Apply the completed status update on the asset.
        payload2 = {
            "asset_tag": asset_tag,
            "model_id": assetData["model"]["id"],
            "status_id": completed_status_id
        }

        response2 = requests.put(Key.API_URL_Base + "hardware/" + str(assetData["id"]), json=payload2,
                                 headers=get_headers())
        if response2.status_code >= 400:
            logger.error("BackFromApple update failed for %s: %s", asset_tag, response2.text)
            messagebox.showerror("Update Failed", f"Failed to update asset {asset_tag}.\n\n{response2.text}")
            return

        logger.info(
            "BackFromApple update complete for %s (status_id=%s)",
            asset_tag,
            completed_status_id,
        )

    assetName = assetData["name"]
    return f"Back-from-Apple window opened for {assetName}."
