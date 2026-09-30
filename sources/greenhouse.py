"""Fetch job postings from a Greenhouse job board, normalised to the shared Job shape."""

from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

from core.http import get_with_retry

BOARDS_API = "https://boards-api.greenhouse.io/v1/boards"


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
