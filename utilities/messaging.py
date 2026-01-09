#!/usr/bin/env python3
"""
messaging.py

Email + SMS helper utilities for the Asset Automations GUI.

This file provides:
 - SFTP helpers that read student/family CSVs on the remote server
 - get_parents(email) -> list of parent emails
 - get_phone_number(email) -> phone number string or None
 - send_text_message(number, content) -> RingCentral API send (raises on failure)
 - message(...) -> unified function to send email and/or SMS and optionally email parents

Design notes:
 - Uses paramiko for SFTP access to the 'upload_data' dir.
 - Uses RingCentral SDK with JWT auth (expects ringCentral* variables from utilities.Key).
 - Uses Gmail SMTP for email (expects tech_email_info and support_email from utilities.Key).
 - Uses messagebox popups for user-facing errors and prints for simple runtime info.
"""

import csv
import json
import logging
import os
import re
import smtplib
from email.message import EmailMessage
from tkinter import messagebox

import paramiko
from paramiko import SSHException
from ringcentral import SDK
from ringcentral.http.api_exception import ApiException

from utilities.Key import *  # noqa: F401,F403 - provides credentials/constants used below
from utilities.logging_utils import configure_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Helper: SFTP open + CSV reader
# ---------------------------------------------------------------------
def _open_sftp():
    """
    Open an SFTP connection to the remote host and change into 'upload_data'.

    Returns:
        (transport, sftp) tuple. Caller MUST close both resources when finished:
            try:
                transport, sftp = _open_sftp()
                ...
            finally:
                sftp.close(); transport.close()

    Raises:
        Exception on failure to connect or change directory.
    """
    configure_logging()
    # Establish an SFTP connection and switch to the expected directory.
    transport = None
    sftp = None
    try:
        transport = paramiko.Transport((ruvna_hostname, 22))
        transport.connect(username=ruvna_username, password=ruvna_password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.chdir('upload_data')
        return transport, sftp
    except Exception:
        # Ensure any partially-opened resources are closed before re-raising
        try:
            if sftp:
                sftp.close()
        except Exception:
            pass
        try:
            if transport:
                transport.close()
        except Exception:
            pass
        raise


def _read_remote_csv(sftp, filename):
    """
    Read a CSV file from an open SFTP client and return a list of rows.

    Args:
        sftp: open paramiko SFTPClient
        filename: filename in the current SFTP directory

    Returns:
        List of rows (each row is a list of strings).
    """
    configure_logging()
    # Read the CSV from SFTP into a list of rows.
    rows = []
    with sftp.open(filename, 'r') as remote_file:
        reader = csv.reader(remote_file)
        for row in reader:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------
# get_parents
# ---------------------------------------------------------------------
def get_parents(email):
    """
    Return a list of parent email addresses for the student matching `email`.

    The function will attempt to connect to the SFTP server and read:
      - students.csv
      - families.csv

    It searches students.csv for a row where column index 6 (7th column) matches `email`
    (case-insensitive). If a match is found, it looks up the family row in families.csv
    with the same family id (assumed in column 0) and collects parent emails from
    columns 6, 12, 18, ... (every 6th column starting at index 6) as in your original layout.

    If the SFTP connection fails, a retry/Cancel dialog is shown. If Cancel, returns [].

    Args:
        email: student email (string)

    Returns:
        list of parent email strings (may be empty).
    """
    configure_logging()
    # Retry loop for transient SFTP failures.
    trying = True
    while trying:
        try:
            # Pull both student and family CSVs from the server.
            transport, sftp = _open_sftp()
            try:
                students = _read_remote_csv(sftp, 'students.csv')
                families = _read_remote_csv(sftp, 'families.csv')
            finally:
                # Always close SFTP resources
                try:
                    sftp.close()
                except Exception:
                    pass
                try:
                    transport.close()
                except Exception:
                    pass

            # Find the student row by email, then map to family rows.
            search_value = str(email).lower()
            result = []

            for row in students:
                if len(row) > 6 and row[6].lower() == search_value:
                    # found student row; find corresponding family row(s)
                    for jrow in families:
                        if len(jrow) > 2 and jrow[0] == row[0]:
                            # collect parent emails from columns 6, 12, 18...
                            for item in jrow[6::6]:
                                if item:
                                    result.append(item)
                            return result
            # if not found return empty list
            return result

        except SSHException as e:
            logger.exception("SFTP connection failed while fetching parents")
            trying = messagebox.askretrycancel("Error", f"Failed to connect to server\nError: {e}")
            if not trying:
                return []
        except Exception as e:
            # Unexpected error - allow retry as well
            logger.exception("Unexpected error while fetching parents")
            trying = messagebox.askretrycancel("Error", f"Unexpected error while fetching parents:\n{e}")
            if not trying:
                return []


# ---------------------------------------------------------------------
# get_phone_number
# ---------------------------------------------------------------------
def get_phone_number(email):
    """
    Return the student's phone number (string) found in students.csv.

    Searches students.csv for the row where column index 6 equals the given email
    (case-insensitive) and returns column index 5 (as in your original code).

    If SFTP fails, shows retry/Cancel dialog. On Cancel or not found, returns None.

    Args:
        email: student email (string)

    Returns:
        phone number string (may be None if not found).
    """
    configure_logging()
    # Retry loop for transient SFTP failures.
    trying = True
    while trying:
        try:
            # Pull the students CSV from the server.
            transport, sftp = _open_sftp()
            try:
                students = _read_remote_csv(sftp, 'students.csv')
            finally:
                try:
                    sftp.close()
                except Exception:
                    pass
                try:
                    transport.close()
                except Exception:
                    pass

            # Find the matching student row by email.
            search_value = str(email).lower()
            for row in students:
                if len(row) > 6 and row[6].lower() == search_value:
                    return row[5]  # keep same column index as your original file
            return None

        except SSHException as e:
            logger.exception("SFTP connection failed while fetching phone number")
            trying = messagebox.askretrycancel("Error", f"Failed to connect to server\nError: {e}")
            if not trying:
                return None
        except Exception as e:
            logger.exception("Unexpected error while fetching phone number")
            trying = messagebox.askretrycancel("Error", f"Unexpected error while fetching phone:\n{e}")
            if not trying:
                return None


# ---------------------------------------------------------------------
# send_text_message
# ---------------------------------------------------------------------
def send_text_message(number: str, content: str):
    """
    Send an SMS via RingCentral using JWT auth.

    Number normalization rules:
      - Remove spaces, hyphens, dots, and parentheses.
      - If cleaned number starts with '+' and has 7-15 digits after '+', accept it.
      - If cleaned number has exactly 10 digits, assume US and prepend '+1'.
      - If cleaned number has 7-15 digits (no '+'), prepend '+' and use it.
      - Otherwise raise ValueError.

    This keeps things permissive enough for xxx-xxx-xxxx while catching clearly invalid values.
    """
    configure_logging()
    # Normalize/validate the phone number before sending.
    if not number:
        raise ValueError("No phone number provided to send_text_message")

    raw = str(number).strip()

    # Normalize: remove common separators but preserve leading '+'.
    if raw.startswith('+'):
        cleaned = '+' + re.sub(r"[^\d]", "", raw[1:])
    else:
        cleaned = re.sub(r"[^\d]", "", raw)

    # Validate/form the final number to send.
    if cleaned.startswith('+'):
        digits = cleaned[1:]
        if not (7 <= len(digits) <= 15):
            raise ValueError(f"Phone number looks invalid after cleanup: {number} -> {cleaned}")
        final_number = cleaned
    else:
        # cleaned contains only digits
        if len(cleaned) == 10:
            # common US format -> assume +1
            final_number = f"+1{cleaned}"
        elif 7 <= len(cleaned) <= 15:
            # no plus but plausible; prepend '+' and use it
            final_number = f"+{cleaned}"
        else:
            raise ValueError(f"Phone number looks invalid after cleanup: {number} -> {cleaned}")

    # Proceed with RingCentral send using final_number.
    sdk = SDK(ringCentralClientID, ringCentralClientSecret, ringCentralURLBase)
    platform = sdk.platform()
    try:
        # Authenticate to RingCentral before sending SMS.
        platform.login(jwt=ringCentralUserJWT)

        # Build the SMS payload.
        body = {
            "from": {"phoneNumber": ringCentralFromNumber},
            "to": [{"phoneNumber": final_number}],
            "text": content
        }

        # Send the SMS and return the response payload.
        resp = platform.post("/restapi/v1.0/account/~/extension/~/sms", body)
        data = resp.json()
        logger.debug("RingCentral SMS send response: %s", data)
        return data

    except ApiException as e:
        try:
            err_body = e.response.json()
            logger.error("RingCentral API error: %s", err_body)
            messagebox.showerror("Text send failed", f"RingCentral API error:\n{err_body}")
            raise RuntimeError(f"RingCentral API error: {err_body}") from e
        except Exception:
            logger.exception("RingCentral API error")
            messagebox.showerror("Text send failed", f"RingCentral API error: {e}")
            raise RuntimeError(f"RingCentral API error: {e}") from e
    except Exception as e:
        logger.exception("Unexpected error sending SMS")
        messagebox.showerror("Text send failed", f"Unexpected error sending SMS:\n{e}")
        raise
    finally:
        # Always attempt to logout to avoid lingering sessions.
        try:
            platform.logout()
        except Exception:
            pass



# ---------------------------------------------------------------------
# message (email + optional text + parent email)
# ---------------------------------------------------------------------
def message(content, recipient, subject=None, text_student_recipient=False, email_recipient=True, email_parent=False):
    """
    Unified send function for email and/or SMS.

    Parameters:
      - content: message body (string)
      - recipient: student email address (string)
      - subject: optional subject string (may be None)
      - text_student_recipient: if True, also send an SMS to the student (phone from students.csv)
      - email_recipient: if True, send email to the 'recipient' address
      - email_parent: if True, also email parent addresses (looked up via get_parents)

    Behavior:
      - If text_student_recipient is True but no phone found, shows an error dialog and continues.
      - Uses Gmail SMTP to send HTML-formatted emails to recipients. If there are no email recipients, SMTP is skipped.
      - Shows messagebox popups on email login/send failure.

    Returns:
      None
    """
    configure_logging()
    # Normalize inputs and prepare recipient list.
    recipients = []
    subject_safe = str(subject) if subject is not None else ""

    if email_recipient:
        recipients.append(recipient)

    if text_student_recipient:
        # Attempt to send SMS to student's phone
        phone = get_phone_number(recipient)
        if not phone:
            messagebox.showerror("Texting failed", f"No phone number found for {recipient}. SMS not sent.")
        else:
            try:
                sms_body = f"{subject_safe}\n\n{content}" if subject_safe else content
                send_text_message(phone, sms_body)
            except Exception as e:
                # send_text_message already displays a messagebox for API errors, but show a fallback as well
                logger.exception("Failed to send SMS to %s", phone)
                messagebox.showerror("Texting failed", f"Failed to send SMS to {phone}:\n{e}")

    if email_parent:
        parents = get_parents(recipient)
        if parents:
            recipients += parents

    # If there are no email recipients, skip SMTP entirely.
    if not recipients:
        logger.info("No email recipients configured; skipping email send.")
        return

    # Attempt SMTP login.
    try:
        s = smtplib.SMTP_SSL(host='smtp.gmail.com', port=465, timeout=30)
        s.login(*tech_email_info)
    except Exception as e:
        logger.exception("Failed to login to SMTP")
        messagebox.showerror("Email login failed", f"Failed to login to SMTP: {e}")
        return

    # Build HTML template once.
    header_img_url = "https://bbk12e1-cdn.myschoolcdn.com/ftpimages/425/logo/NEW2016MainSiteLogo.png"
    html_content = content.replace("\n", "<br>")
    html_template = f"""
    <html>
      <body style="font-family: Arial, sans-serif; margin:0; padding:0; font-size:16px; line-height:1.5; background:#f4f4f4;">
        <div style="max-width:600px; margin:0 auto; background:#ffffff;">

          <!-- Header -->
          <div style="background:#004b8d; padding:20px; text-align:left;">
            {"<img src='" + header_img_url + "' style='max-height:80px;' alt='School Logo'>" if header_img_url else ""}
          </div>

          <!-- Body -->
          <div style="padding:20px; font-size:16px; color:#333;">
            {html_content}
          </div>

          <!-- Footer -->
          <div style="background:#004b8d; padding:20px; text-align:center; font-size:13px; color:#fff;">
            Trinity Episcopal School<br>
            3850 Pittaway Drive, Richmond, VA 23235
          </div>

        </div>
      </body>
    </html>
    """

    # Send the email(s).
    try:
        for r in recipients:
            try:
                # Build and send one message per recipient.
                msg = EmailMessage()
                msg.set_content(content)
                msg.add_alternative(html_template, subtype="html")

                msg['Subject'] = subject_safe
                # If recipient is the tech/support address, send from tech_email_info[0], else from support_email
                msg['From'] = tech_email_info[0] if r == support_email else support_email
                msg['To'] = r

                s.send_message(msg)
                logger.info("Email sent to %s", r)
            except Exception as e:
                # Show error per-recipient but continue to other recipients
                logger.exception("Failed to send email to %s", r)
                messagebox.showerror("Email send failed", f"Failed to send email to {r}:\n{e}")
    finally:
        try:
            s.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------
# Pre-written message templates (unchanged, only docstrings added)
# ---------------------------------------------------------------------
def repair_notice(full_name):
    """Return a standard 'repair submitted' message body that may include fines."""
    return f"""Hello,

We are sending this to let you know that {full_name} has submitted their computer for repair.

Please note that there may be a fine associated with this repair. Manufacturing defects are covered, but accidental damage is not. If any charges apply, you will be notified when the computer is ready for pickup.

We will send you another update once the computer repair is complete and available for pickup.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def repair_notice_no_fine(full_name):
    """Return a 'repair submitted' message body (no-fine version)."""
    return f"""Hello,

We are sending this to let you know that {full_name} has submitted their computer for repair.

There will not be any fine associated with this, regardless of whether we determine the student to be at fault for the damage. Please help us make sure that {full_name} is careful with their computer in the future. 

We will send you another update once the computer repair is complete and available for pickup.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def ready_no_fine(full_name):
    """Return a 'ready for pickup' message body indicating no fine."""
    return f"""Hello,

We are pleased to inform you that the Macbook Air for {full_name} has been repaired and is now ready for pickup. 

{full_name} should schedule an appointment for laptop pickup using the following link:
https://calendly.com/trinitytech/support

Please note: there will not be a fine associated with this repair.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def ready_fine(full_name, fine_amount):
    """Return a 'ready for pickup' message body indicating a fine amount."""
    return f"""Hello,

We are pleased to inform you that the Macbook Air for {full_name} has been repaired and is now ready for pickup. 

{full_name} should schedule an appointment for laptop pickup using the following link:
https://calendly.com/trinitytech/support

Please note: the Business Office will issue a fine of ${fine_amount} associated with this repair. 

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


# ---------------------------------------------------------------------
# Helper: remove_fine_warning and is_email
# ---------------------------------------------------------------------
def remove_fine_warning(student_email):
    """
    Check settings.json patterns for warning matches and prompt the user.

    Returns True if the user chose to remove the fine (Yes), False otherwise.
    """
    try:
        # Load warning patterns from settings.json.
        settings_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings.json")
        with open(settings_path, "r") as fh:
            settings = json.load(fh)
        warn_patterns = settings.get("emailWarnPattern", "").split(";")
    except Exception as e:
        messagebox.showerror("Settings error", f"Failed to read settings.json:\n{e}")
        return False

    # Check student + parent emails for warning pattern matches.
    emails = [student_email] + get_parents(student_email)
    for email in emails:
        for pattern in warn_patterns:
            pattern = pattern.strip()
            if not pattern:
                continue
            try:
                if re.match(pattern, email.strip()):
                    return messagebox.askyesno("Warning", f"This repair is emailing {email}, which matches warning pattern {pattern}, would you like to remove this fine?")
            except re.error:
                # If pattern is invalid, skip it (could also show an error)
                continue
    return False


def is_email(email):
    """
    Basic email address validation.

    Returns True if the string looks like an email address, False otherwise.
    """
    # Normalize input to a string for regex validation.
    email = str(email)
    if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return True
    return False
