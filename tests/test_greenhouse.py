import json
import unittest
from pathlib import Path
from unittest import mock

from sources.greenhouse import _strip_html, fetch_jobs, parse_jobs

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "greenhouse_jobs.json").read_text())


class StripHtmlTest(unittest.TestCase):
    def test_strips_tags_and_unescapes_entities(self):
        html = "&lt;p&gt;Build &amp; ship &lt;strong&gt;LLM&lt;/strong&gt; apps.&lt;/p&gt;"
        self.assertEqual(_strip_html(html), "Build & ship LLM apps.")

    def test_empty_content_is_empty_string(self):
        self.assertEqual(_strip_html(""), "")


class ParseJobsTest(unittest.TestCase):
    def test_normalises_to_shared_job_shape(self):
        jobs = parse_jobs("Anthropic", FIXTURE)
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "greenhouse:Anthropic:4461450008")
        self.assertEqual(job["source"], "greenhouse")
        self.assertEqual(job["company"], "Anthropic")
        self.assertEqual(job["title"], "Account Executive, AI Native")
        self.assertEqual(job["url"], "https://job-boards.greenhouse.io/anthropic/jobs/4461450008")
        self.assertIsNone(job["score"])

    def test_description_has_no_html_tags(self):
        jobs = parse_jobs("Anthropic", FIXTURE)
        for job in jobs:
            self.assertNotIn("<", job["description"])
            self.assertNotIn("&lt;", job["description"])

    def test_london_job_location_preserved(self):
        jobs = parse_jobs("Anthropic", FIXTURE)
        london_job = next(j for j in jobs if j["id"] == "greenhouse:Anthropic:5183044008")
        self.assertIn("London", london_job["location"])

    def test_missing_location_defaults_to_empty_string(self):
        jobs = parse_jobs("Anthropic", {"jobs": [{"id": 1, "title": "X", "absolute_url": "u", "content": ""}]})
        self.assertEqual(jobs[0]["location"], "")

    def test_empty_jobs_list(self):
        self.assertEqual(parse_jobs("Anthropic", {"jobs": []}), [])


class FetchJobsTest(unittest.TestCase):
    """Retry/backoff behavior is tested once, centrally, in tests/test_http.py."""

    @mock.patch("sources.greenhouse.get_with_retry")
    def test_fetch_builds_correct_url_label_and_parses_response(self, mock_get):
        mock_get.return_value.json.return_value = FIXTURE
        jobs = fetch_jobs("Anthropic", "anthropic")
        mock_get.assert_called_once_with(
            "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true", label="greenhouse"
        )
        self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
