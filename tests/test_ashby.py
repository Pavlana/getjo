import json
import unittest
from pathlib import Path
from unittest import mock

from sources.ashby import fetch_jobs, parse_jobs

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ashby_jobs.json").read_text())


class ParseJobsTest(unittest.TestCase):
    def test_normalises_to_shared_job_shape(self):
        jobs = parse_jobs("OpenAI", FIXTURE)
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["source"], "ashby")
        self.assertEqual(job["company"], "OpenAI")
        self.assertIsNone(job["score"])
        self.assertTrue(job["id"].startswith("ashby:OpenAI:"))
        self.assertTrue(job["url"].startswith("https://jobs.ashbyhq.com/"))

    def test_london_job_location_and_title(self):
        jobs = parse_jobs("OpenAI", FIXTURE)
        london_job = next(j for j in jobs if "Applied AI Architects" in j["title"])
        self.assertEqual(london_job["location"], "London, UK")
        self.assertTrue(len(london_job["description"]) > 0)

    def test_missing_location_defaults_to_empty_string(self):
        jobs = parse_jobs("OpenAI", {"jobs": [{"id": "1", "title": "X", "jobUrl": "u", "descriptionPlain": ""}]})
        self.assertEqual(jobs[0]["location"], "")

    def test_empty_jobs_list(self):
        self.assertEqual(parse_jobs("OpenAI", {"jobs": []}), [])


class FetchJobsTest(unittest.TestCase):
    """Retry/backoff behavior is tested once, centrally, in tests/test_http.py."""

    @mock.patch("sources.ashby.get_with_retry")
    def test_fetch_builds_correct_url_label_and_parses_response(self, mock_get):
        mock_get.return_value.json.return_value = FIXTURE
        jobs = fetch_jobs("OpenAI", "openai")
        mock_get.assert_called_once_with(
            "https://api.ashbyhq.com/posting-api/job-board/openai", label="ashby"
        )
        self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
