"""Send messages to a Telegram chat via the Bot API, splitting long text."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
MAX_CHARS = 4000
TIMEOUT = 10
MAX_RETRIES = 5
BACKOFF_BASE = 1.0  # seconds; doubles each retry, so 1, 2, 4, 8, 16


def _split(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split text into chunks of at most max_chars, preferring newline boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n", 0, max_chars)
        if cut <= 0:  # no newline to break on; fall back to a hard cut
            cut = max_chars
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def _post_with_retry(url: str, payload: dict, token: str) -> None:
    """POST with a timeout; retry on 429/5xx with exponential backoff, capped. The bot token is
    part of the URL, so it is replaced with *** in log lines (error text can quote the URL)."""
    delay = BACKOFF_BASE
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, timeout=TIMEOUT)
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("telegram request failed (%s), retrying in %.0fs", str(e).replace(token, "***"), delay)
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code == 200:
            return
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            logger.warning(
                "telegram returned %d, retrying in %.0fs (attempt %d/%d)",
                response.status_code, delay, attempt, MAX_RETRIES,
            )
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()  # non-retryable 4xx


def send_telegram(text: str, *, token: str, chat_id: str) -> None:
    """Send text to a Telegram chat, splitting into multiple messages if too long.

    Errors are re-raised with the token replaced by ***: requests quotes the URL in its error
    messages, and callers log them, store them in runs.errors and repeat them in the run summary.
    """
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    try:
        for chunk in _split(text):
            _post_with_retry(url, {"chat_id": chat_id, "text": chunk}, token)
    except requests.RequestException as e:
        raise type(e)(str(e).replace(token, "***")) from None  # "from None": the original quotes the URL
