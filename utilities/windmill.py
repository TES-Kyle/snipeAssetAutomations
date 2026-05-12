import requests
from utilities.Key import windmillToken
import logging

logger = logging.getLogger(__name__)

def run_windmill_job(url):
    headers = {
        "Authorization": f"Bearer {windmillToken}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, json={})
    logger.info(f"Job Complete with Status: {response.status_code}, Text: {response.text}")