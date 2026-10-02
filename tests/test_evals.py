import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import ConfigError
from core.llm import Completion
from core.store import connect as real_connect
from core.store import upsert_job
from evals.run import load_cases, report, score_cases, summarize, to_label

SCORING = {"model": "claude-haiku-4-5", "notify_threshold": 7, "rubric": ["LLM work is core"]}


def job(job_id: str, title: str = "AI Engineer") -> dict:
    return {
        "id": job_id, "source": "greenhouse", "company": "Acme", "title": title, "location": "London",
        "url": "https://example.com", "description": "desc", "first_seen": "2026-10-01T00:00:00Z", "score": None,
    }


def result(expected: str, predicted: str) -> dict:
    return {"expected": expected, "predicted": predicted}


def scored(score: int, reasons=(), red_flags=(), dealbreakers=(), raw_score: int | None = None) -> dict:
    """A result shaped like score_with_retry's: verified dealbreakers and the pre-cap score included."""
    return {"score": score, "reasons": list(reasons), "red_flags": list(red_flags),
            "dealbreakers": list(dealbreakers), "raw_score": score if raw_score is None else raw_score}


class ToLabelTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(to_label(10, 7), "apply")
        self.assertEqual(to_label(7, 7), "apply")
        self.assertEqual(to_label(6, 7), "maybe")
        self.assertEqual(to_label(4, 7), "maybe")
        self.assertEqual(to_label(3, 7), "skip")
        self.assertEqual(to_label(1, 7), "skip")

    def test_unscored(self):
        self.assertEqual(to_label(None, 7), "unscored")


class SummarizeTest(unittest.TestCase):
    def test_counts(self):
        results = [
            result("apply", "apply"),
            result("apply", "maybe"),
            result("skip", "apply"),
            result("skip", "skip"),
            result("maybe", "unscored"),
        ]
        metrics = summarize(results)
        self.assertEqual(metrics["agreement"], (2, 5))
        self.assertEqual(metrics["apply_precision"], (1, 2))
        self.assertEqual(metrics["apply_recall"], (1, 2))

    def test_no_predicted_applies(self):
        metrics = summarize([result("apply", "skip")])
        self.assertEqual(metrics["apply_precision"], (0, 0))
        self.assertEqual(metrics["apply_recall"], (0, 1))


class LoadCasesTest(unittest.TestCase):
    def _write(self, lines: list[str]) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "cases.jsonl"
        path.write_text("\n".join(lines) + "\n")
        return path

    def test_reads_cases_and_skips_blank_lines(self):
        path = self._write(['{"job_id": "a", "expected": "apply"}', "", '{"job_id": "b", "expected": "skip"}'])
        self.assertEqual([c["job_id"] for c in load_cases(path)], ["a", "b"])

    def test_rejects_unknown_label(self):
        path = self._write(['{"job_id": "a", "expected": "yes"}'])
        with self.assertRaises(ConfigError):
            load_cases(path)

    def test_rejects_empty_label(self):
        path = self._write(['{"job_id": "a", "expected": ""}'])
        with self.assertRaises(ConfigError):
            load_cases(path)

    def test_missing_file_points_to_example(self):
        with self.assertRaisesRegex(ConfigError, "scoring.example.jsonl"):
            load_cases(Path("/nonexistent/cases.jsonl"))


