"""Fetch -> filter -> store -> score -> notify: the main job-radar run."""

import argparse
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from core import config, notify, store
from core.llm import ServiceError
from core.match import names_any
from jobs.score import load_cv, score_with_retry
from sources import amazon, ashby, devitjobs, eightfold, greenhouse, lever, reed, smartrecruiters, workable, workday

logger = logging.getLogger(__name__)

FETCHERS = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
    "workable": workable.fetch_jobs,
    "workday": workday.fetch_jobs,
    "smartrecruiters": smartrecruiters.fetch_jobs,
    "amazon": amazon.fetch_jobs,
    "eightfold": eightfold.fetch_jobs,
}
# Sources that need one extra request per posting for its description: they fetch details only
# for titles the filter wants, so a company with 700 postings costs a handful of extra requests.
NEEDS_TITLE_FILTER = {"workday", "smartrecruiters", "eightfold"}

MAX_SCORE_ATTEMPTS = 2  # failed runs for one job before it is left unscored for good: one retry, no more


@dataclass
class Tally:
    scored: int = 0
    failed: int = 0  # unusable output, a request the API rejected, or a failed send; tried again next run
    gave_up: int = 0  # failed for the MAX_SCORE_ATTEMPTS-th time; never tried again
    notified: int = 0
    cost: float = 0.0
    unpriced_calls: int = 0  # calls whose model isn't in core/llm.PRICING
    stopped: str | None = None  # why scoring stopped early, if a service error stopped it


def title_matches(title: str, filter_cfg: dict) -> bool:
    """Title names an include keyword and no exclude keyword, as whole words: "rag" mustn't match
    "coverage", and excluding "intern" mustn't drop "International ..." titles."""
    title = title.lower()
    return names_any(title, filter_cfg["title_include"]) and not names_any(title, filter_cfg["title_exclude"])


def matches_filter(job: dict, filter_cfg: dict) -> bool:
    """Title must pass title_matches. Location must name one of `locations`, or be remote and
    name one of `remote_places`."""
    if not title_matches(job["title"], filter_cfg):
        return False
    location = (job["location"] or "").lower()
    if names_any(location, filter_cfg["locations"]):
        return True
    return "remote" in location and names_any(location, filter_cfg.get("remote_places", []))


def _reachable(company: dict) -> bool:
    return company["source"] in FETCHERS and bool(company["board"])


def _own_board_employers(targets: list[dict]) -> list[str]:
    """Targets fetched from their own board. Search sources skip these employers, so the same job
    isn't found twice; targets with no readable board are kept, since a search source may be the
    only way to see their jobs."""
    return [c["name"] for c in targets if _reachable(c)]


def _fetch_reed(reed_cfg: dict | None, targets: list[dict], filter_cfg: dict, errors: list[str]) -> list[dict]:
    """Search Reed if the profile has a [reed] section and REED_API_KEY is set; otherwise skip.

    Reed is optional, unlike the Anthropic and Telegram keys, so a missing key doesn't stop the run.
    """
    if not reed_cfg:
        return []
    api_key = os.environ.get("REED_API_KEY")
    if not api_key:
        logger.info("skipping reed: REED_API_KEY not set")
        return []
    try:
        return reed.fetch_jobs(
            reed_cfg["keywords"], reed_cfg["location"], api_key,
            wanted=lambda title: title_matches(title, filter_cfg),
            direct_employers_only=reed_cfg.get("direct_employers_only", True),
            skip_employers=_own_board_employers(targets) + reed_cfg.get("exclude_employers", []),
        )
    except Exception as e:  # one source failing must not stop the run
        logger.warning("fetch failed for reed: %s", e)
        errors.append(f"reed: {e}")
        return []


def _fetch_devitjobs(cfg: dict | None, targets: list[dict], errors: list[str]) -> list[dict]:
    """Read DevITjobs.uk if the profile has a [devitjobs] section with enabled = true."""
    if not (cfg and cfg.get("enabled")):
        return []
    try:
        return devitjobs.fetch_jobs(skip_employers=_own_board_employers(targets) + cfg.get("exclude_employers", []))
    except Exception as e:  # one source failing must not stop the run
        logger.warning("fetch failed for devitjobs: %s", e)
        errors.append(f"devitjobs: {e}")
        return []


