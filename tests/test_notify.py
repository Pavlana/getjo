import unittest
from unittest import mock

import requests

from core.notify import _split, send_telegram

TOKEN = "test-token"
CHAT_ID = "12345"


def make_response(status_code: int) -> mock.Mock:
    resp = mock.Mock(spec=requests.Response)
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


class SplitTest(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(_split("hello"), ["hello"])

    def test_splits_on_newline_boundary(self):
        text = ("a" * 3990) + "\n" + ("b" * 20)
        chunks = _split(text, max_chars=4000)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("a"))
        self.assertEqual(chunks[1], "b" * 20)

    def test_hard_cut_when_no_newline(self):
        text = "a" * 9000
        chunks = _split(text, max_chars=4000)
        self.assertEqual(len(chunks), 3)
        self.assertEqual("".join(chunks), text)

    def test_reassembles_to_original_minus_split_newlines(self):
        text = "line one\n" * 1000  # well over 4000 chars, clean newlines throughout
        chunks = _split(text)
        self.assertEqual("\n".join(c.strip("\n") for c in chunks if c.strip("\n")), text.strip())


class SendTelegramTest(unittest.TestCase):
    @mock.patch("core.notify.requests.post")
    def test_sends_single_message(self, mock_post):
        mock_post.return_value = make_response(200)
        send_telegram("hello from job-radar", token=TOKEN, chat_id=CHAT_ID)
        mock_post.assert_called_once()
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        self.assertIn(TOKEN, url)
        self.assertEqual(kwargs["json"], {"chat_id": CHAT_ID, "text": "hello from job-radar"})
        self.assertEqual(kwargs["timeout"], 10)

    @mock.patch("core.notify.requests.post")
    def test_sends_multiple_messages_in_order(self, mock_post):
        mock_post.return_value = make_response(200)
        long_text = "x" * 9000
        send_telegram(long_text, token=TOKEN, chat_id=CHAT_ID)
        self.assertEqual(mock_post.call_count, 3)
        sent = "".join(call.kwargs["json"]["text"] for call in mock_post.call_args_list)
        self.assertEqual(sent, long_text)

    @mock.patch("core.notify.time.sleep")
    @mock.patch("core.notify.requests.post")
    def test_retries_on_429_then_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [make_response(429), make_response(200)]
        send_telegram("hi", token=TOKEN, chat_id=CHAT_ID)
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once()

    @mock.patch("core.notify.time.sleep")
    @mock.patch("core.notify.requests.post")
    def test_non_retryable_4xx_raises_immediately(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(400)
        with self.assertRaises(requests.HTTPError):
            send_telegram("hi", token=TOKEN, chat_id=CHAT_ID)
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @mock.patch("core.notify.time.sleep")
    @mock.patch("core.notify.requests.post")
    def test_exhausts_retries_on_persistent_500(self, mock_post, mock_sleep):
        mock_post.return_value = make_response(500)
        with self.assertRaises(requests.HTTPError):
            send_telegram("hi", token=TOKEN, chat_id=CHAT_ID)
        self.assertEqual(mock_post.call_count, 5)

    @mock.patch("core.notify.requests.post")
    def test_token_redacted_from_raised_error(self, mock_post):
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        resp = make_response(401)
        resp.raise_for_status.side_effect = requests.HTTPError(f"401 Client Error: Unauthorized for url: {url}")
        mock_post.return_value = resp

        with self.assertRaises(requests.HTTPError) as ctx:
            send_telegram("hi", token=TOKEN, chat_id=CHAT_ID)

        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertIn("/bot***/sendMessage", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)

    @mock.patch("core.notify.time.sleep")
    @mock.patch("core.notify.requests.post")
    def test_token_redacted_from_retry_log_lines(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            requests.ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage"),
            make_response(200),
        ]
        with self.assertLogs("core.notify", level="WARNING") as logs:
            send_telegram("hi", token=TOKEN, chat_id=CHAT_ID)
        self.assertNotIn(TOKEN, "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
