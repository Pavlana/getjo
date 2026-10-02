"""Whole-word matching shared by the filter and the search sources."""

import re


def names_any(text: str, terms: list[str]) -> bool:
    """True if text contains any term as a whole word or phrase, case-insensitive,
    so "us" doesn't match "Australia" and "Wise" doesn't match "Otherwise"."""
    text = text.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text) for term in terms)
