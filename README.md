# job-radar

Watches public job boards (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Eightfold, amazon.jobs) for AI engineering roles, filters them, scores each one against a candidate's CV with Claude, and sends strong matches to a Telegram chat.

Built with plain Python (`requests` + standard library) and no frameworks, as a small, fully visible example of an LLM system: sources, storage, scoring, evaluation and notification.

Status: in development. See `docs/ROADMAP.md` for progress, `docs/design.md` for the architecture, and `docs/scoring.md` for how a job gets its score.

## What it does

- Fetches open jobs from each configured company's Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable or Eightfold board, and Amazon's own job site.
- Optionally searches Reed.co.uk by keyword across all employers (`[reed]` in `profile.toml`, `REED_API_KEY`), skipping employers already fetched from their own board.
- Optionally reads DevITjobs.uk, a UK tech job board (`[devitjobs]` in `profile.toml`, no key), with the same skip.
- A discovery report (`python -m jobs.discover`, run by hand) searches Adzuna for companies hiring for matching titles that aren't targets yet, guesses their Greenhouse, Ashby, Lever or SmartRecruiters board, and prints `[[company]]` blocks to review. It never edits `targets.toml`.
- Filters by title keywords and location: on-site roles in the listed locations, and remote roles only in the listed regions (`config/profile.toml`).
- Stores matches in SQLite, deduplicated by `source:company:job_id`.
- Scores each new match from 1 to 10 against the CV, a rubric of preferences and a list of dealbreakers. A dealbreaker only counts when the model quotes the posting stating it, and the code then caps the score at 3.
- Sends jobs scoring 7 or more to Telegram, with the score, the top reason and the link. A job is never sent twice.
- Keeps going when one board, one API call or one message fails: the error is logged and recorded in the `runs` table, and the run continues.
- Measures scoring against hand-labelled jobs with `python -m evals.run`: agreement, precision and recall for "apply", and every disagreement.

## Architecture

![job-radar architecture: three job-board APIs feed three source modules, which normalise jobs through jobs/radar.py into SQLite; core/llm.py scores them against the CV with the Anthropic API, and core/notify.py sends jobs scoring 7 or more to Telegram](docs/architecture.svg)

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                                # ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
cp config/targets.example.toml config/targets.toml  # companies and their job boards
cp config/profile.example.toml config/profile.toml  # filter, rubric, dealbreakers, threshold
```

Add the CV as plain text or Markdown in `config/cv.md`. Environment variables are read from the shell: `set -a; source .env; set +a`.

For the evaluation, label some stored jobs as `apply`, `maybe` or `skip` in `evals/cases/scoring.jsonl`; `evals/cases/scoring.example.jsonl` shows the format.

## Run

```bash
python -m jobs.radar --dry-run   # preview matches; no database, LLM or Telegram
python -m jobs.radar             # fetch, filter, store, score, and notify
python -m evals.run              # score the labelled jobs and compare with the labels (~$0.08)
python -m jobs.discover          # report companies hiring for matching titles that aren't targets yet
python -m unittest               # test suite; no network, fixtures in tests/fixtures/
```

### On a schedule (macOS launchd)

`scripts/run_radar.sh` loads `.env` and runs the radar once; `scripts/com.getjo.radar.plist` runs it daily at 09:00. Output is appended to `data/radar.log`.

Install (from the repo root, after Setup; `.env` and `.venv` must exist):

```bash
sed "s|REPO_DIR|$PWD|g" scripts/com.getjo.radar.plist > ~/Library/LaunchAgents/com.getjo.radar.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.getjo.radar.plist
```

The job stays installed across restarts; launchd reloads `~/Library/LaunchAgents/` at login.

Check and test:

```bash
launchctl print gui/$(id -u)/com.getjo.radar | grep -E "state|runs|last exit"   # loaded? last exit code?
launchctl kickstart gui/$(id -u)/com.getjo.radar                               # run once now
tail -f data/radar.log                                                          # follow the output
sqlite3 data/jobs.db "SELECT * FROM runs ORDER BY id DESC LIMIT 3"              # recorded runs
```

Change the schedule: edit `scripts/com.getjo.radar.plist`, then uninstall and install again.

Uninstall:

```bash
launchctl bootout gui/$(id -u)/com.getjo.radar
rm ~/Library/LaunchAgents/com.getjo.radar.plist
```

A run missed while the Mac is asleep starts on wake; a run missed while it is shut down is skipped.

## Known limitations

- Supported boards: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Eightfold and amazon.jobs. Companies on other systems (e.g. Avature, or a custom careers site) are skipped.
- Workday, Eightfold and amazon.jobs have no documented public API: the adapter uses the endpoints its own careers pages call, so a change on Workday's side shows up as a fetch error for those companies.
- Reed: only direct-employer ads by default (agency ads often hide the employer, so duplicates can't be detected). A job is recognised as a duplicate of a target's own posting by employer name only.
- The schedule runs on one Mac and depends on it being on. Every run ends with a summary message in Telegram, so a missed run shows up only as a missing message; nothing outside the Mac raises an alert.
- Scores cluster around 8 for any reasonable fit, so strong and borderline matches are hard to separate with the threshold alone.
- Description quality varies by source: Greenhouse provides the full posting; Lever and Ashby provide a shorter summary without their bullet-list sections.
