"""Fetch job postings from an Eightfold careers site (e.g. Microsoft's), normalised to the shared Job shape.

Eightfold has no documented public API; this uses the JSON endpoints its careers pages call: a
search (10 positions per page, no description) and a details request per position. Details are
fetched only for titles the caller wants (the radar's title filter).
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlencode

from core.http import get_with_retry
from sources.html_text import html_to_text

logger = logging.getLogger(__name__)


def _site(board: str) -> tuple[str, str]:
    """Split a board like "apply.careers.microsoft.com/microsoft.com" into (API base URL, domain)."""
    host, domain = board.split("/", 1)
    return f"https://{host}/api/pcsx", domain


def parse_position(company: str, raw: dict, board: str, now: str) -> dict:
    """A position as listed: no description yet."""
    host = board.split("/", 1)[0]
    location = "; ".join(raw.get("locations") or [])
    if raw.get("workLocationOption") == "remote":
        location = f"{location}, Remote" if location else "Remote"
    return {
        "id": f"eightfold:{company}:{raw.get('displayJobId') or raw['id']}",
        "source": "eightfold",
        "company": company,
        "title": raw.get("name", ""),
        "location": location,
        "url": f"https://{host}{raw.get('positionUrl', '')}",
        "description": "",
        "first_seen": now,
        "score": None,
    }


def add_details(job: dict, detail: dict) -> dict:
    """Fill in the public URL and the plain-text description from a position's details response."""
    info = detail["data"]
    return {**job, "url": info.get("publicUrl") or job["url"], "description": html_to_text(info.get("jobDescription") or "")}


def fetch_jobs(company: str, board: str, wanted: Callable[[str], bool], search: str = "") -> list[dict]:
    """Every position the site lists for location `search` (e.g. "London, United Kingdom");
    details only for titles where wanted(title)."""
    api, domain = _site(board)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    listed, start, total = [], 0, None
    while total is None or start < total:
        params = {"domain": domain, "query": "", "location": search, "start": start}
        data = get_with_retry(f"{api}/search?{urlencode(params)}", label="eightfold").json()["data"]
        total = data["count"]
        if not data["positions"]:
            break
        listed += data["positions"]
        start += len(data["positions"])

    jobs = []
    for raw in listed:
        job = parse_position(company, raw, board, now)
        if wanted(job["title"]):
            params = {"position_id": raw["id"], "domain": domain}
            try:
                job = add_details(job, get_with_retry(f"{api}/position_details?{urlencode(params)}", label="eightfold").json())
            except Exception as e:  # e.g. closed between search and details; try again next run
                logger.warning("eightfold details failed for %s %s: %s", company, raw["id"], e)
                continue
        jobs.append(job)
    return jobs
