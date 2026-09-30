"""Fetch job postings from a Lever job board, normalised to the shared Job shape."""

from datetime import datetime, timezone

from core.http import get_with_retry

POSTINGS_API = "https://api.lever.co/v0/postings"


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
    response = get_with_retry(url, label="lever")
    return parse_jobs(company, response.json())
