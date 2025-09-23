from paramiko import SSHException
from tkinter import messagebox
from Utilities.Key import *
from email.message import EmailMessage
import smtplib
import paramiko
import csv

def get_parents(email):
    trying = True
    while trying:
        try:

            # Connect to SFTP
            transport = paramiko.Transport((ruvna_hostname, 22))
            transport.connect(username=ruvna_username, password=ruvna_password)
            sftp = paramiko.SFTPClient.from_transport(transport)

            # Change to remote directory
            sftp.chdir('upload_data')

            # Function to read a remote CSV file into a list of lists
            def read_remote_csv(filename):
                rows = []
                with sftp.open(filename, 'r') as remote_file:
                    reader = csv.reader(remote_file)
                    for row in reader:
                        rows.append(row)
                return rows


            # Read both files into memory
            students = read_remote_csv('students.csv')
            families = read_remote_csv('families.csv')

            # Close SFTP connection
            sftp.close()
            transport.close()

            # ✅ Example: Find all rows where column 2 (index 1) equals "12345"
            search_value = email.lower()
            result = []
            for row in students:
                if len(row) > 6 and row[6].lower() == search_value:
                    for jrow in families:
                        if len(jrow) > 2 and jrow[0] == row[0]:
                            for item in jrow[6::6]:
                                if item != "":
                                    result.append(item)
                            return result
            return result

        except SSHException as e:
            trying = messagebox.askretrycancel("Error", "Failed to connect to server")
            if not trying:
                return []

def message(content, recipient, subject=None, text=False, parent=False):
    recipients = []
    if text:
        messagebox.showerror("Error", "Texting not yet implemented: emailing instead")
        ##### do the texting here ##########
        recipients.append(recipient) # emailing instead of texting for now

    else:
        recipients.append(recipient)

    if parent:
        recipients += (get_parents(recipient))

    s = smtplib.SMTP_SSL(host='smtp.gmail.com', port=465)
    s.login(*tech_email_info)

    for recipient in recipients:
        msg = EmailMessage()

        # --- Plain text fallback ---
        msg.set_content(content)

        # --- HTML version with template ---
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

        msg.add_alternative(html_template, subtype="html")

        msg['Subject'] = subject
        if recipient == support_email:
            msg['From'] = tech_email_info[0]
        else:
            msg['From'] = support_email
        msg['To'] = recipient

        s.send_message(msg)

    s.quit()

def repair_notice(full_name):
    return f"""Hello,

This email is to let you know that {full_name} has submitted their computer for repair.

Please note that there may be a fine associated with this repair. Manufacturing defects are covered, but accidental damage is not. If any charges apply, you will be notified when the computer is ready for pickup.

We will send you another update once the computer repair is complete and available for pickup.

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""


def ready_no_fine(full_name):
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
    return f"""Hello,

We are pleased to inform you that the Macbook Air for {full_name} has been repaired and is now ready for pickup. 

{full_name} should schedule an appointment for laptop pickup using the following link:
https://calendly.com/trinitytech/support

Please note: the Business Office will issue a fine of ${fine_amount} associated with this repair. 

Thank you for your attention.

Sincerely,
Trinity Episcopal School IT Department
"""
