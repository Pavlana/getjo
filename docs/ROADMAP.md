# Roadmap

Each iteration ends with something that runs. In Claude Code, start a session with `/next` and end it with `/wrap`.
Tick a box only when its acceptance criteria pass.

---

## Iteration 0 · Skeleton (Mon 28 Sep)

- [x] Repo created (private for now), this kit copied in, first commit pushed with no secrets
- [x] `.env` created locally from `.env.example`, filled with real values, confirmed ignored by `git status`
- [x] `config/cv.md` created with the CV text, confirmed ignored by `git status`
- [x] `config/targets.toml` has 15 companies (board names can be blank until Wednesday)

**Concept:** secrets vs config vs code, and why each lives in a different place.

---

## Iteration 1 · Storage and notifications (Tue 29 Sep)

- [x] `core/config.py`: load `config/*.toml` and required env vars; fail fast with a clear message if one is missing
- [x] `core/store.py`: SQLite schema with `jobs` and `runs` tables. A job's primary key is `source:company:job_id`. `upsert_job()` returns whether the job is new
- [x] `core/notify.py`: `send_telegram(text)` using the Bot API `sendMessage`; splits messages over 4,000 characters
- [x] Tests: inserting the same job twice returns new=True, then new=False; notify is tested with a mocked HTTP call
- [x] `docs/design.md`: first diagram (source → filter → store → notify) and 3 decisions

**Acceptance:** `python -m unittest` passes; a one-off script sends "hello from job-radar" to Telegram.
**Concept:** idempotency and natural keys, fail-fast configuration.

---

## Iteration 2 · First working version (Wed 30 Sep)

