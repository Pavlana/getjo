import json
import unittest
from pathlib import Path
from unittest import mock

from sources.reed import add_details, fetch_jobs, parse_result

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "reed_search.json").read_text())
DETAIL = json.loads((FIXTURES / "reed_job_detail.json").read_text())
NRF, FDM, CHAMBERS, ITOL, METRO = SEARCH["results"]
AUTH = ("key", "")


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    return r


def page(*results, total=None):
    return response({"results": list(results), "totalResults": len(results) if total is None else total})


class ParseTest(unittest.TestCase):
    def test_result_has_shared_job_shape_and_employer_as_company(self):
        job = parse_result(NRF, "London", "now")
        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "reed:Norton Rose Fulbright LLP:57364884")
        self.assertEqual(job["company"], "Norton Rose Fulbright LLP")
        self.assertEqual(job["location"], "London")
        self.assertEqual(job["url"], "https://www.reed.co.uk/jobs/ai-engineer/57364884")

    def test_postcode_location_gets_the_searched_place(self):
        self.assertEqual(parse_result(METRO, "London", "now")["location"], "WC1B5HA, London")

    def test_details_give_full_plain_text_description(self):
        job = add_details(parse_result(NRF, "London", "now"), DETAIL)
        self.assertNotIn("<", job["description"])
        self.assertGreater(len(job["description"]), 3000)  # search results only carry ~450 characters


@mock.patch("sources.reed.get_with_retry")
class FetchJobsTest(unittest.TestCase):
    def test_searches_direct_employers_with_key_as_auth_and_details_only_wanted(self, mock_get):
        mock_get.side_effect = [page(NRF, FDM), response(DETAIL)]

        jobs = fetch_jobs(["AI engineer"], "London", "key", wanted=lambda title: title == "AI Engineer")

        search_url, details_url = (c.args[0] for c in mock_get.call_args_list)
        self.assertIn("keywords=AI+engineer", search_url)
        self.assertIn("locationName=London", search_url)
        self.assertIn("postedByDirectEmployer=true", search_url)
        self.assertEqual(details_url, "https://www.reed.co.uk/api/1.0/jobs/57364884")
        self.assertTrue(all(c.kwargs["auth"] == AUTH for c in mock_get.call_args_list))
        self.assertEqual(len(jobs), 2)
        self.assertGreater(len(jobs[0]["description"]), 3000)
        self.assertEqual(jobs[1]["description"], "")  # not wanted: no details request

    def test_same_job_from_two_keywords_is_returned_once(self, mock_get):
        mock_get.side_effect = [page(NRF, FDM), page(FDM, CHAMBERS)]

        jobs = fetch_jobs(["AI engineer", "applied AI"], "London", "key", wanted=lambda title: False)

        self.assertEqual([j["company"] for j in jobs], ["Norton Rose Fulbright LLP", "FDM Group", "Chambers and Partners"])

    def test_pages_until_total_results(self, mock_get):
        mock_get.side_effect = [page(*[FDM] * 100, total=101), page(NRF, total=101)]

        fetch_jobs(["AI engineer"], "London", "key", wanted=lambda title: False)

        self.assertIn("resultsToSkip=100", mock_get.call_args.args[0])

    def test_skipped_employers_dropped_before_details_whole_words_only(self, mock_get):
        mock_get.side_effect = [page(NRF, ITOL, METRO), response(DETAIL)]

        jobs = fetch_jobs(
            ["AI engineer"], "London", "key", wanted=lambda title: True,
            skip_employers=["Norton Rose Fulbright", "ITOL Recruit", "Metr"],  # "Metr" is not a whole word
        )

        self.assertEqual(mock_get.call_count, 2)  # one search + details for Metro Bank only
        self.assertEqual([j["company"] for j in jobs], ["Metro Bank"])

    def test_agency_results_included_when_not_direct_only(self, mock_get):
        mock_get.side_effect = [page()]
        fetch_jobs(["AI engineer"], "London", "key", wanted=lambda title: False, direct_employers_only=False)
        self.assertNotIn("postedByDirectEmployer", mock_get.call_args.args[0])

    def test_failed_details_skip_that_job_only(self, mock_get):
        mock_get.side_effect = [page(NRF, FDM), Exception("404 Not Found")]

        with self.assertLogs("sources.reed", level="WARNING"):
            jobs = fetch_jobs(["AI engineer"], "London", "key", wanted=lambda title: title == "AI Engineer")

        self.assertEqual([j["company"] for j in jobs], ["FDM Group"])


if __name__ == "__main__":
    unittest.main()
