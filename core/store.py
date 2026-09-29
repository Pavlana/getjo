"""SQLite storage: jobs (deduplicated by natural key) and a run log."""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,   -- source:company:job_id
    source      TEXT NOT NULL,
    company     TEXT NOT NULL,
    title       TEXT NOT NULL,
    location    TEXT,
    url         TEXT NOT NULL,
    description TEXT,
    first_seen  TEXT NOT NULL,      -- ISO timestamp, set on insert
    score       INTEGER             -- null until scored
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    fetched     INTEGER NOT NULL DEFAULT 0,
    new_jobs    INTEGER NOT NULL DEFAULT 0,
    notified    INTEGER NOT NULL DEFAULT 0,
    errors      TEXT                -- newline-separated source errors, if any
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open (and create if needed) the SQLite database, with the schema applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def upsert_job(conn: sqlite3.Connection, job: dict) -> bool:
    """Insert a job if its id is new. Return True if it was new, False if already stored."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO jobs
            (id, source, company, title, location, url, description, first_seen, score)
        VALUES (:id, :source, :company, :title, :location, :url, :description, :first_seen, :score)
        """,
        {**job, "score": job.get("score")},
    )
    conn.commit()
    return cursor.rowcount == 1


def record_run(
    conn: sqlite3.Connection,
    started_at: str,
    finished_at: str,
    fetched: int = 0,
    new_jobs: int = 0,
    notified: int = 0,
    errors: str | None = None,
) -> None:
    """Log one run in the runs table."""
    conn.execute(
        """
        INSERT INTO runs (started_at, finished_at, fetched, new_jobs, notified, errors)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (started_at, finished_at, fetched, new_jobs, notified, errors),
    )
    conn.commit()
