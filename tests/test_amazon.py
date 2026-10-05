import json
import unittest
from pathlib import Path
from unittest import mock

from sources.amazon import fetch_jobs, parse_job

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "amazon_jobs.json").read_text())
MULTI, LONDON, COVENTRY = FIXTURE["jobs"]


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    return r


class ParseTest(unittest.TestCase):
    def test_shared_shape_with_target_name_as_company(self):
        job = parse_job("Amazon", LONDON, "now")
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "amazon:Amazon:10551893")
        self.assertEqual(job["company"], "Amazon")
        self.assertEqual(job["location"], "London, United Kingdom")
        self.assertTrue(job["url"].startswith("https://www.amazon.jobs/en/jobs/10551893/"))

    def test_every_listed_place(self):
        self.assertEqual(parse_job("Amazon", MULTI, "now")["location"], "London, United Kingdom; Manchester, United Kingdom")

    def test_description_includes_qualifications_as_plain_text(self):
        description = parse_job("Amazon", COVENTRY, "now")["description"]
        self.assertIn("Basic qualifications: - NVQ Level 3", description)
        self.assertIn("Preferred qualifications:", description)
        self.assertNotIn("<br", description)

    def test_remote_place_says_remote(self):
        raw = {**LONDON, "locations": [json.dumps({"city": "London", "normalizedCountryName": "United Kingdom", "type": "REMOTE"})]}
        self.assertEqual(parse_job("Amazon", raw, "now")["location"], "London, United Kingdom, Remote")


@mock.patch("sources.amazon.get_with_retry")
class FetchJobsTest(unittest.TestCase):
    def test_lists_the_country_page_by_page(self, mock_get):
        mock_get.side_effect = [response({"hits": 101, "jobs": [LONDON] * 100}), response({"hits": 101, "jobs": [COVENTRY]})]

        jobs = fetch_jobs("Amazon", "GBR")

        first, second = (c.args[0] for c in mock_get.call_args_list)
        self.assertIn("normalized_country_code%5B%5D=GBR", first)
        self.assertIn("offset=0", first)
        self.assertIn("offset=100", second)
        self.assertEqual(len(jobs), 101)


if __name__ == "__main__":
    unittest.main()
