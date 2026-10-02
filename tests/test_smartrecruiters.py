import json
import unittest
from pathlib import Path
from unittest import mock

from sources.smartrecruiters import add_details, fetch_jobs, parse_listing

FIXTURES = Path(__file__).parent / "fixtures"
LIST = json.loads((FIXTURES / "smartrecruiters_jobs.json").read_text())
DETAIL = json.loads((FIXTURES / "smartrecruiters_job_detail.json").read_text())
API = "https://api.smartrecruiters.com/v1/companies/wise/postings"


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    return r


class ParseTest(unittest.TestCase):
    def test_listing_has_shared_job_shape_and_clean_location(self):
        job = parse_listing("Wise", LIST["content"][0], "wise", "2026-10-02T00:00:00Z")
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "smartrecruiters:Wise:744000153192361")
        self.assertEqual(job["title"], "Software Engineer - FX Markets")
        self.assertEqual(job["location"], "London, United Kingdom")
        self.assertEqual(job["description"], "")

    def test_remote_role_says_remote(self):
        raw = {**LIST["content"][0], "location": {"fullLocation": "London, , United Kingdom", "remote": True}}
        self.assertEqual(parse_listing("Wise", raw, "wise", "now")["location"], "London, United Kingdom, Remote")

    def test_details_give_public_url_and_all_sections_as_text(self):
        job = add_details(parse_listing("Wise", LIST["content"][0], "wise", "now"), DETAIL)
        self.assertEqual(job["url"], "https://jobs.smartrecruiters.com/Wise/744000153192361-software-engineer-fx-markets")
        self.assertNotIn("<", job["description"])
        self.assertGreater(len(job["description"]), 3000)  # all four sections, not just the first


@mock.patch("sources.smartrecruiters.get_with_retry")
class FetchJobsTest(unittest.TestCase):
    def test_details_fetched_only_for_wanted_titles(self, mock_get):
        mock_get.side_effect = [response(LIST), response(DETAIL)]

        jobs = fetch_jobs("Wise", "wise", wanted=lambda title: "engineer" in title.lower())

        self.assertEqual(
            [c.args[0] for c in mock_get.call_args_list],
            [f"{API}?limit=100&offset=0", f"{API}/744000153192361"],
        )
        self.assertEqual(len(jobs), 2)
        self.assertGreater(len(jobs[0]["description"]), 0)
        self.assertEqual(jobs[1]["description"], "")

    def test_pages_until_total_found(self, mock_get):
        first = {"totalFound": 101, "content": [LIST["content"][1]] * 100}
        second = {"totalFound": 101, "content": [LIST["content"][1]]}
        mock_get.side_effect = [response(first), response(second)]

        jobs = fetch_jobs("Wise", "wise", wanted=lambda title: False)

        self.assertEqual(mock_get.call_args.args[0], f"{API}?limit=100&offset=100")
        self.assertEqual(len(jobs), 101)

    def test_failed_detail_skips_that_job_only(self, mock_get):
        mock_get.side_effect = [response(LIST), Exception("404 Not Found")]

        with self.assertLogs("sources.smartrecruiters", level="WARNING"):
            jobs = fetch_jobs("Wise", "wise", wanted=lambda title: "engineer" in title.lower())

        self.assertEqual([j["title"] for j in jobs], ["Senior Product Analyst (IC2), SEND"])


if __name__ == "__main__":
    unittest.main()
