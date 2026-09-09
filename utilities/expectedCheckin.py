"""Shared expected_checkin formatting for Snipe-IT submissions.

Snipe-IT changed expected_checkin from a bare date to a date+time field.
This app always wants devices back by end of the school day by default, so
a bare date submission gets EXPECTED_CHECKIN_TIME appended rather than
leaving the time to whatever Snipe defaults an unspecified time to -- but a
caller that lets someone set an exact time (consisterizer's generic field
editor) can still do so; a value that already has a time component is left
alone.
"""

import logging

logger = logging.getLogger(__name__)

EXPECTED_CHECKIN_TIME = "15:00:00"  # 3:00 PM, end of school day


def with_checkin_time(date_str: str | None) -> str | None:
    """Ensure an expected_checkin value has a time component, defaulting to 3PM.

    A bare "YYYY-MM-DD" date gets EXPECTED_CHECKIN_TIME appended. A value
    that already has a time component (e.g. a caller -- like consisterizer
    -- that lets someone set an exact datetime) is passed through unchanged
    rather than double-appended. Blank/None passes through as None.

    Args:
        date_str: A "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS" string, or falsy
            for "no expected checkin".

    Returns:
        "YYYY-MM-DD 15:00:00" (default time applied), the original string
        unchanged if it already had a time component, or None if blank.
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    if " " in date_str:
        logger.debug("with_checkin_time: date_str=%s already has a time, left unchanged", date_str)
        return date_str
    result = f"{date_str} {EXPECTED_CHECKIN_TIME}"
    logger.debug("with_checkin_time: date_str=%s -> %s", date_str, result)
    return result
