from __future__ import annotations

import re
from collections.abc import Iterable


WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
CN_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])")
EMAIL_SPACE_RE = re.compile(r"\s*([@._+-])\s*")
PHONE_CANDIDATE_RE = re.compile(r"(?:\+?86[- ]?)?1[3-9](?:[ -]?\d){9}")
REPEATED_PUNCT_RE = re.compile(r"([,，。；;：:、])\1{1,}")
YEAR_RANGE_RE = re.compile(r"\b((?:19|20)\d{2})((?:19|20)\d{2})\b")
MONTH_RANGE_RE = re.compile(r"\b((?:19|20)\d{2}[./](?:1[0-2]|0?[1-9]))((?:19|20)\d{2}[./](?:1[0-2]|0?[1-9]))\b")


def clean_text(text: str) -> str:
    text = normalize_common_symbols(text)
    text = CONTROL_RE.sub("", text)
    text = PRIVATE_USE_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = CN_SPACE_RE.sub("", text)
    text = REPEATED_PUNCT_RE.sub(r"\1", text)
    return BLANK_LINES_RE.sub("\n\n", text).strip()


def normalize_common_symbols(text: str) -> str:
    replacements = {
        "\u00a0": " ",
        "\ufeff": "",
        "＠": "@",
        "．": ".",
        "。com": ".com",
        "－": "-",
        "—": "-",
        "–": "-",
        "：": "：",
        "，": "，",
        "／": "/",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def normalize_email_candidates(text: str) -> str:
    return EMAIL_SPACE_RE.sub(r"\1", text)


def normalize_phone_candidates(text: str) -> str:
    def normalize_match(match: re.Match[str]) -> str:
        value = re.sub(r"[ -]", "", match.group(0))
        return value[2:] if value.startswith("86") and len(value) == 13 else value

    return PHONE_CANDIDATE_RE.sub(normalize_match, text)


def normalize_date_ranges(text: str) -> str:
    text = MONTH_RANGE_RE.sub(r"\1 - \2", text)
    return YEAR_RANGE_RE.sub(r"\1-\2", text)


def normalize_resume_text(text: str) -> str:
    text = normalize_date_ranges(text)
    text = normalize_email_candidates(text)
    text = normalize_phone_candidates(text)
    return clean_text(text)


def split_paragraphs(text: str) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    chunks = re.split(r"\n\s*\n|(?<=。)\s+", cleaned)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def truncate_text(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n...内容过长，已省略中间部分...\n\n{tail}"


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result
