"""Fetch Amazon jobs for one country from amazon.jobs, normalised to the shared Job shape.

amazon.jobs has no documented API; this uses the JSON search its own pages call. Results include
the full description and qualifications, so one request per 100 jobs is all it takes. The search's
city filter is ignored by the site, so the whole country is listed and the radar's location filter
does the rest.
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from core.http import get_with_retry
from sources.html_text import html_to_text

SEARCH_URL = "https://www.amazon.jobs/en/search.json"
JOB_URL = "https://www.amazon.jobs"
PAGE_SIZE = 100  # the most the search returns per request


def _location(raw: dict) -> str:
    """Every listed place as "city, country", joined by "; "; remote roles say so, for the filter."""
    places, remote = [], False
    for entry in raw.get("locations") or []:
        loc = json.loads(entry)  # each entry is itself a JSON string
        places.append(", ".join(p for p in (loc.get("city"), loc.get("normalizedCountryName")) if p))
        remote = remote or loc.get("type") == "REMOTE"
    text = "; ".join(p for p in places if p) or raw.get("normalized_location", "")
    return f"{text}, Remote" if remote else text


def _description(raw: dict) -> str:
    """The job text plus its qualifications, where requirements such as travel or languages often sit."""
    parts = [
        raw.get("description") or "",
        "Basic qualifications: " + (raw.get("basic_qualifications") or ""),
        "Preferred qualifications: " + (raw.get("preferred_qualifications") or ""),
    ]
    return " ".join(html_to_text(p) for p in parts)


def parse_job(company: str, raw: dict, now: str) -> dict:
    return {
        "id": f"amazon:{company}:{raw['id_icims']}",
        "source": "amazon",
        "company": company,
        "title": raw.get("title", ""),
        "location": _location(raw),
        "url": f"{JOB_URL}{raw.get('job_path', '')}",
        "description": _description(raw),
        "first_seen": now,
        "score": None,
    }


def fetch_jobs(company: str, board: str) -> list[dict]:
    """Every Amazon job in the country `board` (an ISO 3166 alpha-3 code, e.g. "GBR")."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs, offset, total = [], 0, None
    while total is None or offset < total:
        params = {"normalized_country_code[]": board, "result_limit": PAGE_SIZE, "offset": offset}
        page = get_with_retry(f"{SEARCH_URL}?{urlencode(params)}", label="amazon").json()
        total = page["hits"]
        if not page["jobs"]:
            break
        jobs += [parse_job(company, raw, now) for raw in page["jobs"]]
        offset += PAGE_SIZE
    return jobs
