"""Fetch -> filter -> store -> score -> notify: the main job-radar run."""

import argparse
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from core import config, notify, store
from jobs.score import load_cv, score_with_retry
from sources import ashby, greenhouse, lever

logger = logging.getLogger(__name__)

FETCHERS = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
}

MAX_SCORE_ATTEMPTS = 3  # runs that may try to score one job before it is left unscored for good


@dataclass
class Tally:
    scored: int = 0
    failed: int = 0  # unusable output, API error or failed send; tried again next run
    gave_up: int = 0  # failed for the MAX_SCORE_ATTEMPTS-th time; never tried again
    notified: int = 0
    cost: float = 0.0
    unpriced_calls: int = 0  # calls whose model isn't in core/llm.PRICING


def _names_any(text: str, terms: list[str]) -> bool:
    """True if text contains any term as a whole word or phrase, so "us" doesn't match "australia"."""
    return any(re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text) for term in terms)


def matches_filter(job: dict, filter_cfg: dict) -> bool:
    """Title must hit an include keyword and no exclude keyword. Location must name one of
    `locations`, or be remote and name one of `remote_places`."""
    title = job["title"].lower()
    location = (job["location"] or "").lower()

    if not any(kw.lower() in title for kw in filter_cfg["title_include"]):
        return False
    if any(kw.lower() in title for kw in filter_cfg["title_exclude"]):
        return False
    if _names_any(location, filter_cfg["locations"]):
        return True
    return "remote" in location and _names_any(location, filter_cfg.get("remote_places", []))


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


def _message(job: dict, result: dict) -> str:
    # Plain text: Telegram's Markdown/HTML modes reject a title containing a stray _ or *.
    place = f"{job['company']} · {job['location']}" if job["location"] else job["company"]
    top = (result["reasons"] or result["red_flags"] or ["(no reason given)"])[0]
    return f"{result['score']}/10 · {job['title']}\n{place}\n{top}\n{job['url']}"


def _score_one(
    conn: sqlite3.Connection, job: dict, cv_text: str, scoring_cfg: dict,
    env: dict[str, str], errors: list[str], tally: Tally,
) -> bool:
    """Score one job and notify if it clears the threshold. Returns True if the score was stored.

    The score is written after the send succeeds: if Telegram fails, the job stays unscored
    and is tried again next run instead of being stored as scored but never delivered.
    """
    try:
        result, completions = score_with_retry(
            job, cv_text, scoring_cfg["rubric"], scoring_cfg.get("dealbreakers", []),
            model=scoring_cfg["model"], api_key=env["ANTHROPIC_API_KEY"],
            facts=scoring_cfg.get("candidate_facts", []),
        )
    except Exception as e:  # one job failing must not stop the run
        logger.warning("scoring failed for %s: %s", job["id"], e)
        errors.append(f"score {job['id']}: {e}")
        return False

    for completion in completions:
        if completion.cost is None:
            tally.unpriced_calls += 1
        else:
            tally.cost += completion.cost

    if result is None:
        return False

    if result["score"] >= scoring_cfg["notify_threshold"]:
        try:
            notify.send_telegram(
                _message(job, result), token=env["TELEGRAM_BOT_TOKEN"], chat_id=env["TELEGRAM_CHAT_ID"]
            )
        except Exception as e:
            logger.warning("notify failed for %s: %s", job["id"], e)
            errors.append(f"notify {job['id']}: {e}")
            return False
        tally.notified += 1

    store.set_score(conn, job["id"], result["score"])
    return True


def _score_and_notify(
    conn: sqlite3.Connection, matches: list[dict], scoring_cfg: dict, env: dict[str, str], errors: list[str]
) -> Tally:
    """Score every matching job that has no score yet and tries left; notify those above the threshold.

    A job is notified only when its score goes from NULL to a number, and a scored job is never
    scored again, so no job is notified twice. Every run that tries a job counts as one attempt,
    whatever the outcome; after MAX_SCORE_ATTEMPTS the job is left unscored for good, which caps
    what a job that never scores can cost.
    """
    cv_text = load_cv()
    tally = Tally()
    for job in matches:
        score, attempts = store.get_scoring_state(conn, job["id"])
        if score is not None or attempts >= MAX_SCORE_ATTEMPTS:
            continue
        attempt = store.add_score_attempt(conn, job["id"])
        if _score_one(conn, job, cv_text, scoring_cfg, env, errors, tally):
            tally.scored += 1
        elif attempt >= MAX_SCORE_ATTEMPTS:
            logger.warning("giving up on %s after %d tries", job["id"], attempt)
            tally.gave_up += 1
        else:
            tally.failed += 1
    return tally


def run(dry_run: bool = False) -> None:
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = config.load_config()
    matches, errors, fetched = _fetch_matches(cfg["targets"], cfg["profile"]["filter"])

    if dry_run:
        print(f"dry run: {fetched} jobs fetched, {len(matches)} match the filter")
        for job in matches:
            print(f"  {job['title']} — {job['company']} ({job['location']}) {job['url']}")
        return

    env = config.require_env(["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])
    conn = store.connect()
    new_count = sum(store.upsert_job(conn, job) for job in matches)
    tally = _score_and_notify(conn, matches, cfg["profile"]["scoring"], env, errors)

    finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.record_run(
        conn,
        started_at=started_at,
        finished_at=finished_at,
        fetched=fetched,
        new_jobs=new_count,
        notified=tally.notified,
        errors="\n".join(errors) or None,
    )
    conn.close()

    cost = f"${tally.cost:.4f}"
    if tally.unpriced_calls:
        cost += f" (+{tally.unpriced_calls} calls with unknown pricing)"
    logger.info(
        "run complete: fetched=%d matched=%d new=%d scored=%d failed=%d gave_up=%d notified=%d cost=%s",
        fetched, len(matches), new_count, tally.scored, tally.failed, tally.gave_up, tally.notified, cost,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Fetch, filter, store, score and notify new job matches.")
    parser.add_argument("--dry-run", action="store_true", help="print matches; no database, LLM or Telegram")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
