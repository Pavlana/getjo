"""Discovery report: companies hiring for matching titles that aren't targets yet, and their boards.

Run by hand (python -m jobs.discover), not on the schedule. Searches Adzuna, drops companies already
in targets.toml, guesses each remaining company's board name on the board systems that can be
queried by name alone, and prints a table plus ready-to-paste [[company]] blocks. It never edits
targets.toml: adding a company stays a decision.
"""

import logging
import re
import sys
from collections.abc import Callable

from core import config, store
from core.http import get_with_retry
from core.match import names_any
from jobs.radar import title_matches
from sources import adzuna

logger = logging.getLogger(__name__)

# Board systems whose job list can be fetched from a company's board name alone, in the order tried,
# with how to read the job titles out of the response. Not probed: Workday (also needs a tenant, server
# and site, so it can't be guessed) and Workable (rate-limits guesses with 429s, and each one then
# waits through the full retry backoff).
PROBES: list[tuple[str, str, Callable[[object], list[str]]]] = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{}/jobs", lambda d: [j["title"] for j in d["jobs"]]),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{}", lambda d: [j["title"] for j in d["jobs"]]),
    ("lever", "https://api.lever.co/v0/postings/{}?mode=json", lambda d: [j["text"] for j in d]),
    ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{}/postings?limit=100",
     lambda d: [p["name"] for p in d["content"]]),
]

_SUFFIXES = re.compile(r"\b(ltd|limited|plc|llp|llc|inc|uk)\b\.?|\.com\b")


def slug_candidates(company: str) -> list[str]:
    """Likely board names: "Just Eat Takeaway.com Ltd" -> ["justeattakeaway", "just-eat-takeaway"]."""
    words = re.findall(r"[a-z0-9]+", _SUFFIXES.sub(" ", company.lower()))
    candidates = ["".join(words), "-".join(words)]
    return [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]


def probe(company: str) -> dict | None:
    """The first board found for the company, as {source, board, titles}; None if none has jobs.

    A board that exists but lists no jobs counts as not found: SmartRecruiters answers every name,
    so "has jobs" is the only signal that the board is real.
    """
    for slug in slug_candidates(company):
        for source, url, titles_of in PROBES:
            try:
                titles = titles_of(get_with_retry(url.format(slug), label=f"probe {source}").json())
            except Exception:  # 404 or an unexpected shape: not this one
                continue
            if titles:
                return {"source": source, "board": slug, "titles": titles}
    return None


def hiring_companies(cfg: dict, app_id: str, app_key: str) -> dict[str, list[str]]:
    """Company -> titles of its Adzuna ads that pass the title filter, across all keywords."""
    found: dict[str, list[str]] = {}
    for keyword in cfg["keywords"]:
        for ad in adzuna.search(keyword, cfg["location"], app_id, app_key, max_days_old=cfg.get("max_days_old", 30)):
            if ad["company"] and ad["title"] not in found.get(ad["company"], []):
                found.setdefault(ad["company"], []).append(ad["title"])
    return found


def report(
    hiring: dict[str, list[str]], targets: list[dict], seen_elsewhere: set[str], filter_cfg: dict,
    probe_fn: Callable[[str], dict | None] = probe,
) -> str:
    """Table of new companies, most ads first, then [[company]] blocks for those with a board found."""
    target_names = [t["name"] for t in targets]
    new = sorted(
        ((c, titles) for c, titles in hiring.items() if not names_any(c, target_names)),
        key=lambda item: (-len(item[1]), item[0]),
    )
    rows, blocks = [], []
    for company, titles in new:
        logger.info("probing %s", company)
        board = probe_fn(company)
        seen = "yes" if company in seen_elsewhere else ""
        if board:
            matching = sum(title_matches(t, filter_cfg) for t in board["titles"])
            rows.append(f"{company} | {len(titles)} | {seen} | {board['source']}:{board['board']} | "
                        f"{len(board['titles'])} jobs, {matching} matching | e.g. {board['titles'][0]}")
            blocks.append(f'[[company]]\nname = "{company}"\nsource = "{board["source"]}"\nboard = "{board["board"]}"\n')
        else:
            rows.append(f"{company} | {len(titles)} | {seen} | not found | e.g. ad: {titles[0]}")
    header = "company | Adzuna ads | already via Reed/DevITjobs | board | board jobs | sample title"
    lines = [f"{len(new)} companies hiring for matching titles are not targets yet.", "", header, *rows]
    if blocks:
        lines += ["", "Check the sample title is really that company, then paste into config/targets.toml:", ""]
        lines += blocks
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load_config()
    discover_cfg = cfg["profile"].get("discover")
    if not discover_cfg:
        raise config.ConfigError("config/profile.toml has no [discover] section — see profile.example.toml")
    env = config.require_env(["ADZUNA_APP_ID", "ADZUNA_API_KEY"])

    hiring = hiring_companies(discover_cfg, env["ADZUNA_APP_ID"], env["ADZUNA_API_KEY"])
    conn = store.connect()
    seen = store.companies_from(conn, ["reed", "devitjobs"])
    conn.close()
    print(report(hiring, cfg["targets"], seen, cfg["profile"]["filter"]))


if __name__ == "__main__":
    main()
