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
import logging
import re
import smtplib
import socket
from email.message import EmailMessage
from tkinter import messagebox

import paramiko
from paramiko import SSHException
from ringcentral import SDK
from ringcentral.http.api_exception import ApiException

from utilities.Key import (
    ringCentralClientID,
    ringCentralClientSecret,
    ringCentralFromNumber,
    ringCentralURLBase,
    ringCentralUserJWT,
    ruvna_hostname,
    ruvna_password,
    ruvna_username,
    support_email,
    tech_email_info,
)
from utilities.logging_utils import configure_logging
from utilities.settings import get_settings

logger = logging.getLogger(__name__)

# paramiko.Transport((host, port)) has no connect timeout of its own -- see
# _open_sftp() below. Matches paramiko's own banner_timeout default (15s)
# for the phase right after this one, so a totally unreachable host fails
# in a consistent, bounded amount of time end to end.
_SFTP_CONNECT_TIMEOUT_SECONDS = 15

# ---------------------------------------------------------------------
# Helper: SFTP open + CSV reader
# ---------------------------------------------------------------------
def _open_sftp():
    """Open an SFTP connection to the remote host and change into 'upload_data'.

    Returns:
        (transport, sftp) tuple. Caller MUST close both resources when finished:
            try:
                transport, sftp = _open_sftp()
                ...
            finally:
                sftp.close(); transport.close()

    Raises:
        Exception on failure to connect or change directory (including a
        socket.timeout if the host doesn't respond within
        _SFTP_CONNECT_TIMEOUT_SECONDS).
    """
    configure_logging()
    logger.debug("_open_sftp: connecting to %s:22", ruvna_hostname)
    # Establish an SFTP connection and switch to the expected directory.
    transport = None
    sftp = None
    try:
        # paramiko.Transport((host, port)) opens the raw TCP socket itself,
        # internally, with no timeout at all -- a network that silently
        # drops the connection attempt (e.g. an outbound-port-22 firewall
        # rule on a new deployment site) hangs here indefinitely rather
        # than failing. Building the socket ourselves bounds that.
        sock = socket.create_connection((ruvna_hostname, 22), timeout=_SFTP_CONNECT_TIMEOUT_SECONDS)
        transport = paramiko.Transport(sock)
        logger.debug("_open_sftp: transport created; authenticating as %s", ruvna_username)
        transport.connect(username=ruvna_username, password=ruvna_password)
        logger.debug("_open_sftp: authenticated; opening SFTPClient")
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.chdir('upload_data')
        logger.info("_open_sftp: SFTP connection established, chdir to upload_data")
        return transport, sftp
    except Exception:
        # Ensure any partially-opened resources are closed before re-raising
        logger.debug("_open_sftp: exception during connect; closing partial resources")
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
    """Read a CSV file from an open SFTP client and return a list of rows.

    Args:
        sftp: open paramiko SFTPClient
        filename: filename in the current SFTP directory

    Returns:
        List of rows (each row is a list of strings).
    """
    configure_logging()
    logger.debug("_read_remote_csv: reading %s via SFTP", filename)
    # Read the CSV from SFTP into a list of rows.
    rows = []
    with sftp.open(filename, 'r') as remote_file:
        reader = csv.reader(remote_file)
        for row in reader:
            rows.append(row)
    logger.debug("_read_remote_csv: read %s rows from %s", len(rows), filename)
    return rows


# ---------------------------------------------------------------------
# Helper: fetch CSVs over SFTP with retry/cancel on failure
# ---------------------------------------------------------------------
def _fetch_csvs_with_retry(filenames, op_name):
    """Open an SFTP connection (retrying on failure) and read the given CSVs.

    Shared by get_parents/get_phone_number, which both connect, read one or
    more CSVs from the same session, and offer an identical retry/cancel
    dialog on failure -- only the files fetched and the field extraction
    that follows differ between them.

    Args:
        filenames: Ordered list of CSV filenames to read from the session.
        op_name: Short description used in log/dialog text (e.g.
            "fetching parents").

    Returns:
        List of parsed CSV row-lists in the same order as filenames, or
        None if the user cancelled after a connection/read failure.
    """
    while True:
        try:
            logger.debug("_fetch_csvs_with_retry: opening SFTP connection for %s", op_name)
            transport, sftp = _open_sftp()
            try:
                results = [_read_remote_csv(sftp, name) for name in filenames]
                logger.debug("_fetch_csvs_with_retry: loaded %s file(s) for %s", len(results), op_name)
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
            return results

        except SSHException as e:
            logger.exception("SFTP connection failed while %s", op_name)
            if not messagebox.askretrycancel("Error", f"Failed to connect to server\nError: {e}"):
                return None
        except Exception as e:
            # Unexpected error - allow retry as well
            logger.exception("Unexpected error while %s", op_name)
            if not messagebox.askretrycancel("Error", f"Unexpected error while {op_name}:\n{e}"):
                return None


