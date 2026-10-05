"""Fetch job postings from a Workday careers site, normalised to the shared Job shape.

Workday has no documented public API. This uses the JSON endpoints its own careers pages call:
a POST that lists postings (title, path, a location summary) and a GET per posting for details.
They can change without notice; a changed shape shows up as a fetch error for that company.

The list says "4 Locations" for multi-site roles and has no description, so details are fetched
only for titles the caller wants (the radar's title filter); other postings are returned as listed.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from core.http import get_with_retry, post_with_retry
from sources.html_text import html_to_text

logger = logging.getLogger(__name__)

PAGE_SIZE = 20  # the most Workday returns per request
LISTING_CAP = 2000  # Workday never reports or pages past this many postings


def _site(board: str) -> tuple[str, str, str]:
    """Split a board like "kainos.wd3/Kainos" into (base URL, tenant, site)."""
    host, site = board.split("/", 1)
    return f"https://{host}.myworkdayjobs.com", host.split(".")[0], site


def _job_id(raw: dict) -> str:
    """The requisition ID (the first bullet field on every tenant checked), else the posting path."""
    return (raw.get("bulletFields") or [raw["externalPath"]])[0]


def parse_listing(company: str, raw: dict, board: str, now: str) -> dict:
    """A posting as listed: no description, location may be a summary like "4 Locations"."""
    base, _, site = _site(board)
    return {
        "id": f"workday:{company}:{_job_id(raw)}",
        "source": "workday",
        "company": company,
        "title": raw["title"],
        "location": raw.get("locationsText", ""),
        "url": f"{base}/{site}{raw['externalPath']}",
        "description": "",
        "first_seen": now,
        "score": None,
    }


def add_details(job: dict, detail: dict) -> dict:
    """Fill in every location and the plain-text description from a posting's detail response."""
    info = detail["jobPostingInfo"]
    locations = [info.get("location", "")] + (info.get("additionalLocations") or [])
    return {
        **job,
        "location": "; ".join(loc for loc in locations if loc),
        "url": info.get("externalUrl") or job["url"],
        "description": html_to_text(info.get("jobDescription", "")),
    }


def fetch_jobs(company: str, board: str, wanted: Callable[[str], bool], search: str = "") -> list[dict]:
    """Fetch all postings for one Workday site; fetch details only for titles where wanted(title).

    `search` is passed as the site's own search text (e.g. "London"), for employers with more
    postings than Workday will list.
    """
    base, tenant, site = _site(board)
    api = f"{base}/wday/cxs/{tenant}/{site}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    listed, offset, total = [], 0, None
    while total is None or offset < total:
        page = post_with_retry(
            f"{api}/jobs", {"limit": PAGE_SIZE, "offset": offset, "searchText": search, "appliedFacets": {}},
            label="workday",
        ).json()
        if total is None:
            total = page["total"]  # later pages can report 0
            if total >= LISTING_CAP:
                logger.warning("workday %s: %d+ postings, only the first %d can be listed; set `search` "
                               "for this target in targets.toml", company, total, LISTING_CAP)
        if not page["jobPostings"]:
            break
        listed += page["jobPostings"]
        offset += PAGE_SIZE

    jobs = []
    for raw in listed:
        if "title" not in raw:  # seen on Visa's site: an entry with only a reference number
            continue
        job = parse_listing(company, raw, board, now)
        if wanted(job["title"]):
            try:
                job = add_details(job, get_with_retry(f"{api}{raw['externalPath']}", label="workday").json())
            except Exception as e:  # e.g. closed between list and detail; try again next run
                logger.warning("workday detail failed for %s %s: %s", company, raw["externalPath"], e)
                continue
        jobs.append(job)
    return jobs
