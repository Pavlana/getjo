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
- [ ] `core/notify.py`: `send_telegram(text)` using the Bot API `sendMessage`; splits messages over 4,000 characters
- [ ] Tests: inserting the same job twice returns new=True, then new=False; notify is tested with a mocked HTTP call
- [ ] `docs/design.md`: first diagram (source → filter → store → notify) and 3 decisions

**Acceptance:** `python -m unittest` passes; a one-off script sends "hello from job-radar" to Telegram.
**Concept:** idempotency and natural keys, fail-fast configuration.

---

## Iteration 2 · First working version (Wed 30 Sep)

- [ ] Fill in the job-board names in `targets.toml` (open each company's careers page and check which board it uses)
- [ ] `sources/greenhouse.py`: `GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true`, normalised to the shared Job shape (see `design.md`)
- [ ] Save one real response per source as a test fixture; parse it in tests with no network
- [ ] `jobs/radar.py`: fetch → keyword filter (title include/exclude, location) from `profile.toml` → store → notify only new jobs
- [ ] `--dry-run` flag prints what would be sent and sends nothing

**Acceptance:** first run sends the matching jobs; an immediate second run sends nothing. Then make the repo public.
**Concept:** the adapter pattern (many sources, one shape), polling.

---

## Iteration 3 · More sources and resilience (Thu 1 Oct)

- [ ] `sources/lever.py`: `GET https://api.lever.co/v0/postings/{board}?mode=json`
- [ ] `sources/ashby.py`: `GET https://api.ashbyhq.com/posting-api/job-board/{board}`
- [ ] Shared HTTP helper: timeout, retries on 429/5xx with backoff, clear log line per failure
- [ ] One broken board (wrong name, 404) is logged and skipped; the run still finishes and records the error in `runs`
- [ ] README: what it does, how to run it, diagram, known limitations

**Acceptance:** a run across all 15 companies completes, even with one deliberately wrong board name.
**Concept:** partial failure, retries vs giving up, rate limits.

---

## Iteration 4 · Scoring against the CV (week 2)

- [ ] `core/llm.py`: `complete(system, user, max_tokens)` via POST `/v1/messages`; logs input/output tokens and cost per call
- [ ] Scoring prompt: job description + `cv.md` + rubric from `profile.toml` → JSON `{score: 1-10, reasons: [..], red_flags: [..]}`
- [ ] Validate the JSON in code; on invalid output, retry once, then store the job as `unscored`
- [ ] Only jobs that pass the keyword filter get scored (cost control); only score ≥ threshold goes to Telegram
- [ ] Telegram message: title, company, location, score, top reason, link

**Acceptance:** a run scores new jobs, and cost per run is printed at the end.
**Concept:** structured output, validating model output, cost control by filtering first.

---

## Iteration 5 · Evaluation (week 2)

- [ ] Label 20 real stored jobs by hand in `evals/cases/scoring.jsonl`: `{job_id, expected: "apply" | "maybe" | "skip"}`
- [ ] `evals/run.py`: runs the scorer on the cases, prints agreement, precision for "apply", and the disagreements
- [ ] Record the baseline numbers in `design.md`; change the prompt once, re-run, record again

**Acceptance:** one command prints a comparable number, and you can say whether a prompt change helped.
**Concept:** offline evaluation, a labelled set as the source of truth, measuring before changing.

---

## Iteration 6 · Schedule (week 3)

- [ ] Run automatically twice a day (cron/launchd on the laptop, or GitHub Actions with secrets)
- [ ] A daily summary message even when there are no new jobs, so silence means broken, not empty
- [ ] Evals run in GitHub Actions on every push; the build fails below the agreed threshold

**Acceptance:** two unattended runs in a row, visible in the `runs` table.
**Concept:** scheduling, observability, evals as a CI gate.

---

## Later (only after applications have started)

- Proton inbox module (IMAP via Bridge): threads waiting for my reply, drafts to the Drafts folder
- Application Pack: job + master CV → tailored bullets checked against the CV for invented claims
- Hand-written tool-use loop over radar + inbox ("what needs me today?")
- Deploy the radar to Azure (Container Apps job or Functions timer, Key Vault, managed identity)
