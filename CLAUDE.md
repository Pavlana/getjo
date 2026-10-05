# job-radar

Polls public job boards (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable), filters listings, scores them against my CV with Claude, stores them in SQLite and sends new matches to my Telegram bot (@getjo_bot).

It is also my learning project for AI system design. I'm an experienced cloud engineer (Azure, security, CI/CD) returning to work. I want to understand every line, so work in small steps and explain decisions.

## How to work with me

1. For each task, start by proposing a short plan: files to touch, functions, data flow, and one or two trade-offs. Wait for my OK before writing code.
2. Implement the smallest change that meets the task's acceptance criteria in `docs/ROADMAP.md`. No speculative features.
3. Add or update tests, then run `python -m unittest`.
4. Finish with a 3–5 line summary and a suggested commit message. Do not commit or push unless I ask.
5. When a decision is worth remembering (a schema, a retry policy, a model choice), add one line to `docs/decisions.md` (gitignored, private: it may name real companies and my preferences). Keep `docs/design.md` free of anything personal.
6. If I ask "why", explain the concept briefly with a pointer to where it shows up in this code.

## Technical rules

- Python 3.11+. Dependencies: `requests` only. Everything else from the standard library.
- No frameworks: no LangChain, LlamaIndex, FastAPI, pydantic, ORMs, agent SDKs. No notebooks.
- Call the Anthropic API with a plain HTTPS POST to `https://api.anthropic.com/v1/messages` via `requests`.
- Config in TOML under `config/`, read with `tomllib`. Secrets only from environment variables.
- Storage: `sqlite3`, database file in `data/` (gitignored).
- Every HTTP call has a timeout. Retry on 429 and 5xx with exponential backoff and a cap. Never retry 4xx other than 429.
- One source failing must not stop the run: log it and continue.
- Runs are idempotent: running twice never stores or notifies the same job twice.
- Tests use `unittest` and never hit the network; mock HTTP with fixtures saved in `tests/fixtures/`.
- Logging with the `logging` module to stdout. Never log secrets, tokens or full CV text.
- Type hints on public functions. Small functions. No abstractions until there are two real uses.

## Security

- Never read, print or edit `.env`. Use `.env.example` to document variables.
- `config/cv.md` holds my CV text and is gitignored. Read it only in the scoring step.
- Nothing in this project sends email, applies to jobs or posts anywhere except my own Telegram chat.

## Layout

```
core/      llm.py (Anthropic calls), store.py (SQLite), notify.py (Telegram), config.py
sources/   greenhouse.py, lever.py, ashby.py, workday.py, smartrecruiters.py, workable.py, reed.py (keyword search), devitjobs.py
           -> each returns a list of Job dicts in one shared shape; html_text.py is shared
jobs/      radar.py (fetch -> filter -> store -> score -> notify), discover.py (new companies to consider)
evals/     cases/*.jsonl, run.py
tests/     unit tests + fixtures/
config/    targets.toml (companies), profile.toml (filters, rubric), cv.md — all gitignored; *.example.toml are committed templates
docs/      ROADMAP.md (iterations and tasks), design.md (diagram, job shape), scoring.md (how scoring works),
           decisions.md (decision log, gitignored)
```

## Commands

- Run once: `python -m jobs.radar`
- Dry run, no Telegram and no LLM: `python -m jobs.radar --dry-run`
- Tests: `python -m unittest`
- Evals: `python -m evals.run`
- Discovery report (by hand): `python -m jobs.discover`

## Environment variables

`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; optional `REED_API_KEY`; for discovery `ADZUNA_APP_ID`, `ADZUNA_API_KEY`
