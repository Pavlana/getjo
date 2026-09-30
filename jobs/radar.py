"""Fetch -> filter -> store -> notify: the main job-radar run."""

import argparse
import logging
from datetime import datetime, timezone

from core import config, notify, store
from sources import greenhouse, lever

logger = logging.getLogger(__name__)

FETCHERS = {"greenhouse": greenhouse.fetch_jobs, "lever": lever.fetch_jobs}


def matches_filter(job: dict, filter_cfg: dict) -> bool:
    """Title must hit an include keyword and no exclude keyword; location must hit one keyword."""
    title = job["title"].lower()
    location = (job["location"] or "").lower()

    if not any(kw.lower() in title for kw in filter_cfg["title_include"]):
        return False
    if any(kw.lower() in title for kw in filter_cfg["title_exclude"]):
        return False
    if not any(loc.lower() in location for loc in filter_cfg["locations"]):
        return False
    return True


def _fetch_matches(targets: list[dict], filter_cfg: dict) -> tuple[list[dict], list[str], int]:
    """Fetch every target with a supported, configured source. Return (matches, errors, fetched)."""
    matches = []
    errors = []
    fetched = 0
    for company in targets:
        name, source, board = company["name"], company["source"], company["board"]
        fetcher = FETCHERS.get(source)
        if not fetcher or not board:
            logger.info("skipping %s: source %r not yet supported or board not set", name, source)
            continue
        try:
            jobs = fetcher(name, board)
        except Exception as e:  # one source failing must not stop the run
            logger.warning("fetch failed for %s: %s", name, e)
            errors.append(f"{name}: {e}")
            continue
        fetched += len(jobs)
        matches.extend(job for job in jobs if matches_filter(job, filter_cfg))
    return matches, errors, fetched


def run(dry_run: bool = False) -> None:
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = config.load_config()
    matches, errors, fetched = _fetch_matches(cfg["targets"], cfg["profile"]["filter"])

    if dry_run:
        print(f"dry run: {fetched} jobs fetched, {len(matches)} match the filter")
        for job in matches:
            print(f"  {job['title']} — {job['company']} ({job['location']}) {job['url']}")
        return

    env = config.require_env(["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
    conn = store.connect()
    new_jobs = [job for job in matches if store.upsert_job(conn, job)]

    for job in new_jobs:
        text = f"{job['title']} — {job['company']} ({job['location']})\n{job['url']}"
        notify.send_telegram(text, token=env["TELEGRAM_BOT_TOKEN"], chat_id=env["TELEGRAM_CHAT_ID"])

    finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.record_run(
        conn,
        started_at=started_at,
        finished_at=finished_at,
        fetched=fetched,
        new_jobs=len(new_jobs),
        notified=len(new_jobs),
        errors="\n".join(errors) or None,
    )
    conn.close()
    logger.info(
        "run complete: fetched=%d matched=%d new=%d notified=%d",
        fetched, len(matches), len(new_jobs), len(new_jobs),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Fetch, filter, store and notify new job matches.")
    parser.add_argument("--dry-run", action="store_true", help="print matches, send nothing, store nothing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
