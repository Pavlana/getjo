"""Fetch job postings from a Workable account, normalised to the shared Job shape.

The public widget API returns every posting with its description in one request.
"""

from datetime import datetime, timezone

from core.http import get_with_retry
from sources.html_text import html_to_text

WIDGET_API = "https://apply.workable.com/api/v1/widget/accounts"


def _location(raw: dict) -> str:
    """Every listed place as "city, region, country", joined by "; "; remote roles say so, for the filter."""
    places = raw.get("locations") or [{"city": raw.get("city"), "region": raw.get("state"), "country": raw.get("country")}]
    text = "; ".join(
        ", ".join(part for part in (p.get("city"), p.get("region"), p.get("country")) if part) for p in places
    )
    return f"{text}, Remote" if raw.get("telecommuting") else text


def parse_jobs(company: str, payload: dict) -> list[dict]:
    """Normalise a Workable widget payload into the shared Job shape."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        {
            "id": f"workable:{company}:{raw['shortcode']}",
            "source": "workable",
            "company": company,
            "title": raw.get("title", ""),
            "location": _location(raw),
            "url": raw.get("url", ""),
            "description": html_to_text(raw.get("description") or ""),
            "first_seen": now,
            "score": None,
        }
        for raw in payload.get("jobs", [])
    ]


def fetch_jobs(company: str, board: str) -> list[dict]:
    """Fetch and normalise all open postings for one Workable account."""
    response = get_with_retry(f"{WIDGET_API}/{board}?details=true", label="workable")
    return parse_jobs(company, response.json())
