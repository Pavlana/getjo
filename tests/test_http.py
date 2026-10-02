import unittest
from unittest import mock

import requests

from core.http import get_with_retry, post_with_retry


def make_response(status_code: int) -> mock.Mock:
    resp = mock.Mock(spec=requests.Response)
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


class GetWithRetryTest(unittest.TestCase):
    @mock.patch("core.http.requests.get")
    def test_success_returns_response_with_timeout(self, mock_get):
        mock_get.return_value = make_response(200)
        response = get_with_retry("https://example.com/jobs", label="test")
        mock_get.assert_called_once_with("https://example.com/jobs", timeout=10, auth=None)
        self.assertEqual(response.status_code, 200)

    @mock.patch("core.http.time.sleep")
    @mock.patch("core.http.requests.get")
    def test_retries_on_429_then_succeeds(self, mock_get, mock_sleep):
        mock_get.side_effect = [make_response(429), make_response(200)]
        response = get_with_retry("https://example.com/jobs", label="test")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)
        self.assertEqual(response.status_code, 200)

    @mock.patch("core.http.time.sleep")
    @mock.patch("core.http.requests.get")
    def test_backoff_doubles_each_retry(self, mock_get, mock_sleep):
        mock_get.side_effect = [make_response(500), make_response(500), make_response(200)]
        get_with_retry("https://example.com/jobs", label="test")
        mock_sleep.assert_has_calls([mock.call(1.0), mock.call(2.0)])

    @mock.patch("core.http.time.sleep")
    @mock.patch("core.http.requests.get")
    def test_non_retryable_4xx_raises_immediately(self, mock_get, mock_sleep):
        mock_get.return_value = make_response(404)
        with self.assertRaises(requests.HTTPError):
            get_with_retry("https://example.com/jobs", label="test")
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    @mock.patch("core.http.time.sleep")
    @mock.patch("core.http.requests.get")
    def test_exhausts_retries_on_persistent_500(self, mock_get, mock_sleep):
        mock_get.return_value = make_response(500)
        with self.assertRaises(requests.HTTPError):
            get_with_retry("https://example.com/jobs", label="test")
        self.assertEqual(mock_get.call_count, 5)

    @mock.patch("core.http.time.sleep")
    @mock.patch("core.http.requests.get")
    def test_retries_on_network_exception(self, mock_get, mock_sleep):
        mock_get.side_effect = [requests.ConnectionError("boom"), make_response(200)]
        response = get_with_retry("https://example.com/jobs", label="test")
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(response.status_code, 200)

    @mock.patch("core.http.time.sleep")
    @mock.patch("core.http.requests.get")
    def test_exhausts_retries_on_persistent_network_exception(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.ConnectionError("boom")
        with self.assertRaises(requests.ConnectionError):
            get_with_retry("https://example.com/jobs", label="test")
        self.assertEqual(mock_get.call_count, 5)


class PostWithRetryTest(unittest.TestCase):
    """The retry loop is shared with get_with_retry; this checks the POST is sent and retried."""

    @mock.patch("core.http.time.sleep")
    @mock.patch("core.http.requests.post")
    def test_sends_json_body_with_timeout_and_retries_on_5xx(self, mock_post, mock_sleep):
        mock_post.side_effect = [make_response(503), make_response(200)]
        response = post_with_retry("https://example.com/jobs", {"limit": 20}, label="test")
        self.assertEqual(mock_post.call_count, 2)
        mock_post.assert_called_with("https://example.com/jobs", json={"limit": 20}, timeout=10)
        self.assertEqual(response.status_code, 200)

    @mock.patch("core.http.requests.post")
    def test_non_retryable_4xx_raises_immediately(self, mock_post):
        mock_post.return_value = make_response(404)
        with self.assertRaises(requests.HTTPError):
            post_with_retry("https://example.com/jobs", {}, label="test")
        self.assertEqual(mock_post.call_count, 1)



if __name__ == "__main__":
    unittest.main()
