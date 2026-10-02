"""Call the Anthropic API for scoring: a plain HTTPS POST, no SDK."""

import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT = 30
MAX_RETRIES = 5
BACKOFF_BASE = 1.0  # seconds; doubles each retry, so 1, 2, 4, 8, 16

# $ per 1M tokens. Add an entry here when config/profile.toml's scoring.model changes.
PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
}

# Models that return a 400 if `temperature` is sent: sampling is fixed by the API.
NO_TEMPERATURE = {"claude-sonnet-5"}
# Models that think before answering unless told not to. Callers here expect a short, direct reply,
# so thinking is turned off for them; otherwise it would use part of max_tokens and could cut the reply.
THINKS_BY_DEFAULT = {"claude-sonnet-5"}


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cost: float | None  # None if the model isn't in PRICING


def _cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    rates = PRICING.get(model)
    if rates is None:
        return None
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def _post_with_retry(payload: dict, headers: dict) -> requests.Response:
    """POST with a timeout; retry on 429/5xx with exponential backoff, capped."""
    delay = BACKOFF_BASE
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=TIMEOUT)
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("anthropic request failed (%s), retrying in %.0fs", e, delay)
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code == 200:
            return response
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            logger.warning(
                "anthropic returned %d, retrying in %.0fs (attempt %d/%d)",
                response.status_code, delay, attempt, MAX_RETRIES,
            )
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()  # non-retryable 4xx
    raise RuntimeError("unreachable")  # loop always returns or raises


def complete(
    system: str, user: str, max_tokens: int, *, model: str, api_key: str, temperature: float | None = None
) -> Completion:
    """Send one message to Claude. Logs input/output tokens and estimated cost per call."""
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if temperature is not None and model not in NO_TEMPERATURE:
        payload["temperature"] = temperature
    if model in THINKS_BY_DEFAULT:
        payload["thinking"] = {"type": "disabled"}

    response = _post_with_retry(payload, headers)
    data = response.json()

    text = "".join(block["text"] for block in data["content"] if block["type"] == "text")
    usage = data.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cost = _cost(model, input_tokens, output_tokens)

    logger.info(
        "anthropic call: model=%s input_tokens=%d output_tokens=%d cost=%s",
        model, input_tokens, output_tokens, f"${cost:.5f}" if cost is not None else "unknown",
    )

    return Completion(text=text, input_tokens=input_tokens, output_tokens=output_tokens, cost=cost)