# ---------------------------------------------------------------------
# get_parents
# ---------------------------------------------------------------------
def get_parents(email):
    """Return a list of parent email addresses for the student matching the given email.

    Connects to the SFTP server and reads students.csv and families.csv.
    Searches students.csv for a row where column index 6 matches the given email
    (case-insensitive), then collects parent emails from the corresponding family
    row at columns 6, 12, 18, ... (every 6th column starting at index 6).

    If the SFTP connection fails, a retry/cancel dialog is shown; returns [] on
    cancel or unrecoverable error.

    Args:
        email: Student email address to look up.

    Returns:
        List of parent email strings (may be empty if not found or on error).
    """
    configure_logging()
    logger.debug("get_parents: looking up parents for email=%s", email)
    csvs = _fetch_csvs_with_retry(["students.csv", "families.csv"], "fetching parents")
    if csvs is None:
        return []
    students, families = csvs
    logger.debug("get_parents: loaded %s student rows and %s family rows", len(students), len(families))

    # Find the student row by email, then map to family rows.
    search_value = str(email).lower()
    result = []
    logger.debug("get_parents: searching for student email=%s", search_value)

    for row in students:
        if len(row) > 6 and row[6].lower() == search_value:
            logger.debug("get_parents: found student row for %s; searching family rows", email)
            # found student row; find corresponding family row(s)
            for jrow in families:
                if len(jrow) > 2 and jrow[0] == row[0]:
                    # collect parent emails from columns 6, 12, 18...
                    for item in jrow[6::6]:
                        if item:
                            result.append(item)
                    logger.debug("get_parents: found %s parent email(s) for %s", len(result), email)
                    return result
    # if not found return empty list
    logger.debug("get_parents: student %s not found; returning []", email)
    return result


# ---------------------------------------------------------------------
# get_phone_number
# ---------------------------------------------------------------------
def get_phone_number(email):
    """Return the student's phone number from students.csv on the SFTP server.

    Searches students.csv for the row where column index 6 matches the given
    email (case-insensitive) and returns column index 5 as the phone number.

    If SFTP fails, shows a retry/cancel dialog. Returns None on cancel,
    unreachable server, or when the student is not found.

    Args:
        email: Student email address to look up.

    Returns:
        Phone number string, or None if not found or on error.
    """
    configure_logging()
    logger.debug("get_phone_number: looking up phone for email=%s", email)
    csvs = _fetch_csvs_with_retry(["students.csv"], "fetching phone")
    if csvs is None:
        return None
    students, = csvs
    logger.debug("get_phone_number: loaded %s student rows", len(students))

    # Find the matching student row by email.
    search_value = str(email).lower()
    logger.debug("get_phone_number: searching for email=%s", search_value)
    for row in students:
        if len(row) > 6 and row[6].lower() == search_value:
            phone = row[5]
            logger.debug("get_phone_number: found phone=%s for email=%s", phone, email)
            return phone  # keep same column index as your original file
    logger.debug("get_phone_number: email=%s not found in students.csv; returning None", email)
    return None


