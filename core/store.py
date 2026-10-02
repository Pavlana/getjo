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
    score       INTEGER,            -- null until scored
    score_attempts INTEGER NOT NULL DEFAULT 0  -- runs that tried to score this job
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
    _add_missing_columns(conn)
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring a database created by an older version up to date.

    CREATE TABLE IF NOT EXISTS skips a table that already exists, so new columns
    have to be added to it explicitly.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "score_attempts" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN score_attempts INTEGER NOT NULL DEFAULT 0")
        conn.commit()


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


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    """Return a stored job as a dict of its columns, or None if it isn't stored."""
    cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip([col[0] for col in cursor.description], row))


def get_scoring_state(conn: sqlite3.Connection, job_id: str) -> tuple[int | None, int]:
    """Return (score, score_attempts) for a stored job; (None, 0) if it isn't stored."""
    row = conn.execute("SELECT score, score_attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return (row[0], row[1]) if row else (None, 0)


def add_score_attempt(conn: sqlite3.Connection, job_id: str) -> int:
    """Count one more scoring try for a job. Returns the new count."""
    conn.execute("UPDATE jobs SET score_attempts = score_attempts + 1 WHERE id = ?", (job_id,))
    conn.commit()
    return conn.execute("SELECT score_attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]


def set_score(conn: sqlite3.Connection, job_id: str, score: int) -> None:
    conn.execute("UPDATE jobs SET score = ? WHERE id = ?", (score, job_id))
    conn.commit()


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
