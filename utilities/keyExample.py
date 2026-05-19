"""{secret}s and environment constants for Asset Automations."""

# Default (legacy) API key used when API_KEYS is empty.
API_Key = "{secret}"
# Optional map of user display names -> API keys (matches settings apiUserStaticName).
API_KEYS = {
            "user1": "{secret}",
            "user2": "{secret}",
            "user3": "{secret}",
            "Generic": "{{secret}",
            }
# Email credentials and destinations.
tech_email_info = ["email@example.org", "{secret}"]
operations_email = "email@example.org"
support_email = "email@example.org"
# Label printer endpoint.
printer_ip = "tcp://{ip adress}"
# Snipe-IT base API URL.
API_URL_Base = "{snipe it url}"
# Jamf Pro API credentials.
jamfClientID = "{secret}"
jamfClientSecret = "{secret}"
jamfURL = "{jamf url}"
# Ruvna SFTP credentials.
ruvna_hostname = "{ruvna ip address}"
ruvna_username = "{secret}"
ruvna_password = "{secret}"
# RingCentral credentials. NOT IMPLEMENTED
ringCentralClientID = "xxxxxxx"
ringCentralClientSecret = "xxxxxxx"
ringCentralURLBase = "https://xxxxxxx.ringcentral.com"
ringCentralUserJWT = "xxxxxxx"
ringCentralFromNumber = "+1xxxxxxxxxx"
# Windmill Credentials.
windmillToken = "{secret}"

