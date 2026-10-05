import json
import unittest
from pathlib import Path
from unittest import mock

from sources.adzuna import search

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "adzuna_search.json").read_text())


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    return r


@mock.patch("sources.adzuna.get_with_retry")
class SearchTest(unittest.TestCase):
    def test_returns_company_title_location_only(self, mock_get):
        mock_get.return_value = response({**FIXTURE, "count": 5})

        ads = search("applied AI", "London", "ID", "KEY")

        self.assertEqual(ads[0], {"company": "G-Research", "title": "Applied AI Engineer", "location": "London, UK"})
        self.assertEqual(len(ads), 5)
        self.assertNotIn("TESTAPPID", json.dumps(ads))  # redirect_url carries the app ID; it isn't kept

    def test_searches_titles_near_location_and_redacts_credentials(self, mock_get):
        mock_get.return_value = response({**FIXTURE, "count": 5})

        search("applied AI", "London", "ID", "KEY", max_days_old=14)

        url = mock_get.call_args.args[0]
        self.assertTrue(url.startswith("https://api.adzuna.com/v1/api/jobs/gb/search/1?"))
        for part in ("what=applied+AI", "title_only=applied+AI", "where=London", "max_days_old=14"):
            self.assertIn(part, url)
        self.assertEqual(mock_get.call_args.kwargs["redact"], ("ID", "KEY"))

    def test_pages_until_count_or_page_cap(self, mock_get):
        mock_get.return_value = response({**FIXTURE, "count": 120})
        search("applied AI", "London", "ID", "KEY")
        self.assertEqual(mock_get.call_count, 3)  # 50 + 50 + 20

        mock_get.reset_mock()
        mock_get.return_value = response({**FIXTURE, "count": 5000})
        search("applied AI", "London", "ID", "KEY")
        self.assertEqual(mock_get.call_count, 4)  # MAX_PAGES


if __name__ == "__main__":
    unittest.main()
