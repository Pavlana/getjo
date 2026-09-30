"""Fetch job postings from a Greenhouse job board, normalised to the shared Job shape."""

import logging
import time
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

import requests

logger = logging.getLogger(__name__)

BOARDS_API = "https://boards-api.greenhouse.io/v1/boards"
TIMEOUT = 10
MAX_RETRIES = 5
BACKOFF_BASE = 1.0  # seconds; doubles each retry, so 1, 2, 4, 8, 16


class _TextExtractor(HTMLParser):
    """Collects the plain-text content of an HTML fragment, tags dropped."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _strip_html(html_content: str) -> str:
    """Convert Greenhouse's (entity-escaped) HTML content field to plain text."""
    parser = _TextExtractor()
    parser.feed(unescape(html_content))
    return " ".join(parser.text().split())


def _get_with_retry(url: str) -> requests.Response:
    """GET with a timeout; retry on 429/5xx with exponential backoff, capped."""
    delay = BACKOFF_BASE
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=TIMEOUT)
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("greenhouse request failed (%s), retrying in %.0fs", e, delay)
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code == 200:
            return response
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            logger.warning(
                "greenhouse returned %d, retrying in %.0fs (attempt %d/%d)",
                response.status_code, delay, attempt, MAX_RETRIES,
            )
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()  # non-retryable 4xx
    raise RuntimeError("unreachable")  # loop always returns or raises


def parse_jobs(company: str, payload: dict) -> list[dict]:
    """Normalise a Greenhouse jobs payload into the shared Job shape."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs = []
    for raw in payload.get("jobs", []):
        location = (raw.get("location") or {}).get("name", "")
        jobs.append({
            "id": f"greenhouse:{company}:{raw['id']}",
            "source": "greenhouse",
            "company": company,
            "title": raw.get("title", ""),
            "location": location,
            "url": raw.get("absolute_url", ""),
            "description": _strip_html(raw.get("content", "")),
            "first_seen": now,
            "score": None,
        })
    return jobs


def fetch_jobs(company: str, board: str) -> list[dict]:
    """Fetch and normalise all open jobs for one company's Greenhouse board."""
    url = f"{BOARDS_API}/{board}/jobs?content=true"
    response = _get_with_retry(url)
    return parse_jobs(company, response.json())