def _fetch_matches(targets: list[dict], profile: dict) -> tuple[list[dict], list[str], int]:
    """Fetch every target with a supported, configured source, then the search sources (Reed,
    DevITjobs). Return (matches, errors, fetched)."""
    filter_cfg = profile["filter"]
    matches = []
    errors = []
    fetched = 0
    for company in targets:
        name, source, board = company["name"], company["source"], company["board"]
        fetcher = FETCHERS.get(source)
        if not _reachable(company):
            logger.info("skipping %s: source %r not yet supported or board not set", name, source)
            continue
        try:
            if source in NEEDS_TITLE_FILTER:
                # `search` (Workday, Eightfold) narrows the listing on the board itself, for very large employers.
                extra = {"search": company["search"]} if company.get("search") else {}
                jobs = fetcher(name, board, wanted=lambda title: title_matches(title, filter_cfg), **extra)
            else:
                jobs = fetcher(name, board)
        except Exception as e:  # one source failing must not stop the run
            logger.warning("fetch failed for %s: %s", name, e)
            errors.append(f"{name}: {e}")
            continue
        fetched += len(jobs)
        matches.extend(job for job in jobs if matches_filter(job, filter_cfg))

    for jobs in (
        _fetch_reed(profile.get("reed"), targets, filter_cfg, errors),
        _fetch_devitjobs(profile.get("devitjobs"), targets, errors),
    ):
        fetched += len(jobs)
        matches.extend(job for job in jobs if matches_filter(job, filter_cfg))
    return matches, errors, fetched


def _message(job: dict, result: dict) -> str:
    # Plain text: Telegram's Markdown/HTML modes reject a title containing a stray _ or *.
    place = f"{job['company']} · {job['location']}" if job["location"] else job["company"]
    top = (result["reasons"] or result["red_flags"] or ["(no reason given)"])[0]
    return f"{result['score']}/10 · {job['title']}\n{place}\n{top}\n{job['url']}"


SUMMARY_HEADER = "job-radar run"
SUMMARY_MAX_ERRORS = 3  # error lines quoted in the summary; the full list is in runs.errors
SUMMARY_MAX_ERROR_CHARS = 200


def _summary(fetched: int, matched: int, new: int, tally: Tally, cost: str, errors: list[str]) -> str:
    """One message per run, sent even when nothing is new, so a missing message means the run broke."""
    lines = [
        f"{SUMMARY_HEADER}: {fetched} fetched · {matched} matched · {new} new · "
        f"{tally.scored} scored · {tally.notified} sent · {cost}",
    ]
    if tally.stopped:
        lines.append(f"Scoring stopped early: {tally.stopped}")
    if errors:
        lines.append(f"{len(errors)} errors:")
        lines += [f"- {e[:SUMMARY_MAX_ERROR_CHARS]}" for e in errors[:SUMMARY_MAX_ERRORS]]
        if len(errors) > SUMMARY_MAX_ERRORS:
            lines.append(f"…and {len(errors) - SUMMARY_MAX_ERRORS} more (see runs.errors)")
    else:
        lines.append("No errors.")
    return "\n".join(lines)


def _score(
    job: dict, cv_text: str, scoring_cfg: dict, env: dict[str, str], errors: list[str], tally: Tally
) -> dict | None:
    """Score one job and add its cost to the tally. Returns the result, or None if this run
    couldn't score it (logged). A ServiceError (the API can't serve anyone) is raised to the caller,
    which stops scoring."""
    try:
        result, completions = score_with_retry(
            job, cv_text, scoring_cfg["rubric"], scoring_cfg.get("dealbreakers", []),
            model=scoring_cfg["model"], api_key=env["ANTHROPIC_API_KEY"],
            facts=scoring_cfg.get("candidate_facts", []),
        )
    except ServiceError:
        raise
    except Exception as e:  # one job failing must not stop the run
        logger.warning("scoring failed for %s: %s", job["id"], e)
        errors.append(f"score {job['id']}: {e}")
        return None

    for completion in completions:
        if completion.cost is None:
            tally.unpriced_calls += 1
        else:
            tally.cost += completion.cost
    return result


def _send(job: dict, result: dict, env: dict[str, str], errors: list[str]) -> bool:
    try:
        notify.send_telegram(_message(job, result), token=env["TELEGRAM_BOT_TOKEN"], chat_id=env["TELEGRAM_CHAT_ID"])
    except Exception as e:
        logger.warning("notify failed for %s: %s", job["id"], e)
        errors.append(f"notify {job['id']}: {e}")
        return False
    return True


