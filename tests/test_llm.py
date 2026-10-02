import unittest
from unittest import mock

import requests

from core.llm import JobError, ServiceError, complete

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

        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["temperature"], 0)
        self.assertNotIn("thinking", payload)

    @mock.patch("core.llm.requests.post")
    def test_sonnet_5_gets_no_temperature_and_thinking_off(self, mock_post):
        mock_post.return_value = make_response(200, SUCCESS_BODY)

        complete("s", "u", 500, model="claude-sonnet-5", api_key=API_KEY, temperature=0)

        payload = mock_post.call_args[1]["json"]
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["thinking"], {"type": "disabled"})

    @mock.patch("core.llm.requests.post")
    def test_sonnet_5_cost(self, mock_post):
        mock_post.return_value = make_response(200, SUCCESS_BODY)

        result = complete("s", "u", 500, model="claude-sonnet-5", api_key=API_KEY)

        # 1000 * $2.00/1M + 50 * $10.00/1M = $0.0025
        self.assertAlmostEqual(result.cost, 0.0025, places=6)

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

def api_error(error_type: str, message: str) -> dict:
    return {"type": "error", "error": {"type": error_type, "message": message}}


CREDIT = api_error("invalid_request_error", "Your credit balance is too low to access the Anthropic API.")


@mock.patch("core.llm.time.sleep")
@mock.patch("core.llm.requests.post")
class ErrorTest(unittest.TestCase):
    def _call(self):
        return complete("s", "u", 500, model=MODEL, api_key=API_KEY)

    def test_other_400_is_a_job_error_with_the_apis_explanation(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(400, api_error("invalid_request_error", "prompt is too long"))

        with self.assertRaisesRegex(JobError, r"^400 invalid_request_error: prompt is too long$"):
            self._call()
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    def test_no_credit_is_a_service_error_and_not_retried(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(400, CREDIT)

        with self.assertRaisesRegex(ServiceError, "credit balance is too low"):
            self._call()
        self.assertEqual(mock_post.call_count, 1)

    def test_bad_key_and_no_permission_are_service_errors(self, mock_post, mock_sleep):
        for status, error_type in ((401, "authentication_error"), (403, "permission_error")):
            mock_post.return_value = make_response(status, api_error(error_type, "nope"))
            with self.assertRaisesRegex(ServiceError, f"^{status} {error_type}: nope$"):
                self._call()

    def test_persistent_500_is_a_service_error_after_all_retries(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(500, api_error("api_error", "Internal server error"))

        with self.assertRaisesRegex(ServiceError, "500 api_error"):
            self._call()
        self.assertEqual(mock_post.call_count, 5)

    def test_persistent_429_is_a_service_error_after_all_retries(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(429, api_error("rate_limit_error", "slow down"))

        with self.assertRaises(ServiceError):
            self._call()
        self.assertEqual(mock_post.call_count, 5)

    def test_persistent_network_failure_is_a_service_error(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.ConnectionError("unreachable")

        with self.assertRaisesRegex(ServiceError, "network: unreachable"):
            self._call()
        self.assertEqual(mock_post.call_count, 5)

    def test_error_without_a_json_body_still_reports_the_status(self, mock_post, mock_sleep):
        resp = make_response(400)
        resp.json.side_effect = ValueError("not json")
        mock_post.return_value = resp

        with self.assertRaisesRegex(JobError, r"^400 unknown_error$"):
            self._call()


if __name__ == "__main__":
    unittest.main()
