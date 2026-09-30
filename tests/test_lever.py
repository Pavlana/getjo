import json
import unittest
from pathlib import Path
from unittest import mock

from sources.lever import fetch_jobs, parse_jobs

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "lever_jobs.json").read_text())


class ParseJobsTest(unittest.TestCase):
    def test_normalises_to_shared_job_shape(self):
        jobs = parse_jobs("Palantir", FIXTURE)
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["source"], "lever")
        self.assertEqual(job["company"], "Palantir")
        self.assertIsNone(job["score"])
        self.assertTrue(job["id"].startswith("lever:Palantir:"))
        self.assertTrue(job["url"].startswith("https://jobs.lever.co/"))

    def test_london_job_location_and_title(self):
        jobs = parse_jobs("Palantir", FIXTURE)
        london_job = next(j for j in jobs if "Backend Software Engineer" in j["title"])
        self.assertIn("London", london_job["location"])
        self.assertTrue(len(london_job["description"]) > 0)

    def test_missing_location_defaults_to_empty_string(self):
        jobs = parse_jobs("Palantir", [{"id": "1", "text": "X", "hostedUrl": "u", "descriptionPlain": ""}])
        self.assertEqual(jobs[0]["location"], "")

    def test_empty_postings_list(self):
        self.assertEqual(parse_jobs("Palantir", []), [])


class FetchJobsTest(unittest.TestCase):
    """Retry/backoff behavior is tested once, centrally, in tests/test_http.py."""

    @mock.patch("sources.lever.get_with_retry")
    def test_fetch_builds_correct_url_label_and_parses_response(self, mock_get):
        mock_get.return_value.json.return_value = FIXTURE
        jobs = fetch_jobs("Palantir", "palantir")
        mock_get.assert_called_once_with(
            "https://api.lever.co/v0/postings/palantir?mode=json", label="lever"
        )
        self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
