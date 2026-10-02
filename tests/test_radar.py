import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import ConfigError
from core.llm import Completion
from core.store import connect as real_connect
from jobs.radar import _message, matches_filter, run

PROFILE = {
    "filter": {
        "title_include": ["ai engineer", "applied ai"],
        "title_exclude": ["intern", "director"],
        "locations": ["london"],
        "remote_places": ["united states", "us", "texas", "new mexico", "united kingdom", "denmark"],
    },
    "scoring": {
        "model": "claude-haiku-4-5", "notify_threshold": 7,
        "rubric": ["LLM work is core"], "dealbreakers": ["Travel of 25% or more"],
        "candidate_facts": ["Based in London"],
    },
}

TARGETS = [
    {"name": "Acme", "source": "greenhouse", "board": "acme"},
    {"name": "NoBoard", "source": "greenhouse", "board": ""},
    {"name": "Unsupported", "source": "workday", "board": "unsupported"},
]

ENV = {"ANTHROPIC_API_KEY": "a", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}


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


def scored(score: int, cost: float = 0.004):
    """What score_with_retry returns for a usable reply."""
    return {"score": score, "reasons": ["fit"], "red_flags": []}, [Completion("{}", 100, 10, cost)]


def unscored(cost: float = 0.004):
    """What score_with_retry returns after two unusable replies."""
    return None, [Completion("bad", 100, 10, cost), Completion("bad", 100, 10, cost)]


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

    def _location_passes(self, location: str) -> bool:
        return matches_filter(make_job(1, location=location), PROFILE["filter"])

    def test_london_passes_whatever_else_is_listed(self):
        self.assertTrue(self._location_passes("London, UK"))
        self.assertTrue(self._location_passes("Remote - India; London"))

    def test_location_terms_match_whole_words_only(self):
        self.assertFalse(self._location_passes("Londonderry, Northern Ireland"))
        self.assertFalse(self._location_passes("Remote - Australia"))  # contains "us"
        self.assertFalse(self._location_passes("Remote - Russia"))  # contains "us"
        self.assertFalse(self._location_passes("MX-Mexico-Remote"))  # "new mexico" is a US state

    def test_remote_in_listed_place_passes(self):
        self.assertTrue(self._location_passes("Remote - Texas"))
        self.assertTrue(self._location_passes("Remote, US"))
        self.assertTrue(self._location_passes("US-IL-Remote"))
        self.assertTrue(self._location_passes("Remote - United Kingdom"))
        self.assertTrue(self._location_passes("Finland; Remote - Denmark; Stockholm, Sweden"))

    def test_remote_elsewhere_fails(self):
        self.assertFalse(self._location_passes("Remote - India"))
        self.assertFalse(self._location_passes("Bangalore - Remote"))
        self.assertFalse(self._location_passes("Remote"))

    def test_listed_place_without_remote_fails(self):
        self.assertFalse(self._location_passes("Dallas, Texas"))
        self.assertFalse(self._location_passes("Manchester, United Kingdom"))

    def test_remote_roles_rejected_when_remote_places_not_configured(self):
        filter_cfg = {k: v for k, v in PROFILE["filter"].items() if k != "remote_places"}
        self.assertFalse(matches_filter(make_job(1, location="Remote - Texas"), filter_cfg))


class MessageTest(unittest.TestCase):
    RESULT = {"score": 8, "reasons": ["Hands-on RAG in Python", "London hybrid"], "red_flags": ["visa"]}

    def test_has_score_title_company_location_top_reason_and_link(self):
        self.assertEqual(
            _message(make_job(1), self.RESULT),
            "8/10 · AI Engineer\nAcme · London, UK\nHands-on RAG in Python\nhttps://example.com/1",
        )

    def test_missing_location_shows_company_only(self):
        lines = _message(make_job(1, location=""), self.RESULT).splitlines()
        self.assertEqual(lines[1], "Acme")

    def test_no_reasons_falls_back_to_red_flag_then_placeholder(self):
        no_reasons = {**self.RESULT, "reasons": []}
        self.assertEqual(_message(make_job(1), no_reasons).splitlines()[2], "visa")
        nothing = {**self.RESULT, "reasons": [], "red_flags": []}
        self.assertEqual(_message(make_job(1), nothing).splitlines()[2], "(no reason given)")