# ---------------------------------------------------------------------
# send_text_message
# ---------------------------------------------------------------------
def send_text_message(number: str, content: str):
    """Send an SMS via RingCentral using JWT authentication.

    Normalizes the phone number before sending:
      - Removes spaces, hyphens, dots, and parentheses.
      - If cleaned number starts with '+' and has 7-15 digits after '+', uses it.
      - If cleaned number has exactly 10 digits, assumes US and prepends '+1'.
      - If cleaned number has 7-15 digits (no '+'), prepends '+' and uses it.
      - Otherwise raises ValueError.

    Args:
        number: Destination phone number (any common format; see normalization rules).
        content: SMS message body text.

    Returns:
        RingCentral API response data dict on success.

    Raises:
        ValueError: When the phone number cannot be normalized to a valid format.
        RuntimeError: When the RingCentral API returns an error response.
    """
    configure_logging()
    logger.debug("send_text_message: number=%s, content length=%s", number, len(content) if content else 0)
    # Normalize/validate the phone number before sending.
    if not number:
        raise ValueError("No phone number provided to send_text_message")

    raw = str(number).strip()
    logger.debug("send_text_message: raw number=%s", raw)

    # Normalize: remove common separators but preserve leading '+'.
    if raw.startswith('+'):
        cleaned = '+' + re.sub(r"[^\d]", "", raw[1:])
    else:
        cleaned = re.sub(r"[^\d]", "", raw)
    logger.debug("send_text_message: cleaned number=%s", cleaned)

    # Validate/form the final number to send.
    if cleaned.startswith('+'):
        digits = cleaned[1:]
        if not (7 <= len(digits) <= 15):
            raise ValueError(f"Phone number looks invalid after cleanup: {number} -> {cleaned}")
        final_number = cleaned
        logger.debug("send_text_message: international format detected, final_number=%s", final_number)
    else:
        # cleaned contains only digits
        if len(cleaned) == 10:
            # common US format -> assume +1
            final_number = f"+1{cleaned}"
            logger.debug("send_text_message: 10-digit US number, final_number=%s", final_number)
        elif 7 <= len(cleaned) <= 15:
            # no plus but plausible; prepend '+' and use it
            final_number = f"+{cleaned}"
            logger.debug("send_text_message: plausible number without '+', final_number=%s", final_number)
        else:
            raise ValueError(f"Phone number looks invalid after cleanup: {number} -> {cleaned}")

    logger.info("send_text_message: sending SMS to %s via RingCentral", final_number)
    # Proceed with RingCentral send using final_number.
    sdk = SDK(ringCentralClientID, ringCentralClientSecret, ringCentralURLBase)
    platform = sdk.platform()
    try:
        # Authenticate to RingCentral before sending SMS.
        logger.debug("send_text_message: logging in to RingCentral with JWT")
        platform.login(jwt=ringCentralUserJWT)
        logger.debug("send_text_message: RingCentral login successful")

        # Build the SMS payload.
        body = {
            "from": {"phoneNumber": ringCentralFromNumber},
            "to": [{"phoneNumber": final_number}],
            "text": content
        }
        logger.debug("send_text_message: SMS payload built, from=%s to=%s", ringCentralFromNumber, final_number)

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
        logger.debug("send_text_message: logging out from RingCentral platform")
        try:
            platform.logout()
        except Exception:
            pass



# ---------------------------------------------------------------------
# message (email + optional text + parent email)
# ---------------------------------------------------------------------
def message(content, recipient, subject=None, text_student_recipient=False, email_recipient=True, email_parent=False):
    """Send an email and/or SMS to a student, optionally CC'ing parents.

    Args:
        content: Message body text.
        recipient: Student email address used as the primary recipient.
        subject: Optional email subject line (None for empty subject).
        text_student_recipient: If True, also send an SMS to the student's
            phone number (looked up via students.csv on the SFTP server).
        email_recipient: If True, include the student email in the email list.
        email_parent: If True, also email parent addresses (looked up via
            get_parents for the given recipient).

    Returns:
        None. Shows messagebox dialogs on send failure.
    """
    configure_logging()
    logger.debug("message: recipient=%s, subject=%s, text_student=%s, email_recipient=%s, email_parent=%s",
                 recipient, subject, text_student_recipient, email_recipient, email_parent)
    # Normalize inputs and prepare recipient list.
    recipients = []
    subject_safe = str(subject) if subject is not None else ""
    logger.debug("message: subject_safe=%s", subject_safe)

    if email_recipient:
        recipients.append(recipient)
        logger.debug("message: added direct recipient %s", recipient)

    if text_student_recipient:
        logger.debug("message: looking up phone number for SMS to %s", recipient)
        # Attempt to send SMS to student's phone
        phone = get_phone_number(recipient)
        if not phone:
            logger.debug("message: no phone found for %s; skipping SMS", recipient)
            messagebox.showerror("Texting failed", f"No phone number found for {recipient}. SMS not sent.")
        else:
            logger.info("message: sending SMS to phone=%s", phone)
            try:
                sms_body = f"{subject_safe}\n\n{content}" if subject_safe else content
                send_text_message(phone, sms_body)
                logger.debug("message: SMS sent successfully to %s", phone)
            except Exception as e:
                # send_text_message already displays a messagebox for API errors, but show a fallback as well
                logger.exception("Failed to send SMS to %s", phone)
                messagebox.showerror("Texting failed", f"Failed to send SMS to {phone}:\n{e}")

    if email_parent:
        logger.debug("message: looking up parents for %s", recipient)
        parents = get_parents(recipient)
        if parents:
            recipients += parents
            logger.debug("message: added %s parent email(s): %s", len(parents), parents)

    # If there are no email recipients, skip SMTP entirely.
    if not recipients:
        logger.info("No email recipients configured; skipping email send.")
        return

    logger.info("message: sending email to %s recipient(s): %s", len(recipients), recipients)
    # Attempt SMTP login.
    try:
        s = smtplib.SMTP_SSL(host='smtp.gmail.com', port=465, timeout=30)
        s.login(*tech_email_info)
        logger.debug("message: SMTP login successful")
    except Exception as e:
        logger.exception("Failed to login to SMTP")
        messagebox.showerror("Email login failed", f"Failed to login to SMTP: {e}")
        return

    # Build HTML template once.
    header_img_url = "https://bbk12e1-cdn.myschoolcdn.com/ftpimages/425/logo/NEW2016MainSiteLogo.png"
    html_content = content.replace("\n", "<br>")
    logger.debug("message: HTML template built, content length=%s", len(html_content))
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
            logger.debug("message: sending email to %s", r)
            try:
                # Build and send one message per recipient.
                msg = EmailMessage()
                msg.set_content(content)
                msg.add_alternative(html_template, subtype="html")

                msg['Subject'] = subject_safe
                # If recipient is the tech/support address, send from tech_email_info[0], else from support_email
                msg['From'] = tech_email_info[0] if r == support_email else support_email
                msg['To'] = r
                logger.debug("message: built email from=%s to=%s", msg['From'], r)

                s.send_message(msg)
                logger.info("Email sent to %s", r)
            except Exception as e:
                # Show error per-recipient but continue to other recipients
                logger.exception("Failed to send email to %s", r)
                messagebox.showerror("Email send failed", f"Failed to send email to {r}:\n{e}")
    finally:
        logger.debug("message: quitting SMTP session")
        try:
            s.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------
