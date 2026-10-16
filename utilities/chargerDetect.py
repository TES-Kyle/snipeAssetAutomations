"""Detect the serial number of the charger plugged into this Mac.

Shared by Make Charger and Connected Charger Data. Deliberately free of any
Key.py dependency so selecting either tool in a partial install never pulls in
extra secrets.
"""

import logging
import platform
import subprocess

logger = logging.getLogger(__name__)


def get_connected_charger_serial() -> str:
    """Return the connected charger's serial number (macOS only).

    Returns:
        The serial string, or "" if no charger is detected or the lookup fails.

    Raises:
        OSError: if not running on macOS.
    """
    logger.debug("get_connected_charger_serial: platform=%s", platform.system())
    if platform.system() != "Darwin":
        raise OSError("Unsupported operating system")
    try:
        result = subprocess.run(
            "system_profiler SPPowerDataType | awk '/AC Charger Information:/,/Charging/' | grep 'Serial Number'",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        serial = (result.stdout.strip().split(": ", 1)[-1] or "").strip()
        logger.debug("get_connected_charger_serial: detected serial=%s", serial)
        return serial
    except Exception:
        logger.debug("get_connected_charger_serial: detection failed, returning empty")
        return ""
