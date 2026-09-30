"""Fetch job postings from a Lever job board, normalised to the shared Job shape."""

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

POSTINGS_API = "https://api.lever.co/v0/postings"
TIMEOUT = 10
MAX_RETRIES = 5
BACKOFF_BASE = 1.0  # seconds; doubles each retry, so 1, 2, 4, 8, 16


def _get_with_retry(url: str) -> requests.Response:
    """GET with a timeout; retry on 429/5xx with exponential backoff, capped."""
    delay = BACKOFF_BASE
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=TIMEOUT)
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("lever request failed (%s), retrying in %.0fs", e, delay)
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code == 200:
            return response
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            logger.warning(
                "lever returned %d, retrying in %.0fs (attempt %d/%d)",
                response.status_code, delay, attempt, MAX_RETRIES,
            )
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()  # non-retryable 4xx
    raise RuntimeError("unreachable")  # loop always returns or raises


def parse_jobs(company: str, payload: list) -> list[dict]:
    """Normalise a Lever postings payload into the shared Job shape."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs = []
    for raw in payload:
        location = (raw.get("categories") or {}).get("location", "")
        jobs.append({
            "id": f"lever:{company}:{raw['id']}",
            "source": "lever",
            "company": company,
            "title": raw.get("text", ""),
            "location": location,
            "url": raw.get("hostedUrl", ""),
            "description": raw.get("descriptionPlain", ""),
            "first_seen": now,
            "score": None,
        })
    return jobs


def fetch_jobs(company: str, board: str) -> list[dict]:
    """Fetch and normalise all open postings for one company's Lever board."""
    url = f"{POSTINGS_API}/{board}?mode=json"
    response = _get_with_retry(url)
    return parse_jobs(company, response.json())
