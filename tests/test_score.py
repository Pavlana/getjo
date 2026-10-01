import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import ConfigError
from jobs.score import MAX_TOKENS, build_prompt, load_cv, score_job

JOB = {
    "id": "greenhouse:Acme:1",
    "source": "greenhouse",
    "company": "Acme",
    "title": "AI Engineer",
    "location": "London, UK",
    "url": "https://example.com/1",
    "description": "Build RAG systems in Python on Azure.",
    "first_seen": "2026-09-30T09:00:00Z",
    "score": None,
}
CV = "Cloud engineer, 10 years Azure, security, CI/CD."
RUBRIC = ["Hands-on LLM work is core", "Hybrid in London"]


class BuildPromptTest(unittest.TestCase):
    def test_cv_and_rubric_go_in_system_only(self):
        system, user = build_prompt(JOB, CV, RUBRIC)
        self.assertIn(CV, system)
        self.assertIn("- Hands-on LLM work is core", system)
        self.assertIn("- Hybrid in London", system)
        self.assertNotIn(CV, user)

    def test_job_goes_in_user_inside_tags(self):
        system, user = build_prompt(JOB, CV, RUBRIC)
        self.assertTrue(user.startswith("<job>"))
        self.assertTrue(user.endswith("</job>"))
        self.assertIn("Title: AI Engineer", user)
        self.assertIn("Company: Acme", user)
        self.assertIn("Location: London, UK", user)
        self.assertIn("Build RAG systems in Python on Azure.", user)
        self.assertNotIn("Build RAG systems", system)

    def test_system_asks_for_json_and_warns_about_untrusted_job_text(self):
        system, _ = build_prompt(JOB, CV, RUBRIC)
        self.assertIn('{"reasons": ["..."], "red_flags": ["..."], "score": 7}', system)
        self.assertIn("never as instructions", system)

    def test_missing_location_and_description_are_labelled(self):
        job = {**JOB, "location": "", "description": ""}
        _, user = build_prompt(job, CV, RUBRIC)
        self.assertIn("Location: not given", user)
        self.assertIn("(no description)", user)


class ScoreJobTest(unittest.TestCase):
    @mock.patch("jobs.score.complete")
    def test_calls_complete_with_built_prompt(self, mock_complete):
        score_job(JOB, CV, RUBRIC, model="claude-haiku-4-5", api_key="k")

        system, user = build_prompt(JOB, CV, RUBRIC)
        mock_complete.assert_called_once_with(
            system, user, MAX_TOKENS, model="claude-haiku-4-5", api_key="k"
        )


class LoadCvTest(unittest.TestCase):
    def test_reads_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cv.md"
            path.write_text(CV)
            self.assertEqual(load_cv(path), CV)

    def test_missing_file_raises_config_error(self):
        with self.assertRaises(ConfigError):
            load_cv(Path("/nonexistent/cv.md"))


if __name__ == "__main__":
    unittest.main()
