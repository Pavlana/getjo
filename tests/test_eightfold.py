import json
import unittest
from pathlib import Path
from unittest import mock

from sources.eightfold import add_details, fetch_jobs, parse_position

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "eightfold_search.json").read_text())
DETAIL = json.loads((FIXTURES / "eightfold_position.json").read_text())
POSITIONS = SEARCH["data"]["positions"]
BOARD = "apply.careers.microsoft.com/microsoft.com"
API = "https://apply.careers.microsoft.com/api/pcsx"


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    return r


def page(positions, count):
    return response({"data": {"positions": positions, "count": count}})


class ParseTest(unittest.TestCase):
    def test_position_has_shared_shape(self):
        job = parse_position("Microsoft", POSITIONS[0], BOARD, "now")
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "eightfold:Microsoft:200057122")
        self.assertEqual(job["title"], "Senior Electrical Engineer")
        self.assertEqual(job["location"], "United Kingdom, London, London")
        self.assertEqual(job["url"], "https://apply.careers.microsoft.com/careers/job/1970393557002726")

    def test_remote_position_says_remote(self):
        raw = {**POSITIONS[0], "workLocationOption": "remote", "locations": ["United Kingdom"]}
        self.assertEqual(parse_position("Microsoft", raw, BOARD, "now")["location"], "United Kingdom, Remote")

    def test_details_give_plain_text_description(self):
        job = add_details(parse_position("Microsoft", POSITIONS[0], BOARD, "now"), DETAIL)
        self.assertNotIn("<", job["description"])
        self.assertGreater(len(job["description"]), 2000)


@mock.patch("sources.eightfold.get_with_retry")
class FetchJobsTest(unittest.TestCase):
    def test_searches_location_and_fetches_details_only_for_wanted(self, mock_get):
        mock_get.side_effect = [page(POSITIONS, 3), response(DETAIL)]

        jobs = fetch_jobs("Microsoft", BOARD, wanted=lambda title: "Applied AI" in title, search="London, United Kingdom")

        search_url, details_url = (c.args[0] for c in mock_get.call_args_list)
        self.assertTrue(search_url.startswith(f"{API}/search?domain=microsoft.com"))
        self.assertIn("location=London%2C+United+Kingdom", search_url)
        self.assertEqual(details_url, f"{API}/position_details?position_id={POSITIONS[2]['id']}&domain=microsoft.com")
        self.assertEqual(len(jobs), 3)
        self.assertGreater(len(jobs[2]["description"]), 0)
        self.assertEqual(jobs[0]["description"], "")

    def test_pages_by_positions_returned_until_count(self, mock_get):
        mock_get.side_effect = [page(POSITIONS, 5), page(POSITIONS[:2], 5)]

        jobs = fetch_jobs("Microsoft", BOARD, wanted=lambda title: False)

        self.assertIn("start=3", mock_get.call_args.args[0])
        self.assertEqual(len(jobs), 5)

    def test_failed_details_skip_that_position_only(self, mock_get):
        mock_get.side_effect = [page(POSITIONS, 3), Exception("503")]

        with self.assertLogs("sources.eightfold", level="WARNING"):
            jobs = fetch_jobs("Microsoft", BOARD, wanted=lambda title: "Applied AI" in title)

        self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
