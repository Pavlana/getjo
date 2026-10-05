import json
import unittest
from pathlib import Path
from unittest import mock

from sources.workday import add_details, fetch_jobs, parse_listing

FIXTURES = Path(__file__).parent / "fixtures"
LIST = json.loads((FIXTURES / "workday_jobs.json").read_text())
DETAIL = json.loads((FIXTURES / "workday_job_detail.json").read_text())
BOARD = "kainos.wd3/Kainos"
API = "https://kainos.wd3.myworkdayjobs.com/wday/cxs/kainos/Kainos"


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    return r


class ParseTest(unittest.TestCase):
    def test_listing_has_shared_job_shape_and_requisition_id(self):
        job = parse_listing("Kainos", LIST["jobPostings"][0], BOARD, "2026-10-02T00:00:00Z")
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "workday:Kainos:JR_18460")
        self.assertEqual(job["title"], "Lead Data Engineer")
        self.assertEqual(job["location"], "4 Locations")
        self.assertTrue(job["url"].startswith("https://kainos.wd3.myworkdayjobs.com/Kainos/job/"))
        self.assertEqual(job["description"], "")

    def test_details_give_every_location_and_plain_text_description(self):
        job = parse_listing("Kainos", LIST["jobPostings"][0], BOARD, "2026-10-02T00:00:00Z")
        job = add_details(job, DETAIL)
        self.assertEqual(job["location"], "Belfast; London; Homeworker - UK; Birmingham")
        self.assertNotIn("<", job["description"])
        self.assertGreater(len(job["description"]), 1000)
        self.assertEqual(job["id"], "workday:Kainos:JR_18460")  # unchanged by details


@mock.patch("sources.workday.get_with_retry")
@mock.patch("sources.workday.post_with_retry")
class FetchJobsTest(unittest.TestCase):
    def test_details_fetched_only_for_wanted_titles(self, mock_post, mock_get):
        mock_post.return_value = response(LIST)
        mock_get.return_value = response(DETAIL)

        jobs = fetch_jobs("Kainos", BOARD, wanted=lambda title: "engineer" in title.lower())

        mock_post.assert_called_once_with(
            f"{API}/jobs", {"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}}, label="workday"
        )
        mock_get.assert_called_once_with(f"{API}{LIST['jobPostings'][0]['externalPath']}", label="workday")
        self.assertEqual(len(jobs), 3)  # the entry with no title is skipped
        self.assertIn("London", jobs[0]["location"])
        self.assertEqual(jobs[1]["description"], "")  # not wanted: as listed

    def test_pages_until_total_using_the_first_pages_total(self, mock_post, mock_get):
        first = {"total": 21, "jobPostings": [LIST["jobPostings"][1]] * 20}
        second = {"total": 0, "jobPostings": [LIST["jobPostings"][2]]}  # later pages may report 0
        mock_post.side_effect = [response(first), response(second)]

        jobs = fetch_jobs("Kainos", BOARD, wanted=lambda title: False)

        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_post.call_args.args[1]["offset"], 20)
        self.assertEqual(len(jobs), 21)
        mock_get.assert_not_called()

    def test_search_text_sent_to_the_site(self, mock_post, mock_get):
        mock_post.return_value = response({"total": 0, "jobPostings": []})
        fetch_jobs("Citi", "citi.wd5/2", wanted=lambda title: False, search="London")
        self.assertEqual(mock_post.call_args.args[1]["searchText"], "London")

    def test_warns_when_listing_hits_workdays_cap(self, mock_post, mock_get):
        mock_post.return_value = response({"total": 2000, "jobPostings": []})
        with self.assertLogs("sources.workday", level="WARNING") as logs:
            fetch_jobs("Citi", "citi.wd5/2", wanted=lambda title: False)
        self.assertIn("set `search` for this target", logs.output[0])

    def test_failed_detail_skips_that_job_only(self, mock_post, mock_get):
        mock_post.return_value = response(LIST)
        mock_get.side_effect = Exception("404 Not Found")

        with self.assertLogs("sources.workday", level="WARNING"):
            jobs = fetch_jobs("Kainos", BOARD, wanted=lambda title: title == "Lead Data Engineer")

        self.assertEqual([j["title"] for j in jobs], [p["title"] for p in LIST["jobPostings"][1:3]])


if __name__ == "__main__":
    unittest.main()
