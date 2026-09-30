"""Fetch job postings from an Ashby job board, normalised to the shared Job shape."""

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

JOB_BOARD_API = "https://api.ashbyhq.com/posting-api/job-board"
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
            logger.warning("ashby request failed (%s), retrying in %.0fs", e, delay)
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code == 200:
            return response
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            logger.warning(
                "ashby returned %d, retrying in %.0fs (attempt %d/%d)",
                response.status_code, delay, attempt, MAX_RETRIES,
            )
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()  # non-retryable 4xx
    raise RuntimeError("unreachable")  # loop always returns or raises


def parse_jobs(company: str, payload: dict) -> list[dict]:
    """Normalise an Ashby job board payload into the shared Job shape."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs = []
    for raw in payload.get("jobs", []):
        jobs.append({
            "id": f"ashby:{company}:{raw['id']}",
            "source": "ashby",
            "company": company,
            "title": raw.get("title", ""),
            "location": raw.get("location", ""),
            "url": raw.get("jobUrl", ""),
            "description": raw.get("descriptionPlain", ""),
            "first_seen": now,
            "score": None,
        })
    return jobs


def fetch_jobs(company: str, board: str) -> list[dict]:
    """Fetch and normalise all open jobs for one company's Ashby board."""
    url = f"{JOB_BOARD_API}/{board}"
    response = _get_with_retry(url)
    return parse_jobs(company, response.json())
