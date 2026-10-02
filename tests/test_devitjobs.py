import json
import unittest
from pathlib import Path
from unittest import mock

from sources.devitjobs import LIST_URL, RSS_URL, _location, descriptions_by_slug, fetch_jobs

FIXTURES = Path(__file__).parent / "fixtures"
RSS = (FIXTURES / "devitjobs_rss.xml").read_text(encoding="utf-8")
LIST = json.loads((FIXTURES / "devitjobs_jobs_light.json").read_text())
ELSEVIER = "Elsevier-Principal-Software-Engineer--Principal-AI-Engineer---London"


def responses(mock_get, rss=RSS, listed=LIST):
    feed, jobs = mock.Mock(), mock.Mock()
    feed.text = rss
    jobs.json.return_value = listed
    mock_get.side_effect = [feed, jobs]


class ParseTest(unittest.TestCase):
    def test_descriptions_keyed_by_slug_as_plain_text(self):
        descriptions = descriptions_by_slug(RSS)
        self.assertEqual(len(descriptions), 4)
        self.assertIn(ELSEVIER, descriptions)
        self.assertNotIn("<", descriptions[ELSEVIER])
        self.assertGreater(len(descriptions[ELSEVIER]), 1000)

    def test_location_names_city_country_and_remote(self):
        self.assertEqual(_location({"actualCity": "London", "workplace": "hybrid"}), "London, United Kingdom")
        self.assertEqual(_location({"actualCity": "Remote", "workplace": "remote"}), "United Kingdom, Remote")
        self.assertEqual(_location({"actualCity": "united kingdom", "workplace": "office"}), "United Kingdom")
        self.assertEqual(_location({"actualCity": None, "workplace": "office"}), "United Kingdom")


@mock.patch("sources.devitjobs.get_with_retry")
class FetchJobsTest(unittest.TestCase):
    def test_joins_feed_and_list_dropping_jobs_missing_from_either(self, mock_get):
        responses(mock_get)

        with self.assertLogs("sources.devitjobs", level="INFO") as logs:
            jobs = fetch_jobs()

        self.assertEqual([c.args[0] for c in mock_get.call_args_list], [RSS_URL, LIST_URL])
        # 4 feed items and 4 list entries; 3 are in both. The feed-only item has no location,
        # the list-only job has no description.
        self.assertEqual([j["company"] for j in jobs], ["Elsevier", "Companies House", "Kainos"])
        self.assertIn("1 feed items not in the job list", logs.output[0])

    def test_job_has_shared_shape_list_fields_and_feed_description(self, mock_get):
        responses(mock_get)

        job = fetch_jobs()[0]

        self.assertEqual(
            set(job),
            {"id", "source", "company", "title", "location", "url", "description", "first_seen", "score"},
        )
        self.assertEqual(job["id"], "devitjobs:Elsevier:6ab82c39e7e76405a3d3f163")
        self.assertEqual(job["title"], "Principal Software Engineer / Principal AI Engineer - London")
        self.assertEqual(job["location"], "London, United Kingdom")
        self.assertEqual(job["url"], f"https://devitjobs.uk/jobs/{ELSEVIER}")
        self.assertGreater(len(job["description"]), 1000)

    def test_skipped_employers_dropped(self, mock_get):
        responses(mock_get)
        jobs = fetch_jobs(skip_employers=["Kainos", "Companies"])  # whole words: "Companies" matches "Companies House"
        self.assertEqual([j["company"] for j in jobs], ["Elsevier"])


if __name__ == "__main__":
    unittest.main()
