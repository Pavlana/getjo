import unittest
from unittest import mock

import requests

from core.llm import complete

API_KEY = "test-key"
MODEL = "claude-haiku-4-5"


def make_response(status_code: int, body: dict | None = None) -> mock.Mock:
    resp = mock.Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


SUCCESS_BODY = {
    "content": [{"type": "text", "text": '{"score": 8}'}],
    "usage": {"input_tokens": 1000, "output_tokens": 50},
}


class CompleteTest(unittest.TestCase):
    @mock.patch("core.llm.requests.post")
    def test_sends_correct_request_and_returns_text(self, mock_post):
        mock_post.return_value = make_response(200, SUCCESS_BODY)

        result = complete("system prompt", "user prompt", 500, model=MODEL, api_key=API_KEY)

        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(kwargs["headers"]["x-api-key"], API_KEY)
        self.assertEqual(kwargs["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(kwargs["json"]["model"], MODEL)
        self.assertEqual(kwargs["json"]["max_tokens"], 500)
        self.assertEqual(kwargs["json"]["system"], "system prompt")
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "user prompt"}])
        self.assertEqual(kwargs["timeout"], 30)
        self.assertNotIn("temperature", kwargs["json"])  # omitted unless asked for
        self.assertEqual(result.text, '{"score": 8}')

    @mock.patch("core.llm.requests.post")
    def test_temperature_is_sent_when_given(self, mock_post):
        mock_post.return_value = make_response(200, SUCCESS_BODY)

        complete("s", "u", 500, model=MODEL, api_key=API_KEY, temperature=0)

        self.assertEqual(mock_post.call_args[1]["json"]["temperature"], 0)

    @mock.patch("core.llm.requests.post")
    def test_reports_token_usage_and_cost(self, mock_post):
        mock_post.return_value = make_response(200, SUCCESS_BODY)

        result = complete("s", "u", 500, model=MODEL, api_key=API_KEY)

        self.assertEqual(result.input_tokens, 1000)
        self.assertEqual(result.output_tokens, 50)
        # 1000 * $1.00/1M + 50 * $5.00/1M = $0.00125
        self.assertAlmostEqual(result.cost, 0.00125, places=6)

    @mock.patch("core.llm.requests.post")
    def test_unpriced_model_returns_none_cost(self, mock_post):
        mock_post.return_value = make_response(200, SUCCESS_BODY)

        result = complete("s", "u", 500, model="some-future-model", api_key=API_KEY)

        self.assertIsNone(result.cost)

    @mock.patch("core.llm.requests.post")
    def test_concatenates_multiple_text_blocks(self, mock_post):
        body = {
            "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }
        mock_post.return_value = make_response(200, body)

        result = complete("s", "u", 500, model=MODEL, api_key=API_KEY)

        self.assertEqual(result.text, "hello world")

    @mock.patch("core.llm.time.sleep")
    @mock.patch("core.llm.requests.post")
    def test_retries_on_429_then_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [make_response(429), make_response(200, SUCCESS_BODY)]

        result = complete("s", "u", 500, model=MODEL, api_key=API_KEY)

        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once()
        self.assertEqual(result.text, '{"score": 8}')

    @mock.patch("core.llm.time.sleep")
    @mock.patch("core.llm.requests.post")
    def test_non_retryable_4xx_raises_immediately(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(400)

        with self.assertRaises(requests.HTTPError):
            complete("s", "u", 500, model=MODEL, api_key=API_KEY)

        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @mock.patch("core.llm.time.sleep")
    @mock.patch("core.llm.requests.post")
    def test_exhausts_retries_on_persistent_500(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(500)

        with self.assertRaises(requests.HTTPError):
            complete("s", "u", 500, model=MODEL, api_key=API_KEY)

        self.assertEqual(mock_post.call_count, 5)


if __name__ == "__main__":
    unittest.main()
