import json
import unittest
from pathlib import Path
from unittest import mock

from sources.workable import fetch_jobs, parse_jobs

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "workable_jobs.json").read_text())


class ParseJobsTest(unittest.TestCase):
    def test_normalises_to_shared_job_shape(self):
        jobs = parse_jobs("Hugging Face", FIXTURE)
        self.assertEqual(len(jobs), 3)
        job = jobs[0]
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "workable:Hugging Face:F4C096B22E")
        self.assertEqual(job["url"], "https://apply.workable.com/j/F4C096B22E")
        self.assertNotIn("<", job["description"])
        self.assertGreater(len(job["description"]), 1000)

    def test_remote_role_location_names_place_and_remote(self):
        self.assertEqual(parse_jobs("Hugging Face", FIXTURE)[0]["location"], "Paris, Île-de-France, France, Remote")

    def test_several_places_and_fallback_to_top_level_fields(self):
        raw = {"shortcode": "X", "title": "AI Engineer", "telecommuting": False, "description": "",
               "locations": [{"city": "London", "country": "United Kingdom"}, {"city": "Leeds", "country": "United Kingdom"}]}
        self.assertEqual(parse_jobs("Co", {"jobs": [raw]})[0]["location"], "London, United Kingdom; Leeds, United Kingdom")
        raw = {"shortcode": "Y", "title": "AI Engineer", "telecommuting": False, "city": "London", "country": "United Kingdom"}
        self.assertEqual(parse_jobs("Co", {"jobs": [raw]})[0]["location"], "London, United Kingdom")

    def test_no_openings(self):
        self.assertEqual(parse_jobs("BenevolentAI", {"name": "BenevolentAI", "jobs": []}), [])


class FetchJobsTest(unittest.TestCase):
    @mock.patch("sources.workable.get_with_retry")
    def test_fetch_builds_correct_url_label_and_parses_response(self, mock_get):
        mock_get.return_value.json.return_value = FIXTURE
        jobs = fetch_jobs("Hugging Face", "huggingface")
        mock_get.assert_called_once_with(
            "https://apply.workable.com/api/v1/widget/accounts/huggingface?details=true", label="workable"
        )
        self.assertEqual(len(jobs), 3)


if __name__ == "__main__":
    unittest.main()