# Pre-written message templates (unchanged, only docstrings added)
# ---------------------------------------------------------------------
def repair_notice(full_name):
    """Return a standard 'repair submitted' message body that may include fines.

    Args:
        full_name: The student's full name to embed in the message.

    Returns:
        Multi-line string containing the formatted repair notice.
    """
    logger.debug("repair_notice: full_name=%s", full_name)
    return f"""Hello,

We are sending this to let you know that {full_name} has submitted their computer for repair.

Please note that there may be a fine associated with this repair. Manufacturing defects are covered, but accidental damage is not. If any charges apply, you will be notified when the computer is ready for pickup.

We will send you another update once the computer repair is complete and available for pickup.

<strong>Important:</strong> Apple's repair process will likely require wiping the computer (deleting all data). Any data stored locally on the device should be backed up before the computer is shipped. Please reply to this email if any data needs to be retrieved. Data saved to Google Drive will be retained.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def repair_notice_no_fine(full_name):
    """Return a 'repair submitted' message body indicating no fine will be charged.

    Args:
        full_name: The student's full name to embed in the message.

    Returns:
        Multi-line string containing the formatted repair notice.
    """
    logger.debug("repair_notice_no_fine: full_name=%s", full_name)
    return f"""Hello,

We are sending this to let you know that {full_name} has submitted their computer for repair.

There will not be any fine associated with this, regardless of whether we determine the student to be at fault for the damage. Please help us make sure that {full_name} is careful with their computer in the future. 

We will send you another update once the computer repair is complete and available for pickup.

