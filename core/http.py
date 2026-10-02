"""Shared GET/POST-with-retry used by every job source: timeout, retry on 429/5xx with backoff."""

import logging
import time
from collections.abc import Callable

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 10
MAX_RETRIES = 5
BACKOFF_BASE = 1.0  # seconds; doubles each retry, so 1, 2, 4, 8, 16


def get_with_retry(url: str, *, label: str) -> requests.Response:
    """GET with a timeout; retry on 429/5xx with exponential backoff, capped.

    `label` identifies the caller (e.g. "greenhouse") in log lines only.
    """
    return _with_retry(lambda: requests.get(url, timeout=TIMEOUT), label)


def post_with_retry(url: str, payload: dict, *, label: str) -> requests.Response:
    """POST a JSON body, with the same timeout and retry policy as get_with_retry.

    For read-only search endpoints that take their query as a POST body (Workday's job list),
    so repeating the request is safe.
    """
    return _with_retry(lambda: requests.post(url, json=payload, timeout=TIMEOUT), label)


def _with_retry(send: Callable[[], requests.Response], label: str) -> requests.Response:
    delay = BACKOFF_BASE
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = send()
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("%s request failed (%s), retrying in %.0fs", label, e, delay)
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code == 200:
            return response
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            logger.warning(
                "%s returned %d, retrying in %.0fs (attempt %d/%d)",
                label, response.status_code, delay, attempt, MAX_RETRIES,
            )
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()  # non-retryable 4xx
    raise RuntimeError("unreachable")  # loop always returns or raises