@mock.patch("evals.run.load_cv", return_value="cv")
@mock.patch("evals.run.score_with_retry")
@mock.patch("evals.run.store.connect")
class ScoreCasesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "jobs.db"
        conn = real_connect(self.db_path)
        upsert_job(conn, job("j1", "AI Engineer"))
        upsert_job(conn, job("j2", "Sales Engineer"))
        conn.close()

    def tearDown(self):
        self._tmp.cleanup()

    def test_scores_cases_and_reports_disagreements(self, mock_connect, mock_score, _):
        mock_connect.side_effect = lambda: real_connect(self.db_path)
        mock_score.side_effect = [
            (scored(8, reasons=["RAG work"]), [Completion("", 1, 1, 0.004)]),
            (scored(8, reasons=["good"], red_flags=["pre-sales"]), [Completion("", 1, 1, 0.004)]),
        ]
        cases = [
            {"job_id": "j1", "expected": "apply", "reason": "", "title": "AI Engineer", "company": "Acme"},
            {"job_id": "j2", "expected": "skip", "reason": "pre-sales", "title": "Sales Engineer", "company": "Acme"},
        ]

        results, cost = score_cases(cases, SCORING, "key")
        text = report(results, cost, SCORING)

        self.assertAlmostEqual(cost, 0.008)
        self.assertIn("Agreement:        1/2 (50%)", text)
        self.assertIn("Apply precision:  1/2 (50%)", text)
        self.assertIn("Apply recall:     1/1 (100%)", text)
        self.assertIn("you: skip   Claude: apply (8)  Sales Engineer — Acme", text)
        self.assertIn("your reason: pre-sales", text)
        self.assertIn("Claude's red flag: pre-sales", text)
        self.assertNotIn("AI Engineer — Acme", text)  # agreements aren't listed

    def test_never_writes_scores(self, mock_connect, mock_score, _):
        mock_connect.side_effect = lambda: real_connect(self.db_path)
        mock_score.return_value = (scored(8, reasons=["x"]), [])

        score_cases([{"job_id": "j1", "expected": "apply"}], SCORING, "key")

        conn = real_connect(self.db_path)
        self.assertEqual(conn.execute("SELECT score, score_attempts FROM jobs WHERE id = 'j1'").fetchone(), (None, 0))
        conn.close()

    def test_unknown_job_id_fails_loudly(self, mock_connect, mock_score, _):
        mock_connect.side_effect = lambda: real_connect(self.db_path)

        with self.assertRaisesRegex(ConfigError, "missing-job"):
            score_cases([{"job_id": "missing-job", "expected": "skip"}], SCORING, "key")
        mock_score.assert_not_called()

    def test_result_with_no_reasons_or_red_flags_is_reported(self, mock_connect, mock_score, _):
        mock_connect.side_effect = lambda: real_connect(self.db_path)
        mock_score.return_value = (scored(8), [])

        results, cost = score_cases(
            [{"job_id": "j1", "expected": "skip", "title": "AI Engineer", "company": "Acme"}], SCORING, "key"
        )

        self.assertIn("(no reasons or red flags given)", report(results, cost, SCORING))

    def test_capped_score_shows_rule_quote_and_original_score(self, mock_connect, mock_score, _):
        mock_connect.side_effect = lambda: real_connect(self.db_path)
        travel = {"rule": "Travel of 25% or more", "quote": "Travel up to 30%"}
        mock_score.return_value = (scored(3, reasons=["fit"], dealbreakers=[travel], raw_score=8), [])

        results, cost = score_cases(
            [{"job_id": "j1", "expected": "apply", "title": "AI Engineer", "company": "Acme"}], SCORING, "key"
        )
        text = report(results, cost, SCORING)

        self.assertIn("Claude: skip (3, capped from 8)", text)
        self.assertIn('Claude\'s dealbreaker: Travel of 25% or more — "Travel up to 30%"', text)

    def test_unscored_case_counts_as_disagreement(self, mock_connect, mock_score, _):
        mock_connect.side_effect = lambda: real_connect(self.db_path)
        mock_score.return_value = (None, [Completion("bad", 1, 1, 0.004), Completion("bad", 1, 1, 0.004)])

        results, cost = score_cases(
            [{"job_id": "j1", "expected": "skip", "title": "AI Engineer", "company": "Acme"}], SCORING, "key"
        )
        text = report(results, cost, SCORING)

        self.assertIn("Agreement:        0/1 (0%)", text)
        self.assertIn("Claude: unscored (-)", text)
        self.assertIn("no usable reply", text)


if __name__ == "__main__":
    unittest.main()
