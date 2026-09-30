import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.store import connect as real_connect
from jobs.radar import matches_filter, run

PROFILE = {
    "filter": {
        "title_include": ["ai engineer", "applied ai"],
        "title_exclude": ["intern", "director"],
        "locations": ["london", "remote"],
    },
    "scoring": {"model": "x", "notify_threshold": 7},
}

TARGETS = [
    {"name": "Acme", "source": "greenhouse", "board": "acme"},
    {"name": "NoBoard", "source": "greenhouse", "board": ""},
    {"name": "Unsupported", "source": "ashby", "board": "unsupported"},
]


def make_job(job_id, title="AI Engineer", location="London, UK", company="Acme"):
    return {
        "id": f"greenhouse:{company}:{job_id}",
        "source": "greenhouse",
        "company": company,
        "title": title,
        "location": location,
        "url": f"https://example.com/{job_id}",
        "description": "desc",
        "first_seen": "2026-09-30T09:00:00Z",
        "score": None,
    }


def fetchers(**by_source: mock.Mock):
    """Patch jobs.radar.FETCHERS for the duration of a `with` block, with mocks we can assert on."""
    return mock.patch.dict("jobs.radar.FETCHERS", by_source, clear=True)


class MatchesFilterTest(unittest.TestCase):
    def test_matching_title_and_location(self):
        self.assertTrue(matches_filter(make_job(1), PROFILE["filter"]))

    def test_title_missing_include_keyword(self):
        job = make_job(1, title="Sales Manager")
        self.assertFalse(matches_filter(job, PROFILE["filter"]))

    def test_title_has_exclude_keyword(self):
        job = make_job(1, title="AI Engineer Intern")
        self.assertFalse(matches_filter(job, PROFILE["filter"]))

    def test_location_not_in_list(self):
        job = make_job(1, location="Berlin, Germany")
        self.assertFalse(matches_filter(job, PROFILE["filter"]))

    def test_case_insensitive(self):
        job = make_job(1, title="AI ENGINEER", location="LONDON")
        self.assertTrue(matches_filter(job, PROFILE["filter"]))


@mock.patch("jobs.radar.notify.send_telegram")
@mock.patch("jobs.radar.store.connect")
@mock.patch("jobs.radar.config.load_config")
class RunDryRunTest(unittest.TestCase):
    def test_dry_run_sends_and_stores_nothing(self, mock_load, mock_connect, mock_send):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=True)

        mock_send.assert_not_called()
        mock_connect.assert_not_called()

    def test_dry_run_prints_matches(self, mock_load, mock_connect, mock_send):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}

        buf = io.StringIO()
        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1, title="AI Engineer")])):
            with contextlib.redirect_stdout(buf):
                run(dry_run=True)

        self.assertIn("AI Engineer", buf.getvalue())


@mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"})
@mock.patch("jobs.radar.notify.send_telegram")
@mock.patch("jobs.radar.store.connect")
@mock.patch("jobs.radar.config.load_config")
class RunRealTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "jobs.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _read_one(self, sql: str):
        """Open a fresh connection to check what a run() call persisted — mirrors how a
        second real invocation of the script would see the database."""
        conn = real_connect(self.db_path)
        row = conn.execute(sql).fetchone()
        conn.close()
        return row

    def test_first_run_notifies_second_run_does_not(self, mock_load, mock_connect, mock_send):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}
        mock_connect.side_effect = lambda: real_connect(self.db_path)

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)
        self.assertEqual(mock_send.call_count, 1)

        mock_send.reset_mock()
        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)
        mock_send.assert_not_called()

    def test_non_matching_job_not_stored_or_notified(self, mock_load, mock_connect, mock_send):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}
        mock_connect.side_effect = lambda: real_connect(self.db_path)

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1, title="Sales Manager")])):
            run(dry_run=False)

        mock_send.assert_not_called()
        self.assertEqual(self._read_one("SELECT COUNT(*) FROM jobs")[0], 0)

    def test_fetch_failure_is_logged_and_run_continues(self, mock_load, mock_connect, mock_send):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}
        mock_connect.side_effect = lambda: real_connect(self.db_path)

        with fetchers(greenhouse=mock.Mock(side_effect=Exception("boom"))):
            run(dry_run=False)  # must not raise

        self.assertIn("boom", self._read_one("SELECT errors FROM runs")[0])

    def test_unsupported_source_or_missing_board_is_skipped(self, mock_load, mock_connect, mock_send):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}
        mock_connect.side_effect = lambda: real_connect(self.db_path)
        mock_greenhouse = mock.Mock(return_value=[make_job(1)])

        with fetchers(greenhouse=mock_greenhouse):
            run(dry_run=False)

        mock_greenhouse.assert_called_once_with("Acme", "acme")

    def test_lever_targets_are_fetched_alongside_greenhouse(self, mock_load, mock_connect, mock_send):
        targets = [
            {"name": "Acme", "source": "greenhouse", "board": "acme"},
            {"name": "LeverCo", "source": "lever", "board": "leverco"},
        ]
        mock_load.return_value = {"targets": targets, "profile": PROFILE}
        mock_connect.side_effect = lambda: real_connect(self.db_path)
        mock_greenhouse = mock.Mock(return_value=[make_job(1, company="Acme")])
        mock_lever = mock.Mock(return_value=[make_job(2, company="LeverCo")])

        with fetchers(greenhouse=mock_greenhouse, lever=mock_lever):
            run(dry_run=False)

        mock_greenhouse.assert_called_once_with("Acme", "acme")
        mock_lever.assert_called_once_with("LeverCo", "leverco")
        self.assertEqual(mock_send.call_count, 2)


if __name__ == "__main__":
    unittest.main()