- [x] Fill in the job-board names in `targets.toml` (open each company's careers page and check which board it uses)
- [x] `sources/greenhouse.py`: `GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true`, normalised to the shared Job shape (see `design.md`)
- [x] Save one real response per source as a test fixture; parse it in tests with no network
- [x] `jobs/radar.py`: fetch → keyword filter (title include/exclude, location) from `profile.toml` → store → notify only new jobs
- [x] `--dry-run` flag prints what would be sent and sends nothing

**Acceptance:** first run sends the matching jobs; an immediate second run sends nothing. Then make the repo public.
**Concept:** the adapter pattern (many sources, one shape), polling.

---

## Iteration 3 · More sources and resilience (Thu 1 Oct)

- [x] `sources/lever.py`: `GET https://api.lever.co/v0/postings/{board}?mode=json`
- [x] `sources/ashby.py`: `GET https://api.ashbyhq.com/posting-api/job-board/{board}`
- [x] Shared HTTP helper: timeout, retries on 429/5xx with backoff, clear log line per failure
- [x] One broken board (wrong name, 404) is logged and skipped; the run still finishes and records the error in `runs`
- [x] README: what it does, how to run it, diagram, known limitations
  - Diagram: build a proper architecture diagram (Claude Artifact, boxes-and-arrows, not just the Mermaid block in `design.md`) showing sources, core modules and external services; reuse it (e.g. as an exported image) in the README

**Acceptance:** a run across all 15 companies completes, even with one deliberately wrong board name.
**Concept:** partial failure, retries vs giving up, rate limits.

---

## Iteration 4 · Scoring against the CV (week 2)

- [x] `core/llm.py`: `complete(system, user, max_tokens)` via POST `/v1/messages`; logs input/output tokens and cost per call
- [x] Scoring prompt: job description + `cv.md` + rubric from `profile.toml` → JSON `{score: 1-10, reasons: [..], red_flags: [..]}`
- [x] Validate the JSON in code; on invalid output, retry once, then store the job as `unscored`
- [x] Only jobs that pass the keyword filter get scored (cost control); only score ≥ threshold goes to Telegram
- [x] Telegram message: title, company, location, score, top reason, link

**Acceptance:** a run scores new jobs, and cost per run is printed at the end.
**Concept:** structured output, validating model output, cost control by filtering first.

---

## Iteration 5 · Evaluation (week 2)

- [x] Label 20 real stored jobs by hand in `evals/cases/scoring.jsonl`: `{job_id, expected: "apply" | "maybe" | "skip"}`
- [x] `evals/run.py`: runs the scorer on the cases, prints agreement, precision for "apply", and the disagreements
- [x] Record the baseline numbers in `design.md`; change the prompt once, re-run, record again

**Acceptance:** one command prints a comparable number, and you can say whether a prompt change helped.
**Concept:** offline evaluation, a labelled set as the source of truth, measuring before changing.

---

## Iteration 6 · Schedule (week 3)

- [x] Run automatically once a day (cron/launchd on the laptop, or GitHub Actions with secrets)
- [x] A daily summary message even when there are no new jobs, so silence means broken, not empty

**Acceptance:** two unattended runs in a row, visible in the `runs` table.
**Concept:** scheduling, observability.

---

## Iteration 7 · Wider sourcing

- [x] Investigation, no code: for each target company skipped today (no supported board), find which job board it uses; check which job search services have a usable API for UK roles (full descriptions, rate limits, terms). Output: one table and a recommendation (new board adapters, a search-based source, or both)
- [x] Config: targets acquired by another company point at the parent company's board; drop targets whose roles can't be separated from the parent's
- [x] `sources/workday.py`: list endpoint for all postings, then one detail call per title match for full locations and description (the list shows "N Locations"); undocumented feed, so fixture tests and a clear log line when the shape changes
- [x] `sources/smartrecruiters.py`: official public postings API; details only for titles that pass the title filter
- [x] `sources/workable.py`: official widget API
- [x] Reed search source: free API key, keyword + location search, details endpoint for the full description; check description length live before building. Same job from two sources (a search service and the company's own board) is notified once
- [x] Jooble: request an API key, check fields, description length and terms; build a source only if descriptions are usable for scoring. Evaluated, not built: ~280-character excerpts with no details endpoint, country-only locations
- [x] DevITjobs UK: check terms of use for the public jobs list; if allowed, use it for discovery (companies hiring for matching titles) and, if job details are reachable, as a source
- [x] Adzuna for discovery: search returns only a snippet, too short for scoring; use it to find companies hiring for matching titles in London and add their boards to targets

**Acceptance:** every reachable target is fetched in a normal run, and at least one search-based source adds jobs from companies not in `targets.toml`, with no job notified twice.
**Concept:** coverage vs effort; choosing sources by what they add, not by what is easiest to build.

---

## Iteration 8 · Big employers

- [x] Workday: optional `search` per target (e.g. "London"), for employers with more than Workday's 2,000-posting listing cap
- [x] Amazon (amazon.jobs search, full descriptions in the results)
- [x] Microsoft (Eightfold search API; check descriptions live first)
- [ ] JPMorganChase (Oracle Cloud recruiting API; check the location filter live first)

**Acceptance:** each employer's matching London roles appear in a dry run; a change in an undocumented feed shows up as a fetch error, not as silently missing jobs.
**Concept:** undocumented APIs as dependencies: pin their shape with fixtures, fail loudly when it changes.

---

## Later (only after applications have started)

- Targets with no readable job board: a paste-in command for a single job (URL + description copied by hand, then stored, scored and notified like any other), job-alert emails as a discovery feed, manual LinkedIn search
- Evals in GitHub Actions on every push; the build fails below an agreed threshold. CI has no access to the private CV, profile or labelled cases, so it would use a committed set with a made-up candidate (CV, profile, ~10 cases with job text inline): it guards the code (prompt, parsing, dealbreaker checks), while the local eval keeps judging fit. Concept: evals as a CI gate
- Proton inbox module (IMAP via Bridge): threads waiting for my reply, drafts to the Drafts folder
- Application Pack: job + master CV → tailored bullets checked against the CV for invented claims
- Hand-written tool-use loop over radar + inbox ("what needs me today?")
- Deploy the radar to Azure (Container Apps job or Functions timer, Key Vault, managed identity)
