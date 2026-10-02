import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.store import (
    add_score_attempt, connect, get_job, get_scoring_state, record_run, set_score, upsert_job,
)

JOB = {
    "id": "greenhouse:Example Co:123",
    "source": "greenhouse",
    "company": "Example Co",
    "title": "AI Engineer",
    "location": "London",
    "url": "https://example.com/jobs/123",
    "description": "Build things.",
    "first_seen": "2026-09-29T09:00:00Z",
}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "jobs.db"
        self.conn = connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_upsert_new_then_duplicate(self):
        self.assertTrue(upsert_job(self.conn, JOB))
        self.assertFalse(upsert_job(self.conn, JOB))

    def test_stored_row_matches_input(self):
        upsert_job(self.conn, JOB)
        row = self.conn.execute(
            "SELECT title, company, score FROM jobs WHERE id = ?", (JOB["id"],)
        ).fetchone()
        self.assertEqual(row, ("AI Engineer", "Example Co", None))

    def test_different_ids_both_new(self):
        other = {**JOB, "id": "greenhouse:Example Co:456"}
        self.assertTrue(upsert_job(self.conn, JOB))
        self.assertTrue(upsert_job(self.conn, other))

    def test_new_job_has_no_score_and_no_attempts(self):
        upsert_job(self.conn, JOB)
        self.assertEqual(get_scoring_state(self.conn, JOB["id"]), (None, 0))

    def test_set_score(self):
        upsert_job(self.conn, JOB)
        set_score(self.conn, JOB["id"], 8)
        self.assertEqual(get_scoring_state(self.conn, JOB["id"])[0], 8)

    def test_add_score_attempt_counts_up(self):
        upsert_job(self.conn, JOB)
        self.assertEqual(add_score_attempt(self.conn, JOB["id"]), 1)
        self.assertEqual(add_score_attempt(self.conn, JOB["id"]), 2)
        self.assertEqual(get_scoring_state(self.conn, JOB["id"]), (None, 2))

    def test_get_job_returns_all_columns(self):
        upsert_job(self.conn, JOB)
        job = get_job(self.conn, JOB["id"])
        self.assertEqual(job["title"], "AI Engineer")
        self.assertEqual(job["description"], "Build things.")
        self.assertIsNone(job["score"])
        self.assertEqual(job["score_attempts"], 0)

    def test_get_job_unknown_is_none(self):
        self.assertIsNone(get_job(self.conn, "greenhouse:Nobody:0"))

    def test_unknown_job_state(self):
        self.assertEqual(get_scoring_state(self.conn, "greenhouse:Nobody:0"), (None, 0))

    def test_old_database_gets_score_attempts_column(self):
        old_path = Path(self._tmp.name) / "old.db"
        old = sqlite3.connect(old_path)
        old.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT NOT NULL, "
            "title TEXT NOT NULL, location TEXT, url TEXT NOT NULL, description TEXT, "
            "first_seen TEXT NOT NULL, score INTEGER)"
        )
        old.execute(
            "INSERT INTO jobs VALUES (:id, :source, :company, :title, :location, :url, :description, "
            ":first_seen, NULL)",
            JOB,
        )
        old.commit()
        old.close()

        conn = connect(old_path)
        state = get_scoring_state(conn, JOB["id"])
        conn.close()

        self.assertEqual(state, (None, 0))

    def test_record_run(self):
        record_run(
            self.conn,
            started_at="2026-09-29T09:00:00Z",
            finished_at="2026-09-29T09:00:05Z",
            fetched=10,
            new_jobs=2,
            notified=2,
        )
        row = self.conn.execute(
            "SELECT fetched, new_jobs, notified, errors FROM runs"
        ).fetchone()
        self.assertEqual(row, (10, 2, 2, None))

    def test_connect_creates_db_file_and_dirs(self):
        nested = Path(self._tmp.name) / "nested" / "jobs.db"
        conn = connect(nested)
        conn.close()
        self.assertTrue(nested.exists())


if __name__ == "__main__":
    unittest.main()
