import json
import unittest
from pathlib import Path
from unittest import mock

import requests

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


def make_response(status_code: int, json_body: dict | None = None) -> mock.Mock:
    resp = mock.Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


class FetchJobsTest(unittest.TestCase):
    @mock.patch("sources.greenhouse.requests.get")
    def test_fetch_builds_correct_url_and_parses_response(self, mock_get):
        mock_get.return_value = make_response(200, FIXTURE)
        jobs = fetch_jobs("Anthropic", "anthropic")
        mock_get.assert_called_once_with(
            "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true", timeout=10
        )
        self.assertEqual(len(jobs), 2)

    @mock.patch("sources.greenhouse.time.sleep")
    @mock.patch("sources.greenhouse.requests.get")
    def test_retries_on_429_then_succeeds(self, mock_get, mock_sleep):
        mock_get.side_effect = [make_response(429), make_response(200, FIXTURE)]
        jobs = fetch_jobs("Anthropic", "anthropic")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()
        self.assertEqual(len(jobs), 2)

    @mock.patch("sources.greenhouse.time.sleep")
    @mock.patch("sources.greenhouse.requests.get")
    def test_non_retryable_4xx_raises_immediately(self, mock_get, mock_sleep):
        mock_get.return_value = make_response(404)
        with self.assertRaises(requests.HTTPError):
            fetch_jobs("Anthropic", "wrong-board")
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    @mock.patch("sources.greenhouse.time.sleep")
    @mock.patch("sources.greenhouse.requests.get")
    def test_exhausts_retries_on_persistent_500(self, mock_get, mock_sleep):
        mock_get.return_value = make_response(500)
        with self.assertRaises(requests.HTTPError):
            fetch_jobs("Anthropic", "anthropic")
        self.assertEqual(mock_get.call_count, 5)


if __name__ == "__main__":
    unittest.main()
