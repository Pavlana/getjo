"""Fetch UK tech jobs from DevITjobs.uk, normalised to the shared Job shape.

Two requests, joined on the job's page slug: the official RSS feed has the full description but no
location; the JSON list the site itself uses has title, company, city and work pattern but no
description. Feed items with no match in the list are dropped, since the location filter can't judge them.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from core.http import get_with_retry
from core.match import names_any
from sources.html_text import html_to_text

logger = logging.getLogger(__name__)

RSS_URL = "https://devitjobs.uk/rss"
LIST_URL = "https://devitjobs.uk/api/jobsLight"
JOB_URL = "https://devitjobs.uk/jobs"


def _slug(link: str) -> str:
    """https://devitjobs.uk/jobs/<slug>?utm_source=... -> <slug>"""
    return link.split("/jobs/", 1)[1].split("?", 1)[0]


def descriptions_by_slug(rss_xml: str) -> dict[str, str]:
    """Plain-text description of every RSS item, keyed by its page slug."""
    channel = ET.fromstring(rss_xml).find("channel")
    return {
        _slug(item.findtext("link", "")): html_to_text(item.findtext("description", ""))
        for item in channel.findall("item")
        if "/jobs/" in item.findtext("link", "")
    }


def _location(raw: dict) -> str:
    """ "London, United Kingdom" or "United Kingdom, Remote": the board is UK-only, and remote roles
    say so for the filter."""
    city = (raw.get("actualCity") or "").strip()
    parts = [city] if city and city.lower() not in ("remote", "united kingdom") else []
    parts.append("United Kingdom")
    if raw.get("workplace") == "remote":
        parts.append("Remote")
    return ", ".join(parts)


def parse_job(raw: dict, description: str, now: str) -> dict:
    return {
        "id": f"devitjobs:{raw['company']}:{raw['_id']}",
        "source": "devitjobs",
        "company": raw["company"],
        "title": raw.get("name", ""),
        "location": _location(raw),
        "url": f"{JOB_URL}/{raw['jobUrl']}",
        "description": description,
        "first_seen": now,
        "score": None,
    }


def fetch_jobs(skip_employers: list[str] = ()) -> list[dict]:
    """Every job present in both the feed and the list, except those from `skip_employers`."""
    descriptions = descriptions_by_slug(get_with_retry(RSS_URL, label="devitjobs").text)
    listed = get_with_retry(LIST_URL, label="devitjobs").json()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    jobs = [
        parse_job(raw, descriptions[raw["jobUrl"]], now)
        for raw in listed
        if raw.get("jobUrl") in descriptions and not names_any(raw.get("company", ""), list(skip_employers))
    ]
    unmatched = len(descriptions.keys() - {raw.get("jobUrl") for raw in listed})
    if unmatched:
        logger.info("devitjobs: %d feed items not in the job list (no location), skipped", unmatched)
    return jobs
