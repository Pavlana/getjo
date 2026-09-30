import json
import unittest
from pathlib import Path
from unittest import mock

import requests

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


def make_response(status_code: int, json_body=None) -> mock.Mock:
    resp = mock.Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


class FetchJobsTest(unittest.TestCase):
    @mock.patch("sources.ashby.requests.get")
    def test_fetch_builds_correct_url_and_parses_response(self, mock_get):
        mock_get.return_value = make_response(200, FIXTURE)
        jobs = fetch_jobs("OpenAI", "openai")
        mock_get.assert_called_once_with(
            "https://api.ashbyhq.com/posting-api/job-board/openai", timeout=10
        )
        self.assertEqual(len(jobs), 2)

    @mock.patch("sources.ashby.time.sleep")
    @mock.patch("sources.ashby.requests.get")
    def test_retries_on_429_then_succeeds(self, mock_get, mock_sleep):
        mock_get.side_effect = [make_response(429), make_response(200, FIXTURE)]
        jobs = fetch_jobs("OpenAI", "openai")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()
        self.assertEqual(len(jobs), 2)

    @mock.patch("sources.ashby.time.sleep")
    @mock.patch("sources.ashby.requests.get")
    def test_non_retryable_4xx_raises_immediately(self, mock_get, mock_sleep):
        mock_get.return_value = make_response(404)
        with self.assertRaises(requests.HTTPError):
            fetch_jobs("OpenAI", "wrong-board")
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    @mock.patch("sources.ashby.time.sleep")
    @mock.patch("sources.ashby.requests.get")
    def test_exhausts_retries_on_persistent_500(self, mock_get, mock_sleep):
        mock_get.return_value = make_response(500)
        with self.assertRaises(requests.HTTPError):
            fetch_jobs("OpenAI", "openai")
        self.assertEqual(mock_get.call_count, 5)


if __name__ == "__main__":
    unittest.main()
