"""Windmill job runner for triggering remote automation workflows.

Sends a POST request to a Windmill API endpoint and logs the result.
Token is read from utilities.Key (windmillToken).
"""

import logging

import requests

from utilities.Key import windmillToken

logger = logging.getLogger(__name__)


def run_windmill_job(url):
    """Trigger a Windmill job at the given API endpoint URL.

    Args:
        url: Full Windmill API URL for the job to trigger.
    """
    logger.debug("run_windmill_job: url=%s", url)
    # Build bearer-auth headers required by the Windmill API.
    headers = {
        "Authorization": f"Bearer {windmillToken}",
        "Content-Type": "application/json",
    }
    logger.debug("run_windmill_job: headers built, token present=%s", bool(windmillToken))
    # POST with an empty JSON body to start the job.
    logger.info("run_windmill_job: sending POST to %s", url)
    response = requests.post(url, headers=headers, json={})
    logger.debug("run_windmill_job: response status=%s", response.status_code)
    logger.info("Windmill job complete — status: %s, response: %s", response.status_code, response.text)
