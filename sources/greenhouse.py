"""Fetch job postings from a Greenhouse job board, normalised to the shared Job shape."""

from datetime import datetime, timezone
from html import unescape

from core.http import get_with_retry
from sources.html_text import html_to_text

BOARDS_API = "https://boards-api.greenhouse.io/v1/boards"


def _strip_html(html_content: str) -> str:
    """Convert Greenhouse's content field to plain text: it is entity-escaped on top of being HTML."""
    return html_to_text(unescape(html_content))


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
    response = get_with_retry(url, label="greenhouse")
    return parse_jobs(company, response.json())