<strong>Important:</strong> Apple's repair process will likely require wiping the computer (deleting all data). Any data stored locally on the device should be backed up before the computer is shipped. Please reply to this email if any data needs to be retrieved. Data saved to Google Drive will be retained.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def ready_no_fine(full_name):
    """Return a 'ready for pickup' message body indicating no fine will be charged.

    Args:
        full_name: The student's full name to embed in the message.

    Returns:
        Multi-line string containing the formatted pickup notice.
    """
    logger.debug("ready_no_fine: full_name=%s", full_name)
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
    """Return a 'ready for pickup' message body stating the fine amount due.

    Args:
        full_name: The student's full name to embed in the message.
        fine_amount: Dollar amount of the fine to display (no '$' prefix needed).

    Returns:
        Multi-line string containing the formatted pickup notice with fine.
    """
    logger.debug("ready_fine: full_name=%s, fine_amount=%s", full_name, fine_amount)
    return f"""Hello,

We are pleased to inform you that the Macbook Air for {full_name} has been repaired and is now ready for pickup. 

{full_name} should schedule an appointment for laptop pickup using the following link:
https://calendly.com/trinitytech/support

Please note: the Business Office will issue a fine of ${fine_amount} associated with this repair. 

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def loan_checkout_warning_second(full_name, reason_label, expected_checkin=None):
    """Return a warning notice for a person's 2nd unexcused loaner checkout since the last cutoff.

    Args:
        full_name: The person's full name (or display label) to embed in the message.
        reason_label: The reason text given for this checkout.
        expected_checkin: Optional expected check-in date string (YYYY-MM-DD).

    Returns:
        Multi-line string containing the formatted warning notice.
    """
    logger.debug("loan_checkout_warning_second: full_name=%s reason_label=%s", full_name, reason_label)
    checkin_line = f"\nThe device is expected back by {expected_checkin}." if expected_checkin else ""
    return f"""Hello,

This is a notice that {full_name} has checked out a loaner computer for the 2nd time this semester.

Reason given: {reason_label}{checkin_line}

We are limiting loan computers to 3 per semester because repeated loaner checkouts can be disruptive. Please make sure you bring your own computer to school when possible.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def loan_checkout_warning_third(full_name, reason_label, expected_checkin=None):
    """Return a warning notice for a person's 3rd (or later) unexcused loaner checkout since the last cutoff.

    Args:
        full_name: The person's full name (or display label) to embed in the message.
        reason_label: The reason text given for this checkout.
        expected_checkin: Optional expected check-in date string (YYYY-MM-DD).

    Returns:
        Multi-line string containing the formatted warning notice.
    """
    logger.debug("loan_checkout_warning_third: full_name=%s reason_label=%s", full_name, reason_label)
    checkin_line = f"\nThe device is expected back by {expected_checkin}." if expected_checkin else ""
    return f"""Hello,

This is a notice that {full_name} has checked out a loaner computer for the 3rd (or more) time this semester.

Reason given: {reason_label}{checkin_line}

This is at or beyond the maximum number of loaner checkouts allowed without additional consideration. All further loan checkouts this semester are subject to review. We have a limited stock of loan computers available and will prioritize other students if stock is low.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


# ---------------------------------------------------------------------
# Helper: remove_fine_warning and is_email
# ---------------------------------------------------------------------
def remove_fine_warning(student_email):
    """Check settings.json patterns for warning matches and prompt the user.

    Reads emailWarnPattern from settings.json, then checks the student's email
    and their parent emails against each semicolon-separated regex pattern. If
    any match is found, a yes/no dialog asks whether to remove the fine.

    Args:
        student_email: The student's email address to check against patterns.

    Returns:
        True if the user chose to remove the fine (Yes); False otherwise or
        when no pattern matches.
    """
    logger.debug("remove_fine_warning: student_email=%s", student_email)
    settings = get_settings()
    warn_patterns = settings.get("emailWarnPattern", "").split(";")
    logger.debug("remove_fine_warning: loaded %s warn patterns", len(warn_patterns))

    # Check student + parent emails for warning pattern matches.
    emails = [student_email] + get_parents(student_email)
    logger.debug("remove_fine_warning: checking %s email(s) against patterns", len(emails))
    for email in emails:
        for pattern in warn_patterns:
            pattern = pattern.strip()
            if not pattern:
                continue
            logger.debug("remove_fine_warning: testing email=%s against pattern=%s", email, pattern)
            try:
                if re.match(pattern, email.strip()):
                    logger.info("remove_fine_warning: match found email=%s pattern=%s; prompting user", email, pattern)
                    return messagebox.askyesno("Warning", f"This repair is emailing {email}, which matches warning pattern {pattern}, would you like to remove this fine?")
            except re.error:
                # If pattern is invalid, skip it (could also show an error)
                logger.debug("remove_fine_warning: invalid regex pattern=%s; skipping", pattern)
                continue
    logger.debug("remove_fine_warning: no pattern matches found; returning False")
    return False


def is_email(email):
    """Return True if the string looks like a valid email address.

    Uses a simple regex pattern covering most common email formats. Does not
    perform DNS or SMTP validation.

    Args:
        email: Candidate email string to validate.

    Returns:
        True when the string matches the email pattern; False otherwise.
    """
    logger.debug("is_email checking: %s", email)
    # Normalize input to a string for regex validation.
    email = str(email)
    return bool(re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email))
