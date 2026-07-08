from __future__ import annotations

import re


ASCII_TOKEN_RE = re.compile(r"[a-z0-9+#.]", re.I)


def contains_term(text: str, term: str) -> bool:
    """Match technical terms without treating substrings as full skill hits."""
    normalized_text = (text or "").casefold()
    normalized_term = (term or "").strip().casefold()
    if not normalized_text or not normalized_term:
        return False

    if ASCII_TOKEN_RE.search(normalized_term):
        pattern = rf"(?<![a-z0-9+#.]){re.escape(normalized_term)}(?![a-z0-9+#.])"
        return bool(re.search(pattern, normalized_text))
    return normalized_term in normalized_text


def contains_any(text: str, terms: list[str] | tuple[str, ...] | set[str]) -> bool:
    return any(contains_term(text, term) for term in terms)


def matched_terms(text: str, terms: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    return [term for term in terms if contains_term(text, term)]