@mock.patch("jobs.radar.score_with_retry")
@mock.patch("jobs.radar.notify.send_telegram")
@mock.patch("jobs.radar.store.connect")
@mock.patch("jobs.radar.config.load_config")
class RunDryRunTest(unittest.TestCase):
    def test_dry_run_scores_sends_and_stores_nothing(self, mock_load, mock_connect, mock_send, mock_score):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=True)

        mock_score.assert_not_called()
        mock_send.assert_not_called()
        mock_connect.assert_not_called()

    def test_dry_run_prints_matches(self, mock_load, mock_connect, mock_send, mock_score):
        mock_load.return_value = {"targets": TARGETS, "profile": PROFILE}

        buf = io.StringIO()
        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1, title="AI Engineer")])):
            with contextlib.redirect_stdout(buf):
                run(dry_run=True)

        self.assertIn("AI Engineer", buf.getvalue())


@mock.patch.dict("os.environ", ENV)
@mock.patch("jobs.radar.load_cv", return_value="cv text")
@mock.patch("jobs.radar.score_with_retry")
@mock.patch("jobs.radar.notify.send_telegram")
@mock.patch("jobs.radar.store.connect")
@mock.patch("jobs.radar.config.load_config")
class RunRealTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "jobs.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _wire(self, mock_load, mock_connect, targets=TARGETS):
        mock_load.return_value = {"targets": targets, "profile": PROFILE}
        mock_connect.side_effect = lambda: real_connect(self.db_path)

    def _read_one(self, sql: str, params: tuple = ()):
        """Open a fresh connection to check what a run() call persisted — mirrors how a
        second real invocation of the script would see the database."""
        conn = real_connect(self.db_path)
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row

    def _score_of(self, job_id: str):
        return self._read_one("SELECT score FROM jobs WHERE id = ?", (job_id,))[0]

    def test_first_run_notifies_second_run_does_not(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)
        mock_score.return_value = scored(8)

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)
        self.assertEqual(mock_send.call_count, 1)
        self.assertTrue(mock_send.call_args[0][0].startswith("8/10 · AI Engineer\n"))
        self.assertEqual(self._score_of("greenhouse:Acme:1"), 8)

        mock_send.reset_mock()
        mock_score.reset_mock()
        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)
        mock_score.assert_not_called()
        mock_send.assert_not_called()

    def test_scoring_gets_cv_rubric_dealbreakers_and_facts_from_profile(
        self, mock_load, mock_connect, mock_send, mock_score, _
    ):
        self._wire(mock_load, mock_connect)
        mock_score.return_value = scored(5)

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)

        args, kwargs = mock_score.call_args
        self.assertEqual(args[1:], ("cv text", ["LLM work is core"], ["Travel of 25% or more"]))
        self.assertEqual(kwargs, {"model": "claude-haiku-4-5", "api_key": "a", "facts": ["Based in London"]})

    def test_below_threshold_is_stored_but_not_notified(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)
        mock_score.return_value = scored(5)

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)

        mock_send.assert_not_called()
        self.assertEqual(self._score_of("greenhouse:Acme:1"), 5)

    def test_unscored_job_stays_null_and_is_retried_next_run(
        self, mock_load, mock_connect, mock_send, mock_score, _
    ):
        self._wire(mock_load, mock_connect)
        mock_score.side_effect = [unscored(), scored(8)]

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)
        mock_send.assert_not_called()
        self.assertIsNone(self._score_of("greenhouse:Acme:1"))

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)
        self.assertEqual(mock_score.call_count, 2)
        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(self._score_of("greenhouse:Acme:1"), 8)

    def test_scoring_error_is_recorded_and_run_continues(
        self, mock_load, mock_connect, mock_send, mock_score, _
    ):
        self._wire(mock_load, mock_connect)
        mock_score.side_effect = [Exception("api down"), scored(8)]

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1), make_job(2)])):
            run(dry_run=False)  # must not raise

        self.assertIn("api down", self._read_one("SELECT errors FROM runs")[0])
        self.assertIsNone(self._score_of("greenhouse:Acme:1"))
        self.assertEqual(self._score_of("greenhouse:Acme:2"), 8)
        self.assertEqual(mock_send.call_count, 1)

    def test_notify_failure_leaves_job_unscored_for_retry(
        self, mock_load, mock_connect, mock_send, mock_score, _
    ):
        self._wire(mock_load, mock_connect)
        mock_score.return_value = scored(9)
        mock_send.side_effect = Exception("telegram down")

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)  # must not raise

        self.assertIsNone(self._score_of("greenhouse:Acme:1"))
        self.assertIn("telegram down", self._read_one("SELECT errors FROM runs")[0])
        self.assertEqual(self._read_one("SELECT notified FROM runs")[0], 0)

    def test_cost_includes_retries_and_is_logged(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)
        mock_score.side_effect = [scored(8, cost=0.004), unscored(cost=0.004)]

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1), make_job(2)])):
            with self.assertLogs("jobs.radar", level="INFO") as logs:
                run(dry_run=False)

        summary = logs.output[-1]
        self.assertIn("scored=1 failed=1 gave_up=0 notified=1", summary)
        self.assertIn("cost=$0.0120", summary)

    def test_gives_up_after_three_failed_runs(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)
        mock_score.return_value = unscored()

        for _run in range(3):
            with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
                with self.assertLogs("jobs.radar", level="INFO") as logs:
                    run(dry_run=False)
        self.assertTrue(any("giving up on greenhouse:Acme:1 after 3 tries" in line for line in logs.output))
        self.assertIn("gave_up=1", logs.output[-1])

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
            run(dry_run=False)

        self.assertEqual(mock_score.call_count, 3)
        self.assertIsNone(self._score_of("greenhouse:Acme:1"))
        self.assertEqual(self._read_one("SELECT score_attempts FROM jobs")[0], 3)

    def test_failed_send_counts_as_a_try(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)
        mock_score.return_value = scored(9)
        mock_send.side_effect = Exception("message rejected")

        for _run in range(4):
            with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
                run(dry_run=False)

        self.assertEqual(mock_score.call_count, 3)
        self.assertEqual(mock_send.call_count, 3)
        self.assertIsNone(self._score_of("greenhouse:Acme:1"))

    def test_successful_score_on_last_try_is_kept(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)
        mock_score.side_effect = [unscored(), unscored(), scored(8)]

        for _run in range(3):
            with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
                run(dry_run=False)

        self.assertEqual(self._score_of("greenhouse:Acme:1"), 8)
        self.assertEqual(mock_send.call_count, 1)

    def test_non_matching_job_not_stored_scored_or_notified(
        self, mock_load, mock_connect, mock_send, mock_score, _
    ):
        self._wire(mock_load, mock_connect)

        with fetchers(greenhouse=mock.Mock(return_value=[make_job(1, title="Sales Manager")])):
            run(dry_run=False)

        mock_score.assert_not_called()
        mock_send.assert_not_called()
        self.assertEqual(self._read_one("SELECT COUNT(*) FROM jobs")[0], 0)

    def test_fetch_failure_is_logged_and_run_continues(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)

        with fetchers(greenhouse=mock.Mock(side_effect=Exception("boom"))):
            run(dry_run=False)  # must not raise

        self.assertIn("boom", self._read_one("SELECT errors FROM runs")[0])

    def test_unsupported_source_or_missing_board_is_skipped(
        self, mock_load, mock_connect, mock_send, mock_score, _
    ):
        self._wire(mock_load, mock_connect)
        mock_score.return_value = scored(8)
        mock_greenhouse = mock.Mock(return_value=[make_job(1)])

        with fetchers(greenhouse=mock_greenhouse):
            run(dry_run=False)

        mock_greenhouse.assert_called_once_with("Acme", "acme")

    def test_lever_targets_are_fetched_alongside_greenhouse(
        self, mock_load, mock_connect, mock_send, mock_score, _
    ):
        targets = [
            {"name": "Acme", "source": "greenhouse", "board": "acme"},
            {"name": "LeverCo", "source": "lever", "board": "leverco"},
        ]
        self._wire(mock_load, mock_connect, targets)
        mock_score.return_value = scored(8)
        mock_greenhouse = mock.Mock(return_value=[make_job(1, company="Acme")])
        mock_lever = mock.Mock(return_value=[make_job(2, company="LeverCo")])

        with fetchers(greenhouse=mock_greenhouse, lever=mock_lever):
            run(dry_run=False)

        mock_greenhouse.assert_called_once_with("Acme", "acme")
        mock_lever.assert_called_once_with("LeverCo", "leverco")
        self.assertEqual(mock_send.call_count, 2)

    def test_real_run_requires_anthropic_key(self, mock_load, mock_connect, mock_send, mock_score, _):
        self._wire(mock_load, mock_connect)
        env_without_key = {k: v for k, v in ENV.items() if k != "ANTHROPIC_API_KEY"}

        with mock.patch.dict("os.environ", env_without_key, clear=True):
            with fetchers(greenhouse=mock.Mock(return_value=[make_job(1)])):
                with self.assertRaises(ConfigError):
                    run(dry_run=False)


if __name__ == "__main__":
    unittest.main()
