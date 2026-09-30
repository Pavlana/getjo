"""Fetch job postings from an Ashby job board, normalised to the shared Job shape."""

from datetime import datetime, timezone

from core.http import get_with_retry

JOB_BOARD_API = "https://api.ashbyhq.com/posting-api/job-board"


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
    response = get_with_retry(url, label="ashby")
    return parse_jobs(company, response.json())
