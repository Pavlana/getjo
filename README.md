# job-radar

Watches public job boards (Greenhouse, Lever, Ashby) for AI engineering roles, filters them, scores each one against my CV with Claude, and sends the good matches to Telegram.

Built with plain Python (`requests` + standard library) and no frameworks, as a small, fully visible example of an LLM system: sources, storage, scoring, evaluation and notification.

Status: in development. See `docs/ROADMAP.md` for progress and `docs/design.md` for the architecture and decisions.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the values
python -m jobs.radar --dry-run
```
