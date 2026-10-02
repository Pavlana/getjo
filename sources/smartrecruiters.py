"""Fetch job postings from a SmartRecruiters company, normalised to the shared Job shape.

The public postings API lists postings without descriptions, so details (one GET per posting)
are fetched only for titles the caller wants (the radar's title filter).
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from core.http import get_with_retry
from sources.html_text import html_to_text

logger = logging.getLogger(__name__)

POSTINGS_API = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100  # the most the API returns per request


def _location(loc: dict) -> str:
    """ "London, , United Kingdom" -> "London, United Kingdom"; remote roles say so, for the filter."""
    parts = [p.strip() for p in (loc.get("fullLocation") or "").split(",") if p.strip()]
    if loc.get("remote"):
        parts.append("Remote")
    return ", ".join(parts)


def parse_listing(company: str, raw: dict, board: str, now: str) -> dict:
    """A posting as listed: no description yet."""
    return {
        "id": f"smartrecruiters:{company}:{raw['id']}",
        "source": "smartrecruiters",
        "company": company,
        "title": raw.get("name", ""),
        "location": _location(raw.get("location") or {}),
        "url": f"https://jobs.smartrecruiters.com/{board}/{raw['id']}",
        "description": "",
        "first_seen": now,
        "score": None,
    }


def add_details(job: dict, detail: dict) -> dict:
    """Fill in the public URL and the description: every section of the job ad, as plain text."""
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    text = " ".join(html_to_text(s.get("text", "")) for s in sections.values())
    return {**job, "url": detail.get("postingUrl") or job["url"], "description": text.strip()}


def fetch_jobs(company: str, board: str, wanted: Callable[[str], bool]) -> list[dict]:
    """Fetch all postings for one SmartRecruiters company; details only for titles where wanted(title)."""
    api = f"{POSTINGS_API}/{board}/postings"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    listed, offset, total = [], 0, None
    while total is None or offset < total:
        page = get_with_retry(f"{api}?limit={PAGE_SIZE}&offset={offset}", label="smartrecruiters").json()
        total = page["totalFound"]
        if not page["content"]:
            break
        listed += page["content"]
        offset += PAGE_SIZE

    jobs = []
    for raw in listed:
        job = parse_listing(company, raw, board, now)
        if wanted(job["title"]):
            try:
                job = add_details(job, get_with_retry(f"{api}/{raw['id']}", label="smartrecruiters").json())
            except Exception as e:  # e.g. closed between list and detail; try again next run
                logger.warning("smartrecruiters detail failed for %s %s: %s", company, raw["id"], e)
                continue
        jobs.append(job)
    return jobs
