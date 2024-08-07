import smtplib
from email.message import EmailMessage
from Key import tech_email_info as email_info, operations_email as fine_erEmail, support_email


def sendFineEmail(name, charge, assetTag, divert=False):
    if name is not None and divert is False:
        msg = EmailMessage()
        msg.set_content(f"The following Student needs to be charged ${charge} for breaking their laptop:\n" + name)
        msg['Subject'] = 'Laptop Repair Fine'
        msg['From'] = email_info[0]
        msg['To'] = fine_erEmail
    else:
        msg = EmailMessage()
        msg.set_content(f"Failed to find name for fine email.\nCharge: {charge}\nAsset Tag: {assetTag}")
        msg['Subject'] = 'Laptop Repair Fine Email Failed'
        msg['From'] = email_info[0]
        msg['To'] = support_email

    # Send the message via our own SMTP server.
    s = smtplib.SMTP_SSL(host='smtp.gmail.com', port=465)
    s.login(*email_info)
    s.send_message(msg)
    s.quit()
