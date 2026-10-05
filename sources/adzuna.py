"""Search Adzuna for job ads, for discovering companies (not as a job source).

Results carry only a 500-character excerpt, too short for scoring, so this returns just
company, title and location. Adzuna takes its app ID and key in the URL, so both are redacted
from log lines and errors; each result's redirect_url also contains the app ID and isn't kept.
"""

from urllib.parse import urlencode

from core.http import get_with_retry

API = "https://api.adzuna.com/v1/api/jobs/gb/search"
PAGE_SIZE = 50  # the most Adzuna returns per request
MAX_PAGES = 4  # per keyword: the 200 newest results, so one report stays well within the free quota


def search(keyword: str, location: str, app_id: str, app_key: str, *, max_days_old: int = 30) -> list[dict]:
    """Ads whose title matches `keyword` near `location`, as {company, title, location}."""
    found = []
    for page in range(1, MAX_PAGES + 1):
        params = {
            "app_id": app_id, "app_key": app_key, "what": keyword, "title_only": keyword,
            "where": location, "results_per_page": PAGE_SIZE, "max_days_old": max_days_old,
        }
        data = get_with_retry(f"{API}/{page}?{urlencode(params)}", label="adzuna", redact=(app_id, app_key)).json()
        found += [
            {
                "company": (raw.get("company") or {}).get("display_name", ""),
                "title": raw.get("title", ""),
                "location": (raw.get("location") or {}).get("display_name", ""),
            }
            for raw in data["results"]
        ]
        if page * PAGE_SIZE >= data["count"] or not data["results"]:
            break
    return found
