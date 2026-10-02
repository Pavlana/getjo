"""Search Reed.co.uk for jobs, normalised to the shared Job shape.

Unlike the board sources, this searches by keyword across all employers. Search results carry a
~450-character excerpt, so the full description (one GET per job) is fetched only for titles the
caller wants. Employers already fetched from their own board are skipped, so a job isn't found twice.
"""

import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlencode

from core.http import get_with_retry
from sources.html_text import html_to_text

logger = logging.getLogger(__name__)

API = "https://www.reed.co.uk/api/1.0"
PAGE_SIZE = 100  # the most Reed returns per request


def _names_any(text: str, names: list[str]) -> bool:
    """True if text contains any name as a whole word or phrase, so "Wise" doesn't match "Otherwise"."""
    text = text.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", text) for n in names)


def _location(location_name: str, searched: str) -> str:
    """Reed sometimes gives a postcode ("WC1B5HA"); the search already limited results to near
    `searched`, so say so, or the location filter would drop them."""
    if _names_any(location_name, [searched]):
        return location_name
    return f"{location_name}, {searched}" if location_name else searched


def parse_result(raw: dict, searched: str, now: str) -> dict:
    """A search result: the description is only an excerpt until add_details."""
    return {
        "id": f"reed:{raw['employerName']}:{raw['jobId']}",
        "source": "reed",
        "company": raw["employerName"],
        "title": raw.get("jobTitle", ""),
        "location": _location(raw.get("locationName") or "", searched),
        "url": raw.get("jobUrl", ""),
        "description": "",
        "first_seen": now,
        "score": None,
    }


def add_details(job: dict, detail: dict) -> dict:
    """Fill in the full description from the job's details response."""
    return {**job, "description": html_to_text(detail.get("jobDescription") or "")}


def _search(keyword: str, location: str, direct_only: bool, auth: tuple[str, str]) -> list[dict]:
    """Every result for one keyword, page by page."""
    results, skip, total = [], 0, None
    while total is None or skip < total:
        params = {"keywords": keyword, "locationName": location, "resultsToTake": PAGE_SIZE, "resultsToSkip": skip}
        if direct_only:
            params["postedByDirectEmployer"] = "true"
        page = get_with_retry(f"{API}/search?{urlencode(params)}", label="reed", auth=auth).json()
        total = page["totalResults"]
        if not page["results"]:
            break
        results += page["results"]
        skip += PAGE_SIZE
    return results


def fetch_jobs(
    keywords: list[str], location: str, api_key: str, wanted: Callable[[str], bool],
    *, direct_employers_only: bool = True, skip_employers: list[str] = (),
) -> list[dict]:
    """Search every keyword near `location`; one job per Reed job ID, however many keywords found it.

    Results from `skip_employers` (target companies, fetched from their own boards, and employers
    excluded in the profile) are dropped before any details request.
    """
    auth = (api_key, "")  # Reed takes the key as the Basic auth username, password empty
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    found: dict[int, dict] = {}
    for keyword in keywords:
        for raw in _search(keyword, location, direct_employers_only, auth):
            found.setdefault(raw["jobId"], raw)

    jobs = []
    for job_id, raw in found.items():
        if _names_any(raw["employerName"], list(skip_employers)):
            continue
        job = parse_result(raw, location, now)
        if wanted(job["title"]):
            try:
                job = add_details(job, get_with_retry(f"{API}/jobs/{job_id}", label="reed", auth=auth).json())
            except Exception as e:  # e.g. expired between search and details; try again next run
                logger.warning("reed details failed for %s: %s", job_id, e)
                continue
        jobs.append(job)
    return jobs