def _count_failure(conn: sqlite3.Connection, job: dict, tally: Tally) -> None:
    """One more failed try for this job; after MAX_SCORE_ATTEMPTS it is left unscored for good."""
    attempt = store.add_score_attempt(conn, job["id"])
    if attempt >= MAX_SCORE_ATTEMPTS:
        logger.warning("giving up on %s after %d tries", job["id"], attempt)
        tally.gave_up += 1
    else:
        tally.failed += 1


def _score_and_notify(
    conn: sqlite3.Connection, matches: list[dict], scoring_cfg: dict, env: dict[str, str], errors: list[str]
) -> Tally:
    """Score every matching job that has no score yet and tries left, then send those at or above
    the threshold to Telegram, highest score first, so the best matches lead.

    A score is written only after its send succeeds: if Telegram fails, the job stays unscored and
    is tried again next run instead of being stored as scored but never delivered. A job is notified
    only when its score goes from NULL to a number, and a scored job is never scored again, so no
    job is notified twice. A run in which a job itself fails (unusable reply, rejected request,
    failed send) counts as one try; after MAX_SCORE_ATTEMPTS the job is left unscored for good,
    which caps what a job that never scores can cost. A service error (no credit, bad key, API down)
    stops scoring for this run and counts against no job; jobs already scored are still sent.
    """
    cv_text = load_cv()
    tally = Tally()
    pending = [job for job in matches if _needs_scoring(conn, job)]
    to_send = []
    for done, job in enumerate(pending):
        try:
            result = _score(job, cv_text, scoring_cfg, env, errors, tally)
        except ServiceError as e:
            tally.stopped = str(e)
            logger.error("scoring stopped: %s; %d jobs left for the next run", e, len(pending) - done)
            errors.append(f"scoring stopped: {e}")
            break
        if result is None:
            _count_failure(conn, job, tally)
        elif result["score"] >= scoring_cfg["notify_threshold"]:
            to_send.append((job, result))
        else:
            store.set_score(conn, job["id"], result["score"])
            tally.scored += 1

    for job, result in sorted(to_send, key=lambda pair: -pair[1]["score"]):  # stable: ties keep their order
        if _send(job, result, env, errors):
            store.set_score(conn, job["id"], result["score"])
            tally.scored += 1
            tally.notified += 1
        else:
            _count_failure(conn, job, tally)
    return tally


def _needs_scoring(conn: sqlite3.Connection, job: dict) -> bool:
    score, attempts = store.get_scoring_state(conn, job["id"])
    return score is None and attempts < MAX_SCORE_ATTEMPTS


def run(dry_run: bool = False) -> bool:
    """Run once. Returns False if scoring had to stop early because of a service error."""
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = config.load_config()
    matches, errors, fetched = _fetch_matches(cfg["targets"], cfg["profile"])

    if dry_run:
        print(f"dry run: {fetched} jobs fetched, {len(matches)} match the filter")
        for job in matches:
            print(f"  {job['title']} — {job['company']} ({job['location']}) {job['url']}")
        return True

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
        "run complete: fetched=%d matched=%d new=%d scored=%d failed=%d gave_up=%d notified=%d cost=%s%s",
        fetched, len(matches), new_count, tally.scored, tally.failed, tally.gave_up, tally.notified, cost,
        " (scoring stopped early)" if tally.stopped else "",
    )

    summary = _summary(fetched, len(matches), new_count, tally, cost, errors)
    try:
        notify.send_telegram(summary, token=env["TELEGRAM_BOT_TOKEN"], chat_id=env["TELEGRAM_CHAT_ID"])
    except Exception as e:  # the run's work is done and recorded; a lost summary shows up as silence
        logger.warning("summary send failed: %s", e)
    return tally.stopped is None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Fetch, filter, store, score and notify new job matches.")
    parser.add_argument("--dry-run", action="store_true", help="print matches; no database, LLM or Telegram")
    args = parser.parse_args()
    # A non-zero exit lets a scheduler or alert notice that scoring couldn't finish.
    sys.exit(0 if run(dry_run=args.dry_run) else 1)


if __name__ == "__main__":
    main()
