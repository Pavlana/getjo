import unittest
from unittest import mock

import requests

from jobs.discover import hiring_companies, probe, report, slug_candidates

FILTER = {"title_include": ["ai engineer"], "title_exclude": ["intern"], "locations": ["london"]}


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    return r


class SlugTest(unittest.TestCase):
    def test_joined_and_hyphenated_without_legal_suffixes(self):
        self.assertEqual(slug_candidates("Just Eat Takeaway.com"), ["justeattakeaway", "just-eat-takeaway"])
        self.assertEqual(slug_candidates("Hackajob Ltd"), ["hackajob"])
        self.assertEqual(slug_candidates("G-Research"), ["gresearch", "g-research"])
        self.assertEqual(slug_candidates("Norton Rose Fulbright LLP"), ["nortonrosefulbright", "norton-rose-fulbright"])


@mock.patch("jobs.discover.get_with_retry")
class ProbeTest(unittest.TestCase):
    def test_first_board_with_jobs_wins(self, mock_get):
        def answer(url, label):
            if "greenhouse" in url:
                raise requests.HTTPError("404")
            if "ashbyhq" in url:
                return response({"jobs": [{"title": "AI Engineer"}, {"title": "Designer"}]})
            raise AssertionError("should stop at the first hit")
        mock_get.side_effect = answer

        self.assertEqual(probe("Fuse Energy"), {"source": "ashby", "board": "fuseenergy", "titles": ["AI Engineer", "Designer"]})

    def test_boards_with_no_jobs_dont_count(self, mock_get):
        def answer(url, label):
            if "smartrecruiters" in url:
                return response({"totalFound": 0, "content": []})
            raise requests.HTTPError("404")
        mock_get.side_effect = answer

        self.assertIsNone(probe("Nobody Ltd"))
        self.assertEqual(mock_get.call_count, 4)  # one name ("nobody"), four systems


@mock.patch("jobs.discover.adzuna.search")
class HiringCompaniesTest(unittest.TestCase):
    def test_titles_grouped_by_company_across_keywords_without_repeats(self, mock_search):
        mock_search.side_effect = [
            [{"company": "Acme", "title": "AI Engineer", "location": "London"},
             {"company": "", "title": "AI Engineer", "location": "London"}],
            [{"company": "Acme", "title": "AI Engineer", "location": "London"},
             {"company": "Acme", "title": "Applied AI Lead", "location": "London"}],
        ]
        found = hiring_companies({"keywords": ["ai engineer", "applied ai"], "location": "London"}, "ID", "KEY")
        self.assertEqual(found, {"Acme": ["AI Engineer", "Applied AI Lead"]})
        self.assertEqual(mock_search.call_args.kwargs["max_days_old"], 30)


class ReportTest(unittest.TestCase):
    def test_targets_dropped_boards_reported_and_blocks_only_for_found(self):
        hiring = {"Kainos Software Ltd": ["AI Engineer"], "Acme": ["AI Engineer", "Senior AI Engineer"], "Quiet Co": ["AI Engineer"]}
        boards = {"Acme": {"source": "greenhouse", "board": "acme", "titles": ["Senior AI Engineer", "AI Engineer Intern", "Chef"]}}

        text = report(hiring, [{"name": "Kainos"}], {"Quiet Co"}, FILTER, probe_fn=boards.get)

        self.assertNotIn("Kainos", text)  # already a target
        self.assertIn("2 companies hiring", text)
        self.assertIn("Acme | 2 |  | greenhouse:acme | 3 jobs, 1 matching | e.g. Senior AI Engineer", text)
        self.assertIn("Quiet Co | 1 | yes | not found | e.g. ad: AI Engineer", text)
        self.assertIn('[[company]]\nname = "Acme"\nsource = "greenhouse"\nboard = "acme"\n', text)
        self.assertEqual(text.count("[[company]]"), 1)
        self.assertLess(text.index("Acme |"), text.index("Quiet Co |"))  # most ads first


if __name__ == "__main__":
    unittest.main()
