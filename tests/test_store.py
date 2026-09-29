import tempfile
import unittest
from pathlib import Path

from core.store import connect, record_run, upsert_job

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
