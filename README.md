# job-radar

Watches public job boards (Greenhouse, Lever, Ashby) for AI engineering roles, filters them, scores each one against my CV with Claude, and sends the good matches to Telegram.

Built with plain Python (`requests` + standard library) and no frameworks, as a small, fully visible example of an LLM system: sources, storage, scoring, evaluation and notification.

Status: in development. See `docs/ROADMAP.md` for progress and `docs/design.md` for decisions.

## What it does today

- Fetches open jobs from every configured company's Greenhouse, Lever or Ashby board
- Filters by title keywords and location (`config/profile.toml`)
- Stores matches in SQLite, deduplicated by `source:company:job_id` — running the same fetch twice never notifies twice
- Sends every new match straight to Telegram (no scoring yet — see [Known limitations](#known-limitations))
- One bad board (wrong name, API outage) is logged and skipped; the run still finishes and the error is recorded in the `runs` table

## Architecture

![job-radar architecture: three job-board APIs feed three source modules, which normalise through jobs/radar.py, dedup into SQLite, and notify Telegram for new matches; a dashed, not-yet-built branch shows planned CV scoring](docs/architecture.svg)

Solid-bordered boxes are built and verified against live boards. The dashed `core/llm.py` branch (score against the CV, gate the Telegram send on a threshold) is Iteration 4 — today every filter match gets sent, unscored.

[View the interactive version](https://claude.ai/artifact/BBWsVDtAm9JjV923hr54dk) (supports dark mode; requires access to the link).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                              # fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
cp config/targets.example.toml config/targets.toml # add the companies you want to watch
cp config/profile.example.toml config/profile.toml # set your keyword/location filter
```

`config/cv.md` isn't needed yet — it's only read once scoring (Iteration 4) exists.

## Run

```bash
python -m jobs.radar --dry-run   # preview matches; touches neither the database nor Telegram
python -m jobs.radar             # fetch, filter, store, and notify new matches for real
python -m unittest               # run the test suite (no network; fixtures in tests/fixtures/)
```

## Known limitations

- Only companies on Greenhouse, Lever or Ashby are covered — Workday, Workable, SmartRecruiters and custom in-house ATS's aren't supported. In my own 39-company target list, 14 fall into this category and are skipped with a note in `config/targets.toml`.
- No scoring against a CV yet — every job that passes the keyword/location filter gets sent to Telegram, not just the good matches. Iteration 4 adds this.
- No scheduler — a notification only happens when you run `python -m jobs.radar` yourself. Iteration 6 adds an automatic twice-daily run plus a "still alive" summary even when nothing's new.
- `description` quality varies by source: Greenhouse gives the full posting as HTML (stripped to plain text here); Lever and Ashby provide a shorter plain-text summary that omits their structured bullet-list sections.
