"""Read and describe PAi Legal's four-position Trust Locks.

This module never assigns, promotes, or demotes a claim.  It only parses marks
that are already present so the UI, audit trail, tension detector, and exports
all use one canonical interpretation.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterator

from .epistemic import BracketType


MARKS = (
    (BracketType.VALIDATED, "[[[", "]]]"),
    (BracketType.EXPLAINED, "{[", "]}"),
    (BracketType.SPECULATIVE, "[[", "]]"),
    (BracketType.UNVERIFIED, "[{", "}]"),
)
SHORT = {
    BracketType.UNVERIFIED: "[{ }]",
    BracketType.SPECULATIVE: "[[ ]]",
    BracketType.EXPLAINED: "{[ ]}",
    BracketType.VALIDATED: "[[[ ]]]",
}
MEANING = {
    BracketType.UNVERIFIED: "Unverified",
    BracketType.SPECULATIVE: "Speculative",
    BracketType.EXPLAINED: "Explained",
    BracketType.VALIDATED: "Independently validated",
}
NOT_PROMOTED = "Pressure observed; status unchanged."

PATTERN = re.compile(
    r"\[\[\[(?P<validated>.*?)\]\]\]"
    r"|\{\[(?P<explained>.*?)\]\}"
    r"|(?<!\[)\[\[(?!\[)(?P<speculative>.*?)\]\](?!\])"
    r"|\[\{(?P<unverified>.*?)\}\]"
)
SOURCE_PATTERN = re.compile(r"\[(?:PSI:|RPM:)[^\]]+\]|\[[A-Za-z0-9_. -]+:\d+\]")
_GROUPS = {
    "validated": BracketType.VALIDATED,
    "explained": BracketType.EXPLAINED,
    "speculative": BracketType.SPECULATIVE,
    "unverified": BracketType.UNVERIFIED,
}


def spans(text: str) -> Iterator[tuple[int, int, BracketType, str]]:
    """Yield start, end, lock and inner claim for each complete mark."""
    for match in PATTERN.finditer(text):
        for group, bracket in _GROUPS.items():
            inner = match.group(group)
            if inner is not None:
                yield match.start(), match.end(), bracket, inner
                break


def count_claims(text: str) -> Counter:
    counts = Counter({bracket: 0 for bracket, _, _ in MARKS})
    for _start, _end, bracket, _inner in spans(text):
        counts[bracket] += 1
    return counts


def count_names(text: str) -> dict[str, int]:
    counts = count_claims(text)
    return {bracket.name: counts[bracket] for bracket, _, _ in MARKS}


def source_spans(text: str) -> Iterator[tuple[int, int, str]]:
    for match in SOURCE_PATTERN.finditer(text):
        yield match.start(), match.end(), match.group(0)


def summary(text: str) -> str:
    counts = count_claims(text)
    order = (BracketType.UNVERIFIED, BracketType.SPECULATIVE,
             BracketType.EXPLAINED, BracketType.VALIDATED)
    return "Claims: " + "  ".join(f"{counts[item]} {SHORT[item]}" for item in order) + f"  ·  {NOT_PROMOTED}"


def legend_markdown() -> str:
    rows = ["| Trust Lock | Meaning |", "| --- | --- |"]
    for bracket in (BracketType.UNVERIFIED, BracketType.SPECULATIVE,
                    BracketType.EXPLAINED, BracketType.VALIDATED):
        rows.append(f"| `{SHORT[bracket]}` | {MEANING[bracket]} |")
    rows += ["", "> Pressure and recurrence never promote or demote a claim's Trust Lock."]
    return "\n".join(rows)
